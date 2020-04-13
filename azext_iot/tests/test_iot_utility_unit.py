import pytest
import json
from knack.util import CLIError
from uamqp.message import Message, MessageProperties
from azure.cli.core.extension import get_extension_path
from azext_iot.common.utility import validate_min_python_version
from azext_iot.common.deps import ensure_uamqp
from azext_iot._validators import mode2_iot_login_handler
from azext_iot.constants import EVENT_LIB, EXTENSION_NAME
from azext_iot.common.utility import process_json_arg, read_file_content, logger
from azext_iot.operations.events3 import _parser


class TestMinPython(object):
    @pytest.mark.parametrize("pymajor, pyminor", [(3, 6), (3, 4), (2, 7)])
    def test_min_python(self, mocker, pymajor, pyminor):
        version_mock = mocker.patch("azext_iot.common.utility.sys.version_info")
        version_mock.major = pymajor
        version_mock.minor = pyminor

        assert validate_min_python_version(2, 7)

    @pytest.mark.parametrize(
        "pymajor, pyminor, exception",
        [(3, 6, SystemExit), (3, 4, SystemExit), (2, 7, SystemExit)],
    )
    def test_min_python_error(self, mocker, pymajor, pyminor, exception):
        version_mock = mocker.patch("azext_iot.common.utility.sys.version_info")
        version_mock.major = 2
        version_mock.minor = 6

        with pytest.raises(exception):
            validate_min_python_version(pymajor, pyminor)


class TestMode2Handler(object):
    @pytest.fixture(
        params=[
            {"hub_name": "myhub", "login": None},
            {"hub_name": None, "login": "connection_string"},
            {"hub_name": "myhub", "login": "connection_string"},
            {"hub_name": None, "login": None},
            {"dps_name": "mydps", "login": None},
            {"dps_name": None, "login": "connection_string"},
            {"dps_name": "mydps", "login": "connection_string"},
            {"dps_name": None, "login": None},
            {"cmd.name": "webapp", "login": None},
        ]
    )
    def mode2_scenario(self, mocker, request):
        from argparse import Namespace

        ns = Namespace()
        param = request.param
        for kw in param:
            setattr(ns, kw, param[kw])

        mock_cmd = mocker.MagicMock(name="mock cmd")
        custom_cmd_name = param.get("cmd.name")
        mock_cmd.name = custom_cmd_name if custom_cmd_name else "iot "

        scenario = {"namespace": ns, "cmd": mock_cmd, "param": param}
        return scenario

    def test_mode2_login(self, mode2_scenario):
        scenario_param = mode2_scenario["param"]
        if (
            not any([scenario_param.get("dps_name"), scenario_param.get("hub_name")])
            and not scenario_param["login"]
            and mode2_scenario["cmd"].name.startswith("iot")
        ):
            with pytest.raises(CLIError):
                mode2_iot_login_handler(
                    cmd=mode2_scenario["cmd"], namespace=mode2_scenario["namespace"]
                )
        else:
            mode2_iot_login_handler(
                cmd=mode2_scenario["cmd"], namespace=mode2_scenario["namespace"]
            )


class TestEnsureUamqp(object):
    @pytest.fixture()
    def uamqp_scenario(self, mocker):
        get_uamqp = mocker.patch("azext_iot.common.deps.get_uamqp_ext_version")
        update_uamqp = mocker.patch("azext_iot.common.deps.update_uamqp_ext_version")
        installer = mocker.patch("azext_iot.common.deps.install")
        installer.return_value = True
        get_uamqp.return_value = EVENT_LIB[1]
        test_import = mocker.patch("azext_iot.common.deps.test_import")
        test_import.return_value = True
        m_exit = mocker.patch("azext_iot.common.deps.sys.exit")

        return {
            "get_uamqp": get_uamqp,
            "update_uamqp": update_uamqp,
            "installer": installer,
            "test_import": test_import,
            "exit": m_exit,
        }

    @pytest.mark.parametrize(
        "case, extra_input, external_input",
        [
            ("importerror", None, "y"),
            ("importerror", None, "n"),
            ("importerror", "yes;", None),
            ("compatibility", None, "y"),
            ("compatibility", None, "n"),
            ("compatibility", "yes;", None),
            ("repair", "repair;", "y"),
            ("repair", "repair;yes;", None),
            ("repair", "repair;", "n"),
        ],
    )
    def test_ensure_uamqp_version(
        self, mocker, uamqp_scenario, case, extra_input, external_input
    ):
        from functools import partial

        if case == "importerror":
            uamqp_scenario["test_import"].return_value = False
        elif case == "compatibility":
            uamqp_scenario["get_uamqp"].return_value = "0.0.0"

        kwargs = {}
        user_cancelled = True
        if extra_input and "yes;" in extra_input:
            kwargs["yes"] = True
            user_cancelled = False
        if extra_input and "repair;" in extra_input:
            kwargs["repair"] = True
        if external_input:
            mocked_input = mocker.patch("azext_iot.common.deps.input")
            mocked_input.return_value = external_input
            if external_input.lower() == "y":
                user_cancelled = False

        method = partial(ensure_uamqp, mocker.MagicMock(), **kwargs)
        method()

        if user_cancelled:
            assert uamqp_scenario["exit"].call_args
        else:
            install_args = uamqp_scenario["installer"].call_args
            assert install_args[0][0] == EVENT_LIB[0]
            assert install_args[1]["compatible_version"] == EVENT_LIB[1]


