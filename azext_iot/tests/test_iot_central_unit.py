# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import mock
import pytest

from knack.util import CLIError
from uamqp.message import Message, MessageProperties
from azext_iot.operations import central as subject
from azext_iot.common.shared import SdkType
from azure.cli.core.mock import DummyCli
from azext_iot.common.utility import validate_min_python_version
from azext_iot.models import parsers


device_id = "mydevice"
app_id = "myapp"
device_twin_result = "{device twin result}"
resource = "shared_resource"


@pytest.fixture()
def fixture_iot_token(mocker):
    sas = mocker.patch(
        "azext_iot.operations.central.get_iot_hub_token_from_central_app_id"
    )
    sas.return_value = "SharedAccessSignature sr={}&sig=signature&se=expiry&skn=service".format(
        resource
    )
    return sas


@pytest.fixture()
def fixture_cmd(mocker):
    # Placeholder for later use
    cmd = mock.MagicMock()
    cmd.cli_ctx = DummyCli()
    return cmd


@pytest.fixture()
def fixture_bind_sdk(mocker):
    class mock_service_sdk:
        def get_twin(self, device_id):
            return device_twin_result

    mock = mocker.patch("azext_iot.operations.central._bind_sdk")
    mock.return_value = (mock_service_sdk(), None)
    return mock


@pytest.fixture()
def fixture_requests_post(mocker):
    class MockJsonObject:
        def get(self, _value):
            return ""

        def value(self):
            return "fixture_requests_post value"

    class ReturnObject:
        def json(self):
            return MockJsonObject()

    mock = mocker.patch("requests.post")
    mock.return_value = ReturnObject()


@pytest.fixture()
def fixture_azure_profile(mocker):
    mock = mocker.patch("azure.cli.core._profile.Profile.__init__")
    mock.return_value = None

    mock_method = mocker.patch("azure.cli.core._profile.Profile.get_raw_token")

    class MockTokenWithGet:
        def get(self, _value, _default):
            return "value"

    mock_method.return_value = [
        ["raw token 0 - A", "raw token 0 -b", MockTokenWithGet()],
        "raw token 1",
        "raw token 2",
    ]


@pytest.fixture()
def fixture_get_aad_token(mocker):
    mock = mocker.patch("azext_iot.common._azure._get_aad_token")
    mock.return_value = {"accessToken": "token"}


@pytest.fixture()
def fixture_get_iot_central_tokens(mocker):
    mock = mocker.patch("azext_iot.common._azure.get_iot_central_tokens")

    mock.return_value = {
        "eventhubSasToken": {
            "hostname": "part1/part2/part3",
            "entityPath": "entityPath",
            "sasToken": "sasToken",
        },
        "expiry": "0000",
        "iothubTenantSasToken": {"sasToken": "iothubTenantSasToken"},
    }


class TestCentralHelpers:
    def test_get_iot_central_tokens(self, fixture_requests_post, fixture_get_aad_token):
        from azext_iot.common._azure import get_iot_central_tokens

        # Test to ensure get_iot_central_tokens calls requests.post and tokens are returned
        assert (
            get_iot_central_tokens({}, "app_id", "api-uri").value()
            == "fixture_requests_post value"
        )

    def test_get_aad_token(self, fixture_azure_profile):
        from azext_iot.common._azure import _get_aad_token

        class Cmd:
            cli_ctx = "test"

        # Test to ensure _get_aad_token is called and returns the right values based on profile.get_raw_tokens
        assert _get_aad_token(Cmd(), "resource") == {
            "accessToken": "raw token 0 -b",
            "expiresOn": "value",
            "subscription": "raw token 1",
            "tenant": "raw token 2",
            "tokenType": "raw token 0 - A",
        }

    def test_get_iot_hub_token_from_central_app_id(
        self, fixture_get_iot_central_tokens
    ):
        from azext_iot.common._azure import get_iot_hub_token_from_central_app_id

        # Test to ensure get_iot_hub_token_from_central_app_id returns iothubTenantSasToken
        assert (
            get_iot_hub_token_from_central_app_id({}, "app_id", "api-uri")
            == "iothubTenantSasToken"
        )


