# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import pytest
import os
import sys

from unittest import mock
from knack.util import CLIError
from azure.cli.core.extension import get_extension_path
from azext_iot.common.utility import (
    handle_service_exception,
    validate_min_python_version,
    process_json_arg,
    read_file_content,
    logger,
    ensure_iothub_sdk_min_version,
    ensure_iotdps_sdk_min_version,
)
from azext_iot.operations.generic import _process_top
from azext_iot.common.deps import ensure_uamqp
from azext_iot.constants import EVENT_LIB, EXTENSION_NAME
from azext_iot._validators import mode2_iot_login_handler
from azext_iot.common.embedded_cli import EmbeddedCLI


class TestMinPython(object):
    @pytest.mark.parametrize("pymajor, pyminor", [(3, 6), (3, 4), (2, 7)])
    def test_min_python(self, pymajor, pyminor):
        with mock.patch("azext_iot.common.utility.sys.version_info") as version_mock:
            version_mock.major = pymajor
            version_mock.minor = pyminor

            assert validate_min_python_version(2, 7)

    @pytest.mark.parametrize(
        "pymajor, pyminor, exception",
        [(3, 6, SystemExit), (3, 4, SystemExit), (2, 7, SystemExit)],
    )
    def test_min_python_error(self, pymajor, pyminor, exception):
        with mock.patch("azext_iot.common.utility.sys.version_info") as version_mock:
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
        installer = mocker.patch("azext_iot.common.deps.install")
        installer.return_value = True
        test_import = mocker.patch("azext_iot.common.deps.test_import_and_version")
        test_import.return_value = True
        m_exit = mocker.patch("azext_iot.common.deps.sys.exit")

        return {
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

        if uamqp_scenario["test_import"]:
            pass
        elif user_cancelled:
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
        [("../iothub/configurations/test_adm_device_content.json", "myarg0")],
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

    @pytest.mark.parametrize("content, argname", [("../generators.py", "myarg0")])
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


class TestVersionComparison(object):
    @pytest.mark.parametrize(
        "current, minimum, expected",
        [
            ("1.0", "2.0", False),
            ("1.8.7", "1.8.6.4", True),
            ("1.0+a", "1.0", True),
            ("1.0+a", "1.0+b", False),
            ("1.0", "1.0", True),
            ("2.0.1.9", "2.0.6", False),
        ],
    )
    def test_ensure_iothub_sdk_min_version(self, mocker, current, minimum, expected):
        try:
            mocker.patch("azure.mgmt.iothub.__version__", current)
        except Exception:
            mocker.patch("azure.mgmt.iothub._version.VERSION", current)

        assert ensure_iothub_sdk_min_version(minimum) == expected

    @pytest.mark.parametrize(
        "current, minimum, expected",
        [
            ("1.0", "2.0", False),
            ("1.8.7", "1.8.6.4", True),
            ("1.0+a", "1.0", True),
            ("1.0+a", "1.0+b", False),
            ("1.0", "1.0", True),
            ("2.0.1.9", "2.0.6", False),
        ],
    )
    def test_ensure_iotdps_sdk_min_version(self, mocker, current, minimum, expected):
        try:
            mocker.patch("azure.mgmt.iothubprovisioningservices.__version__", current)
        except Exception:
            mocker.patch(
                "azure.mgmt.iothubprovisioningservices._version.VERSION", current
            )

        assert ensure_iotdps_sdk_min_version(minimum) == expected


class TestEmbeddedCli(object):
    @pytest.fixture(params=[0, 1])
    def mocked_azclient(self, mocker, request):
        def mock_invoke(args, out_file):
            out_file.write(json.dumps({"generickey": "genericvalue"}))
            return request.param

        azclient = mocker.patch("azext_iot.common.embedded_cli.get_default_cli")
        azclient.return_value.invoke.side_effect = mock_invoke
        azclient.test_meta.error_code = request.param
        return azclient

    @pytest.mark.parametrize(
        "command, user_subscription, subscription",
        [
            ("iot hub device-identity create -n abcd -d dcba", None, None),
            (
                "iot hub device-twin show -n 'abcd' -d 'dcba'",
                "20a300e5-a444-4130-bb5a-1abd08ad930a",
                None,
            ),
            (
                "iot hub device-identity create -n abcd -d dcba",
                None,
                "20a300e5-a444-4130-bb5a-1abd08ad930a",
            ),
            (
                "iot hub device-twin show -n 'abcd' -d 'dcba'",
                "20a300e5-a444-4130-bb5a-1abd08ad930a",
                "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            ),
        ],
    )
    def test_embedded_cli(
        self, mocker, mocked_azclient, command, user_subscription, subscription
    ):
        import shlex

        cli_ctx = mocker.MagicMock()
        cli_ctx.data = {}
        if user_subscription:
            cli_ctx.data["subscription_id"] = user_subscription
        cli = EmbeddedCLI(cli_ctx)
        cli.invoke(command=command, subscription=subscription)

        # Due to forced json output
        command += " -o json"

        if subscription:
            command += " --subscription '{}'".format(subscription)
        elif user_subscription:
            command += " --subscription '{}'".format(user_subscription)

        expected_args = shlex.split(command)
        call = mocked_azclient().invoke.call_args_list[0]
        actual_args, _ = call
        assert expected_args == actual_args[0]
        success = cli.success()

        if mocked_azclient.test_meta.error_code == 1:
            assert not success
        elif mocked_azclient.test_meta.error_code == 0:
            assert success

        assert cli.output
        assert cli.as_json()


class TestCliInit(object):
    def test_package_init(self):
        from azext_iot.constants import EXTENSION_ROOT

        tests_root = "tests"
        directory_structure = {}

        def _validate_directory(path):
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False) and all(
                    [not entry.name.startswith("__"), tests_root not in entry.path]
                ):
                    directory_structure[entry.path] = None
                    _validate_directory(entry.path)
                else:
                    if entry.path.endswith("__init__.py"):
                        directory_structure[os.path.dirname(entry.path)] = entry.path

        _validate_directory(EXTENSION_ROOT)

        invalid_directories = []
        for directory in directory_structure:
            if directory_structure[directory] is None:
                invalid_directories.append(
                    "Directory: '{}' missing __init__.py".format(directory)
                )

        if invalid_directories:
            pytest.fail(", ".join(invalid_directories))

    def test_ensure_azure_namespace_path(self):
        import azure
        from azext_iot.common.utility import ensure_azure_namespace_path
        from azure.cli.core.extension import get_extension_path
        from azext_iot.constants import EXTENSION_NAME

        ext_path = get_extension_path(EXTENSION_NAME)

        original_sys_path = list(sys.path)
        original_azure_namespace_path = list(azure.__path__)
        ext_azure_dir = os.path.join(ext_path, "azure")

        os.makedirs(ext_azure_dir, exist_ok=True)

        ensure_azure_namespace_path()
        modified_sys_path = list(sys.path)
        modified_azure_namespace_path = list(azure.__path__)

        original_azure_namespace_path.append(ext_azure_dir)
        assert set(original_azure_namespace_path) == set(modified_azure_namespace_path)

        original_sys_path.insert(0, ext_path)
        assert set(original_sys_path) == set(modified_sys_path)
        assert modified_sys_path[0] == ext_path


class TestHandleServiceException(object):
    from azure.cli.core.azclierror import (
        AzureInternalError,
        AzureResponseError,
        BadRequestError,
        ForbiddenError,
        ResourceNotFoundError,
        UnauthorizedError,
    )

    @pytest.mark.parametrize(
        "status_code, expected_error",
        [
            (400, BadRequestError),
            (401, UnauthorizedError),
            (402, AzureResponseError),
            (403, ForbiddenError),
            (404, ResourceNotFoundError),
            (409, AzureResponseError),
            (500, AzureInternalError),
            (501, AzureInternalError),
            (502, AzureInternalError),
            (503, AzureInternalError),
            (504, AzureInternalError),
            (None, AzureResponseError),
        ],
    )
    def test_handle_service_exception(self, mocker, status_code, expected_error):
        error = mocker.MagicMock(name="mock error")
        error.response = mocker.MagicMock(name="mock response")
        error.response.status_code = status_code

        with pytest.raises(expected_error):
            handle_service_exception(error)


class TestFileHeaders(object):
    def test_file_headers(self):
        from azext_iot.constants import EXTENSION_ROOT

        header = """# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------"""

        files_missing_header = []
        sdk_root = "sdk"

        def _validate_directory(path):
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False) and sdk_root not in entry.path:
                    _validate_directory(entry.path)
                else:
                    if entry.is_file() and entry.path.endswith(".py"):
                        contents = None
                        with open(entry.path, "rt", encoding="utf-8") as f:
                            contents = f.read()
                        if contents and not contents.startswith(header):
                            files_missing_header.append(entry.path)

        _validate_directory(EXTENSION_ROOT)
        if files_missing_header:
            pytest.fail(
                "The following files are missing an encoding and license header, or it is improperly formatted:\n"
                "{}".format("\n".join(files_missing_header))
            )


class TestProcessTop(object):
    @pytest.mark.parametrize(
        "top, upper_limit",
        [
            (None, None),
            (-1, None),
            (5, None),
            (5, 5),
            (5, 10),
        ],
    )
    def test_process_top(self, mocker, top, upper_limit):
        processed_top = _process_top(top=top, upper_limit=upper_limit)
        if top and top >= 0:
            assert processed_top == top
        else:
            assert processed_top is None

    @pytest.mark.parametrize(
        "top, upper_limit",
        [
            (0, None),
            (-1, 100),
            (-3, None),
            (5, 4),
            (0, 0),
        ],
    )
    def test_process_top_error(self, mocker, top, upper_limit):
        with pytest.raises(CLIError) as e:
            _process_top(top=top, upper_limit=upper_limit)

        assert "top must be > 0" in e.value.error_msg
        if upper_limit:
            assert f" and <= {upper_limit}" in e.value.error_msg