class TestInstallPipPackage(object):
    @pytest.fixture()
    def subprocess_scenario(self, mocker):
        return mocker.patch("azext_iot.common.pip.subprocess")

    @pytest.fixture()
    def subprocess_error(self, mocker):
        from subprocess import CalledProcessError

        patch_check_output = mocker.patch(
            "azext_iot.common.pip.subprocess.check_output"
        )
        patch_check_output.side_effect = CalledProcessError(
            returncode=1, cmd="cmd", output=None
        )
        return patch_check_output

    @pytest.mark.parametrize(
        "install_type, package_name, expected",
        [
            ({"exact_version": "1.2"}, "uamqp", "uamqp==1.2"),
            ({"compatible_version": "1.2"}, "uamqp", "uamqp~=1.2"),
            ({"custom_version": ">=1.2,<1.3"}, "uamqp", "uamqp>=1.2,<1.3"),
        ],
    )
    def test_pip_install(
        self, subprocess_scenario, install_type, package_name, expected
    ):
        from azext_iot.common.pip import install
        from sys import executable

        install(package_name, **install_type)

        assert subprocess_scenario.check_output.call_count == 1

        call = subprocess_scenario.check_output.call_args[0][0]

        assert call == [
            executable,
            "-m",
            "pip",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "install",
            "-U",
            "--target",
            get_extension_path(EXTENSION_NAME),
            expected,
        ]

    def test_pip_error(self, subprocess_error):
        from azext_iot.common.pip import install

        with pytest.raises(RuntimeError):
            install("uamqp")


class TestProcessJsonArg(object):
    @pytest.mark.parametrize(
        "content, argname", [('{"authenticationType": "sas"}', "myarg0")]
    )
    def test_inline_json(self, content, argname):
        result = process_json_arg(content, argument_name=argname)
        assert result == json.loads(content)

    @pytest.mark.parametrize(
        "content, argname",
        [
            ('}"authenticationType": "sas"{', "myarg0"),
            ('{"authenticationType": }', "myarg1"),
        ],
    )
    def test_inline_json_fail(self, content, argname):
        with pytest.raises(CLIError) as exc_info:
            process_json_arg(content, argument_name=argname)

        assert str(exc_info.value).startswith(
            "Failed to parse json for argument '{}' with exception:\n".format(argname)
        )

    @pytest.mark.parametrize(
        "content, argname",
        [("iothub/configurations/test_adm_device_content.json", "myarg0")],
    )
    def test_file_json(self, content, argname, set_cwd):
        result = process_json_arg(content, argument_name=argname)
        assert result == json.loads(read_file_content(content))

    @pytest.mark.parametrize(
        "content, argname", [("test_config_device_content_nothere.json", "myarg0")]
    )
    def test_file_json_fail_invalidpath(self, content, argname, set_cwd, mocker):
        mocked_util_logger = mocker.patch.object(logger, "warning", autospec=True)

        with pytest.raises(CLIError) as exc_info:
            process_json_arg(content, argument_name=argname)

        assert str(exc_info.value).startswith(
            "Failed to parse json for argument '{}' with exception:\n".format(argname)
        )
        assert mocked_util_logger.call_count == 1
        assert (
            mocked_util_logger.call_args[0][0]
            == "The json payload for argument '%s' looks like its intended from a file. Please ensure the file path is correct."
        )
        assert mocked_util_logger.call_args[0][1] == argname

    @pytest.mark.parametrize("content, argname", [("generators.py", "myarg0")])
    def test_file_json_fail_invalidcontent(self, content, argname, set_cwd, mocker):
        mocked_util_logger = mocker.patch.object(logger, "warning", autospec=True)

        with pytest.raises(CLIError) as exc_info:
            process_json_arg(content, argument_name=argname)

        assert str(exc_info.value).startswith(
            "Failed to parse json from file: '{}' for argument '{}' with exception:\n".format(
                content, argname
            )
        )
        assert mocked_util_logger.call_count == 0


