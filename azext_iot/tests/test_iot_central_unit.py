# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=W0613,W0621

from azext_iot.operations import central as subject
from azext_iot.common.shared import SdkType
from azure.cli.core.mock import DummyCli
import mock
import pytest
from knack.util import CLIError
from azext_iot.common.utility import validate_min_python_version

device_id = 'mydevice'
app_id = 'myapp'
device_twin_result = '{device twin result}'
resource = 'shared_resource'

@pytest.fixture()
def fixture_iot_token(mocker):
    sas = mocker.patch('azext_iot.operations.central.get_iot_hub_token_from_central_app_id')
    sas.return_value = 'SharedAccessSignature sr={}&sig=signature&se=expiry&skn=service'.format(resource)
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

    mock = mocker.patch('azext_iot.operations.central._bind_sdk')
    mock.return_value = (mock_service_sdk(), None)
    return mock


class TestDeviceTwinShow():

    def test_device_twin_show_calls_get_twin(self, fixture_iot_token, fixture_bind_sdk, fixture_cmd):
        result = subject.iot_central_device_show(fixture_cmd, device_id, app_id)

        # Ensure get_twin is called and result is returned
        assert result is device_twin_result

        # Ensure _bind_sdk is called with correct parameters
        assert fixture_bind_sdk.called is True
        args = fixture_bind_sdk.call_args
        assert args[0] == ({'entity': resource}, SdkType.service_sdk)


@pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
class TestMonitorEvents():
    @pytest.mark.parametrize("timeout, exception", [
        (-1, CLIError),
    ])
    def test_monitor_events_invalid_args(self, timeout, exception, fixture_cmd):
        with pytest.raises(exception):
            subject.iot_central_monitor_events(fixture_cmd, app_id, timeout=timeout)
