# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import mock
import pytest
import json
import responses
import ast
from datetime import datetime
from knack.util import CLIError
from azure.cli.core.mock import DummyCli
from azext_iot.central import commands_device_twin
from azext_iot.central import commands_device
from azext_iot.central import commands_monitor
from azext_iot.central.providers.v1 import (
    CentralDeviceProviderV1,
    CentralDeviceTemplateProviderV1,
)
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central import models as central_models
from azext_iot.monitor.property import PropertyMonitor
from azext_iot.monitor.models.enum import Severity
from azext_iot.tests.helpers import load_json
from azext_iot.tests.test_constants import FileNames
from azext_iot.constants import PNP_DTDLV2_COMPONENT_MARKER

device_id = "mydevice"
app_id = "myapp"
device_twin_result = {"deviceId": "{}".format(device_id)}
resource = "shared_resource"
success_resp = {"result": "success"}


@pytest.fixture()
def fixture_cmd(mocker):
    # Placeholder for later use
    cmd = mock.MagicMock()
    cmd.cli_ctx = DummyCli()
    return cmd


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
    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_cmd, fixture_get_iot_central_tokens
    ):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/twins/{}".format(resource, device_id),
            body=json.dumps(device_twin_result),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_device_twin_show_calls_get_twin(self, service_client):
        result = commands_device_twin.device_twin_show(fixture_cmd, device_id, app_id)
        assert result == device_twin_result


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
        provider = CentralDeviceProviderV1(cmd=None, app_id=app_id)
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
        provider = CentralDeviceTemplateProviderV1(cmd=None, app_id=app_id)
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
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
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
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
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
        mock_device_template_svc.get_device_template.return_value = central_models.TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        model = {"Model": "test_model"}

        issues = monitor._validate_payload_against_entities(
            model, list(model.keys())[0], Severity.warning,
        )

        assert (
            issues[0].details == "Duplicate property: 'Model' found under following "
            "interfaces ['urn:sampleApp:groupOne_bz:_rpgcmdpo:1', 'urn:sampleApp:groupTwo_bz:myxqftpsr:2', "
            "'urn:sampleApp:groupThree_bz:myxqftpsr:2'] "
            "in the device model. Either provide the interface name as part "
            "of the device payload or make the propery name unique in the device model"
        )

        version = {"OsName": "test_osName"}

        issues = monitor._validate_payload_against_entities(
            version, list(version.keys())[0], Severity.warning,
        )

        assert len(issues) == 0

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_name_miss_under_interface(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = central_models.TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # invalid interface / property
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_entities(
            definition, list(definition.keys())[0], Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template."
            " Following capabilities have NOT been defined in the device template '['definition']'."
            " Following capabilities have been defined in the device template (grouped by interface)"
            " '{'urn:sampleApp:groupOne_bz:2': ['addRootProperty', 'addRootPropertyReadOnly', 'addRootProperty2'],"
            " 'urn:sampleApp:groupOne_bz:_rpgcmdpo:1': ['Model', 'Version', 'TotalStorage'],"
            " 'urn:sampleApp:groupTwo_bz:myxqftpsr:2': ['Model', 'Manufacturer'],"
            " 'urn:sampleApp:groupThree_bz:myxqftpsr:2': ['Manufacturer', 'Version', 'Model', 'OsName']}'. "
        )

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_severity_level(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = central_models.TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # severity level info
        definition = {"definition": "test_definition"}

        issues = monitor._validate_payload_against_entities(
            definition, list(definition.keys())[0], Severity.info,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template. "
            "Following capabilities have NOT been defined in the device template "
            "'['definition']'. Following capabilities have been defined in the device template "
            "(grouped by interface) '{'urn:sampleApp:groupOne_bz:2': "
            "['addRootProperty', 'addRootPropertyReadOnly', 'addRootProperty2'], "
            "'urn:sampleApp:groupOne_bz:_rpgcmdpo:1': ['Model', 'Version', 'TotalStorage'], "
            "'urn:sampleApp:groupTwo_bz:myxqftpsr:2': ['Model', 'Manufacturer'], "
            "'urn:sampleApp:groupThree_bz:myxqftpsr:2': ['Manufacturer', 'Version', 'Model', 'OsName']}'. "
        )

        # severity level error
        issues = monitor._validate_payload_against_entities(
            definition, list(definition.keys())[0], Severity.error,
        )

        assert len(issues) == 0

    @mock.patch("azext_iot.central.services.device_template")
    @mock.patch("azext_iot.central.services.device")
    def test_validate_properties_name_miss_under_component(
        self, mock_device_svc, mock_device_template_svc
    ):

        # setup
        mock_device_template_svc.get_device_template.return_value = central_models.TemplateV1(
            self._duplicate_property_template
        )

        monitor = PropertyMonitor(
            cmd=None,
            app_id=app_id,
            device_id=device_id,
            token=None,
            central_dns_suffix=None,
        )

        # invalid component property
        definition = {
            PNP_DTDLV2_COMPONENT_MARKER: "c",
            "data": {"definition": "test_definition"},
        }

        issues = monitor._validate_payload_against_entities(
            definition, list(definition.keys())[0], Severity.warning,
        )

        assert (
            issues[0].details
            == "Device is sending data that has not been defined in the device template. "
            "Following capabilities have NOT been defined in the device template '['data']'. "
            "Following capabilities have been defined in the device template (grouped by components) "
            "'{'_rpgcmdpo': ['component1Prop', 'testComponent', 'component1PropReadonly', 'component1Prop2'], "
            "'RS40OccupancySensorV36fy': ['component2prop', 'testComponent', 'component2PropReadonly', "
            "'component2Prop2', 'component1Telemetry']}'. "
        )


class TestFailover:

    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_cmd, fixture_get_iot_central_tokens
    ):

        mocked_response.add(
            method=responses.POST,
            url="https://myapp.azureiotcentral.com/system/iothub/devices/{}/manual-failover".format(device_id),
            body=json.dumps(success_resp),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_should_run_manual_failover(
        self, service_client
    ):
        # act
        result = commands_device.run_manual_failover(fixture_cmd, app_id, device_id, ttl_minutes=10, token="Shared sig")
        # assert
        assert result == success_resp

    def test_should_fail_negative_ttl(self):
        with pytest.raises(CLIError):
            # act
            commands_device.run_manual_failover(fixture_cmd, app_id, device_id, ttl_minutes=-10, token="Shared sig")


class TestFailback:

    @pytest.fixture
    def service_client(
        self, mocked_response, fixture_cmd, fixture_get_iot_central_tokens
    ):

        mocked_response.add(
            method=responses.POST,
            url="https://myapp.azureiotcentral.com/system/iothub/devices/{}/manual-failback".format(device_id),
            body=json.dumps(success_resp),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    def test_should_run_manual_failover(
        self, service_client
    ):
        # act
        result = commands_device.run_manual_failback(fixture_cmd, app_id, device_id, token="Shared sig")
        # assert
        assert result == success_resp