@pytest.mark.skipif(
    not validate_min_python_version(3, 5, exit_on_fail=False),
    reason="minimum python version not satisfied",
)
class TestEvents3Parser:
    device_id = "some-device-id"
    payload = {"someProperty": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"

    bad_encoding = "ascii"
    bad_payload = "bad-payload"
    bad_content_type = "bad-content-type"

    def test_parse_message_should_succeed(self):
        # setup
        app_prop_type = "some_app_prop"
        app_prop_value = "some_app_value"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
            application_properties={app_prop_type.encode(): app_prop_value.encode()},
        )
        parser = _parser.Event3Parser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=False,
            interface_name=None,
            properties={"all"},
            content_type_hint=None,
            simulate_errors=False,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        device_identifier = str(_parser.DEVICE_ID_IDENTIFIER, "utf8")
        assert parsed_msg["event"]["annotations"][device_identifier] == self.device_id

        properties = parsed_msg["event"]["properties"]
        assert properties["system"]["content_encoding"] == self.encoding
        assert properties["system"]["content_type"] == self.content_type
        assert properties["application"][app_prop_type] == app_prop_value

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

    def test_parse_message_pnp_should_succeed(self):
        # setup
        interface_name = "interface_name"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={
                _parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                _parser.INTERFACE_NAME_IDENTIFIER: interface_name.encode(),
            },
        )
        parser = _parser.Event3Parser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=True,
            interface_name=interface_name,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
        )

        # verify
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["interface"] == interface_name

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

    def test_parse_message_bad_content_type_should_warn(self):
        # setup
        encoded_payload = json.dumps(self.payload).encode()
        properties = MessageProperties(
            content_type=self.bad_content_type
        )
        message = Message(
            body=encoded_payload,
            properties=properties,
            annotations={_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = _parser.Event3Parser()

        # act
        parsed_msg = parser.parse_message(message, None, None, None, None, False)

        # verify
        # since the content_encoding header is not present, just dump the raw payload
        assert parsed_msg["event"]["payload"] == str(encoded_payload, "utf8")

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 1
        assert len(parser._info) == 0

        warning = parser._warnings[0]
        assert "Content type not supported." in warning
        assert self.bad_content_type in warning
        assert "application/json" in warning
        assert self.device_id in warning

        error = parser._errors[0]
        assert "No encoding found for message" in error

    def test_parse_message_bad_encoding_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.bad_encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(self.bad_encoding),
            properties=properties,
            annotations={_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = _parser.Event3Parser()

        # act
        parser.parse_message(message, None, None, None, None, False)

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert "Unsupported encoding detected: '{}'".format(self.bad_encoding) in errors

    def test_parse_message_bad_json_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=self.bad_payload.encode(),
            properties=properties,
            annotations={_parser.DEVICE_ID_IDENTIFIER: self.device_id.encode()},
        )
        parser = _parser.Event3Parser()

        # act
        parsed_msg = parser.parse_message(message, None, None, None, None, False)

        # verify
        # parsing should attempt to place raw payload into result even if parsing fails
        assert parsed_msg["event"]["payload"] == self.bad_payload

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert "Invalid JSON format." in errors
        assert self.device_id in errors
        assert self.bad_payload in errors

    def test_parse_message_pnp_should_fail(self):
        # setup
        actual_interface_name = "actual_interface_name"
        expected_interface_name = "expected_interface_name"
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={
                _parser.DEVICE_ID_IDENTIFIER: self.device_id.encode(),
                _parser.INTERFACE_NAME_IDENTIFIER: actual_interface_name.encode(),
            },
        )
        parser = _parser.Event3Parser()

        # act
        parsed_msg = parser.parse_message(
            message=message,
            pnp_context=True,
            interface_name=expected_interface_name,
            properties=None,
            content_type_hint=None,
            simulate_errors=False,
        )

        # verify
        # all the items should still be parsed and available, but we should have an error
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == self.device_id
        assert parsed_msg["event"]["interface"] == actual_interface_name

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        actual_error = parser._errors[0]
        expected_error = "Inteface name mismatch. {}. Expected: {}, Actual: {}".format(
            self.device_id, expected_interface_name, actual_interface_name
        )
        assert actual_error == expected_error
