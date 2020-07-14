# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import mock
import pytest
import json
import ast
from datetime import datetime
from knack.util import CLIError
from azure.cli.core.mock import DummyCli
from azext_iot.central import commands_device_twin
from azext_iot.central import commands_monitor
from azext_iot.common.shared import SdkType
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.template import Template
from azext_iot.monitor.property import PropertyMonitor
from azext_iot.monitor.models.enum import Severity
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

    mock = mocker.patch("azext_iot.central.providers.devicetwin_provider._bind_sdk")
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
            get_iot_central_tokens(Cmd(), "app_id", "", "api-uri").value()
            == "fixture_requests_post value"
        )

    def test_get_aad_token(self, fixture_azure_profile):
        from azext_iot.common.auth import get_aad_token

        class Cmd:
            cli_ctx = ""

        # Test to ensure _get_aad_token is called and returns the right values based on profile.get_raw_tokens
        assert get_aad_token(Cmd(), "resource") == {
            "accessToken": "raw token 0 -b",
            "expiresOn": "value",
            "subscription": "raw token 1",
            "tenant": "raw token 2",
            "tokenType": "raw token 0 - A",
        }


class TestDeviceTwinShow:
    def test_device_twin_show_calls_get_twin(
        self, fixture_bind_sdk, fixture_cmd, fixture_get_iot_central_tokens
    ):
        result = commands_device_twin.device_twin_show(fixture_cmd, device_id, app_id)

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
            commands_monitor.monitor_events(fixture_cmd, app_id, timeout=timeout)


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


class TestCentralPropertyMonitor:
    _device_twin = load_json(FileNames.central_device_twin_file)
    _duplicate_property_template = load_json(
        FileNames.central_property_validation_template_file
    )

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_updated_properties(
        self, mock_device_svc, mock_device_template_svc
    ):
        # setup
        device_twin_data = json.dumps(self._device_twin)
        raw_twin = ast.literal_eval(
            device_twin_data.replace("current_time", datetime.now().isoformat())
        )

        twin = DeviceTwin(raw_twin)
        twin_next = DeviceTwin(raw_twin)
        twin_next.reported_property.version = twin.reported_property.version + 1
        monitor = PropertyMonitor(
            cmd=None, app_id=app_id, device_id=device_id, central_dns_suffix=None,
        )
        result = monitor._compare_properties(
            twin_next.reported_property, twin.reported_property
        )
        assert len(result) == 3
        assert len(result["$iotin:urn_azureiot_Client_SDKInformation"]) == 3
        assert result["$iotin:urn_azureiot_Client_SDKInformation"]["language"]
        assert result["$iotin:urn_azureiot_Client_SDKInformation"]["version"]
        assert result["$iotin:urn_azureiot_Client_SDKInformation"]["vendor"]

        assert len(result["$iotin:deviceinfo"]) == 8
        assert result["$iotin:deviceinfo"]["manufacturer"]
        assert result["$iotin:deviceinfo"]["model"]
        assert result["$iotin:deviceinfo"]["osName"]
        assert result["$iotin:deviceinfo"]["processorArchitecture"]
        assert result["$iotin:deviceinfo"]["swVersion"]
        assert result["$iotin:deviceinfo"]["processorManufacturer"]
        assert result["$iotin:deviceinfo"]["totalStorage"]
        assert result["$iotin:deviceinfo"]["totalMemory"]

        assert len(result["$iotin:settings"]) == 1
        assert result["$iotin:settings"]["fanSpeed"]

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_should_return_no_properties(
        self, mock_device_svc, mock_device_template_svc
    ):
        # test to check that no property updates are reported when version is not upadted
        # setup
        device_twin_data = json.dumps(self._device_twin)
        raw_twin = ast.literal_eval(
            device_twin_data.replace("current_time", datetime.now().isoformat())
        )
        twin = DeviceTwin(raw_twin)
        twin_next = DeviceTwin(raw_twin)
        monitor = PropertyMonitor(
            cmd=None, app_id=app_id, device_id=device_id, central_dns_suffix=None,
        )
        result = monitor._compare_properties(
            twin_next.reported_property, twin.reported_property
        )
        assert result is None

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_declared_multiple_interfaces(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = Template(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None, app_id=app_id, device_id=device_id, central_dns_suffix=None,
        )

        model = {"Model": "test_model"}

        issues = monitor._validate_payload_against_interfaces(
            model, list(model.keys())[0], Severity.warning,
        )

        assert (
            issues[0].details == "Duplicate property: 'Model' found under following "
            "interfaces ['groupOne_g4', 'groupTwo_ed', 'groupThree_ed'] "
            "in the device model. Either provide the interface name as part "
            "of the device payload or make the propery name unique in the device model"
        )

        version = {"OsName": "test_osName"}

        issues = monitor._validate_payload_against_interfaces(
            version, list(version.keys())[0], Severity.warning,
        )

        assert len(issues) == 0

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_name_miss(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = Template(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None, app_id=app_id, device_id=device_id, central_dns_suffix=None,
        )

        # invalid interface / property
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_interfaces(
            definition, list(definition.keys())[0], Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device "
            "template. Following capabilities have NOT been defined in the device template "
            "'['definition']'. Following capabilities have been defined in the device template "
            "(grouped by interface) '{'groupOne_g4': ['Model', 'Version', 'TotalStorage'], "
            "'groupTwo_ed': ['Model', 'Manufacturer'], 'groupThree_ed': ['Manufacturer', "
            "'Version', 'Model', 'OsName']}'. "
        )

        # invalid and valid property with valid interface
        property_collection = {
            "Model": "test_model",
            "Manufacturer": "test_manufacturer",
            "OsName": "test_osName",
        }

        issues = monitor._validate_payload_against_interfaces(
            property_collection, "groupOne_g4", Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device "
            "template. Following capabilities have NOT been defined in the device template "
            "'['Manufacturer', 'OsName']'. Following capabilities have been defined in the device template "
            "(grouped by interface) '{'groupOne_g4': ['Model', 'Version', 'TotalStorage'], "
            "'groupTwo_ed': ['Model', 'Manufacturer'], 'groupThree_ed': ['Manufacturer', "
            "'Version', 'Model', 'OsName']}'. "
        )

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_severity_level(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = Template(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None, app_id=app_id, device_id=device_id, central_dns_suffix=None,
        )

        # severity level info
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_interfaces(
            definition, list(definition.keys())[0], Severity.info,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device "
            "template. Following capabilities have NOT been defined in the device template "
            "'['definition']'. Following capabilities have been defined in the device template "
            "(grouped by interface) '{'groupOne_g4': ['Model', 'Version', 'TotalStorage'], "
            "'groupTwo_ed': ['Model', 'Manufacturer'], 'groupThree_ed': ['Manufacturer', "
            "'Version', 'Model', 'OsName']}'. "
        )

        # severity level error
        issues = monitor._validate_payload_against_interfaces(
            definition, list(definition.keys())[0], Severity.error,
        )

        assert len(issues) == 0
