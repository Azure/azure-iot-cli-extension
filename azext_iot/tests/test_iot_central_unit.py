# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import mock
import pytest

from knack.util import CLIError
from azure.cli.core.mock import DummyCli
from azext_iot.operations import central as subject
from azext_iot.common.shared import SdkType
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)

from .helpers import load_json
from .test_constants import FileNames


device_id = "mydevice"
app_id = "myapp"
device_twin_result = "{device twin result}"
resource = "shared_resource"


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
def fixture_get_iot_central_tokens(mocker):
    mock = mocker.patch("azext_iot.common._azure.get_iot_central_tokens")

    mock.return_value = {
        "id": {
            "eventhubSasToken": {
                "hostname": "part1/part2/part3",
                "entityPath": "entityPath",
                "sasToken": "sasToken",
            },
            "expiry": "0000",
            "iothubTenantSasToken": {
                "sasToken": "SharedAccessSignature sr=shared_resource&sig="
            },
        }
    }


class TestCentralHelpers:
    def test_get_iot_central_tokens(self, fixture_requests_post, fixture_azure_profile):
        from azext_iot.common._azure import get_iot_central_tokens

        class Cmd:
            cli_ctx = ""

        # Test to ensure get_iot_central_tokens calls requests.post and tokens are returned
        assert (
            get_iot_central_tokens(Cmd(), "app_id", "api-uri").value()
            == "fixture_requests_post value"
        )


class TestDeviceTwinShow:
    def test_device_twin_show_calls_get_twin(
        self, fixture_bind_sdk, fixture_cmd, fixture_get_iot_central_tokens
    ):
        result = subject.iot_central_device_show(fixture_cmd, device_id, app_id)

        # Ensure get_twin is called and result is returned
        assert result is device_twin_result

        # Ensure _bind_sdk is called with correct parameters
        assert fixture_bind_sdk.called is True
        args = fixture_bind_sdk.call_args
        assert args[0] == ({"entity": resource}, SdkType.service_sdk)


class TestMonitorEvents:
    @pytest.mark.parametrize("timeout, exception", [(-1, CLIError)])
    def test_monitor_events_invalid_args(self, timeout, exception, fixture_cmd):
        with pytest.raises(exception):
            subject.iot_central_monitor_events(fixture_cmd, app_id, timeout=timeout)


class TestCentralDeviceProvider:
    _device = load_json(FileNames.central_device_file)
    _device_template = load_json(FileNames.central_device_template_file)

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_device(self, mock_device_svc, mock_device_template_svc):
        # setup
        provider = CentralDeviceProvider(cmd=None, app_id=app_id)
        mock_device_svc.get_device.return_value = self._device
        mock_device_template_svc.get_device_template.return_value = (
            self._device_template
        )

        # act
        device = provider.get_device("someDeviceId")
        # check that caching is working
        device = provider.get_device("someDeviceId")

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_svc.get_device.call_count == 1
        assert mock_device_svc.get_device_template.call_count == 0
        assert device == self._device

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_device_template(
        self, mock_device_svc, mock_device_template_svc
    ):
        # setup
        provider = CentralDeviceTemplateProvider(cmd=None, app_id=app_id)
        mock_device_svc.get_device.return_value = self._device
        mock_device_template_svc.get_device_template.return_value = (
            self._device_template
        )

        # act
        template = provider.get_device_template("someDeviceTemplate")
        # check that caching is working
        template = provider.get_device_template("someDeviceTemplate")

        # verify
        # call counts should be at most 1 since the provider has a cache
        assert mock_device_template_svc.get_device_template.call_count == 1
        assert template == self._device_template