class TestDeviceTwinShow:
    def test_device_twin_show_calls_get_twin(
        self, fixture_iot_token, fixture_bind_sdk, fixture_cmd
    ):
        result = subject.iot_central_device_show(
            fixture_cmd, device_id, app_id, "api-uri"
        )

        # Ensure get_twin is called and result is returned
        assert result is device_twin_result

        # Ensure _bind_sdk is called with correct parameters
        assert fixture_bind_sdk.called is True
        args = fixture_bind_sdk.call_args
        assert args[0] == ({"entity": resource}, SdkType.service_sdk)


@pytest.mark.skipif(
    not validate_min_python_version(3, 5, exit_on_fail=False),
    reason="minimum python version not satisfied",
)
class TestMonitorEvents:
    @pytest.mark.parametrize("timeout, exception", [(-1, CLIError)])
    def test_monitor_events_invalid_args(self, timeout, exception, fixture_cmd):
        with pytest.raises(exception):
            subject.iot_central_monitor_events(fixture_cmd, app_id, timeout=timeout)


@pytest.mark.skipif(
    not validate_min_python_version(3, 5, exit_on_fail=False),
    reason="minimum python version not satisfied",
)
class TestEvents3Parser:
    payload = {"someProperty": "someValue"}
    encoding = "UTF-8"
    content_type = "application/json"

    bad_encoding = "bad-encoding"
    bad_payload = "bad-payload"
    bad_content_type = "bad-content-type"

    def test_parse_message_should_succeed(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={parsers.DEVICE_ID_IDENTIFIER: device_id.encode()},
        )
        parser = parsers.Event3Parser()

        # act
        parsed_msg = parser.parse_msg(message, None, None, None, None, False)

        # verify
        assert parsed_msg["event"]["payload"] == self.payload
        assert parsed_msg["event"]["origin"] == device_id

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

    def test_parse_message_bad_encoding_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.bad_encoding, content_type=self.content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={parsers.DEVICE_ID_IDENTIFIER: device_id.encode()},
        )
        parser = parsers.Event3Parser()

        # act
        parsed_msg = parser.parse_msg(message, None, None, None, None, False)

        # verify
        assert parsed_msg == {}

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert f"Unsupported encoding detected: '{self.bad_encoding}'" in errors

    def test_parse_message_bad_json_should_fail(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.content_type
        )
        message = Message(
            body=self.bad_payload.encode(),
            properties=properties,
            annotations={parsers.DEVICE_ID_IDENTIFIER: device_id.encode()},
        )
        parser = parsers.Event3Parser()

        # act
        parsed_msg = parser.parse_msg(message, None, None, None, None, False)

        # verify
        assert parsed_msg == {}

        assert len(parser._errors) == 1
        assert len(parser._warnings) == 0
        assert len(parser._info) == 0

        errors = parser._errors[0]
        assert f"Invalid JSON format." in errors
        assert device_id in errors
        assert self.bad_payload in errors

    def test_parse_message_bad_content_type_should_warn(self):
        # setup
        properties = MessageProperties(
            content_encoding=self.encoding, content_type=self.bad_content_type
        )
        message = Message(
            body=json.dumps(self.payload).encode(),
            properties=properties,
            annotations={parsers.DEVICE_ID_IDENTIFIER: device_id.encode()},
        )
        parser = parsers.Event3Parser()

        # act
        parsed_msg = parser.parse_msg(message, None, None, None, None, False)

        # verify
        assert parsed_msg["event"]["payload"] == self.payload

        assert len(parser._errors) == 0
        assert len(parser._warnings) == 1
        assert len(parser._info) == 0

        warning = parser._warnings[0]
        assert "Message contains custom headers." in warning
        assert (
            "Custom headers are not supported and will be dropped from the message"
            in warning
        )
        assert device_id in warning
