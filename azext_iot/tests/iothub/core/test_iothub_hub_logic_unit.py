# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Unit tests for the pure-logic helpers in ``azext_iot.operations.hub``.

These target the connection-string construction and distributed-tracing logic,
which are deterministic and do not require a live IoT Hub. I/O orchestration
(event monitoring, blob SAS generation, etc.) is intentionally left to the
integration suite.
"""

import pytest
from azure.cli.core.azclierror import (
    CLIInternalError,
    ClientRequestError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azext_iot.constants import TRACING_PROPERTY
from azext_iot.operations import hub as subject


# ---------------------------------------------------------------------------
# _build_device_or_module_connection_string
# ---------------------------------------------------------------------------
class TestBuildDeviceOrModuleConnectionString:
    @staticmethod
    def _sas_entity(module=False):
        entity = {
            "deviceId": "d1",
            "hub": "myhub.azure-devices.net",
            "authentication": {
                "type": "sas",
                "symmetricKey": {"primaryKey": "PK", "secondaryKey": "SK"},
            },
        }
        if module:
            entity["moduleId"] = "m1"
        return entity

    def test_device_sas_primary(self):
        cs = subject._build_device_or_module_connection_string(self._sas_entity())
        assert cs == "HostName=myhub.azure-devices.net;DeviceId=d1;SharedAccessKey=PK"

    def test_device_sas_secondary(self):
        cs = subject._build_device_or_module_connection_string(
            self._sas_entity(), key_type="secondary"
        )
        assert cs.endswith("SharedAccessKey=SK")

    def test_module_sas(self):
        cs = subject._build_device_or_module_connection_string(self._sas_entity(module=True))
        assert cs == (
            "HostName=myhub.azure-devices.net;DeviceId=d1;ModuleId=m1;SharedAccessKey=PK"
        )

    def test_hostname_override(self):
        cs = subject._build_device_or_module_connection_string(
            self._sas_entity(), hostname_override="override.host"
        )
        assert cs.startswith("HostName=override.host;")

    @pytest.mark.parametrize("auth_type", ["selfSigned", "certificateAuthority"])
    def test_x509(self, auth_type):
        entity = {
            "deviceId": "d1",
            "hub": "h",
            "authentication": {"type": auth_type},
        }
        cs = subject._build_device_or_module_connection_string(entity)
        assert cs == "HostName=h;DeviceId=d1;x509=true"

    def test_unknown_auth_raises(self):
        entity = {
            "deviceId": "d1",
            "hub": "h",
            "authentication": {"type": "bogus"},
        }
        with pytest.raises(CLIInternalError):
            subject._build_device_or_module_connection_string(entity)


# ---------------------------------------------------------------------------
# _get_hub_connection_string
# ---------------------------------------------------------------------------
class TestGetHubConnectionString:
    @staticmethod
    def _hub():
        return {
            "name": "myhub",
            "resourcegroup": "rg",
            "properties": {
                "hostName": "myhub.azure-devices.net",
                "deviceHostName": "myhub.device.azure-devices.net",
                "serviceHostName": "myhub.service.azure-devices.net",
                "eventHubEndpoints": {
                    "events": {"endpoint": "sb://ehendpoint/", "path": "myhub"}
                },
            },
        }

    @staticmethod
    def _policy(rights="RegistryWrite, ServiceConnect, DeviceConnect"):
        return {
            "keyName": "iothubowner",
            "primaryKey": "PK",
            "secondaryKey": "SK",
            "rights": rights,
        }

    def _discovery(self, mocker, show_all=False):
        discovery = mocker.MagicMock()
        discovery.find_policy.return_value = self._policy()
        discovery.get_policies.return_value = [self._policy()]
        return discovery

    def test_standard_auto_uses_device_hostname(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            False, False, "auto",
        )
        assert result == [
            "HostName=myhub.device.azure-devices.net;"
            "SharedAccessKeyName=iothubowner;SharedAccessKey=PK"
        ]
        discovery.find_policy.assert_called_once()

    def test_standard_classic_uses_hostname(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            False, False, "classic",
        )
        assert result[0].startswith("HostName=myhub.azure-devices.net;")

    def test_standard_device_explicit(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            False, False, "device",
        )
        assert result[0].startswith("HostName=myhub.device.azure-devices.net;")

    def test_secondary_key(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "secondary",
            False, False, "classic",
        )
        assert result[0].endswith("SharedAccessKey=SK")

    def test_missing_service_hostname_raises(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        hub = self._hub()
        hub["properties"]["serviceHostName"] = None
        with pytest.raises(InvalidArgumentValueError):
            subject._get_hub_connection_string(
                fixture_cmd, discovery, hub, "iothubowner", "primary",
                False, False, "service",
            )

    def test_show_all_uses_get_policies(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            True, False, "classic",
        )
        discovery.get_policies.assert_called_once()
        assert len(result) == 1

    def test_default_eventhub_filters_serviceconnect(self, mocker, fixture_cmd):
        discovery = self._discovery(mocker)
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            False, True, "auto",
        )
        assert result == [
            "Endpoint=sb://ehendpoint/;SharedAccessKeyName=iothubowner;"
            "SharedAccessKey=PK;EntityPath=myhub"
        ]

    def test_default_eventhub_excludes_non_serviceconnect(self, mocker, fixture_cmd):
        discovery = mocker.MagicMock()
        discovery.find_policy.return_value = self._policy(rights="RegistryWrite")
        result = subject._get_hub_connection_string(
            fixture_cmd, discovery, self._hub(), "iothubowner", "primary",
            False, True, "auto",
        )
        assert result == []


# ---------------------------------------------------------------------------
# iot_hub_connection_string_show
# ---------------------------------------------------------------------------
class TestIotHubConnectionStringShow:
    @pytest.fixture(autouse=True)
    def _discovery(self, mocker):
        self.disc = mocker.patch.object(subject, "IotHubDiscovery").return_value
        return self.disc

    def test_single_hub(self, mocker, fixture_cmd):
        self.disc.find_resource.return_value = {"name": "h1"}
        mocker.patch.object(subject, "_get_hub_connection_string", return_value=["cs1"])
        result = subject.iot_hub_connection_string_show(fixture_cmd, hub_name_or_hostname="h1")
        assert result == {"connectionString": "cs1"}

    def test_list_all_active_only(self, mocker, fixture_cmd):
        self.disc.get_resources.return_value = [
            {"name": "active", "resourcegroup": "rg", "properties": {"state": "Active"}},
            {"name": "inactive", "resourcegroup": "rg", "properties": {"state": "Suspended"}},
        ]
        mocker.patch.object(subject, "_get_hub_connection_string", return_value=["cs"])
        result = subject.iot_hub_connection_string_show(fixture_cmd)
        assert result == [{"name": "active", "connectionString": "cs"}]

    def test_list_all_missing_policy_warning(self, mocker, fixture_cmd):
        self.disc.get_resources.return_value = [
            {"name": "active", "resourcegroup": "rg", "properties": {"state": "Active"}},
        ]
        mocker.patch.object(
            subject, "_get_hub_connection_string", side_effect=Exception("no policy")
        )
        result = subject.iot_hub_connection_string_show(fixture_cmd)
        assert result == []

    def test_no_hubs_raises(self, fixture_cmd):
        self.disc.get_resources.return_value = None
        with pytest.raises(ResourceNotFoundError):
            subject.iot_hub_connection_string_show(fixture_cmd)


# ---------------------------------------------------------------------------
# _customize_device_tracing_output
# ---------------------------------------------------------------------------
class TestCustomizeDeviceTracingOutput:
    def test_no_desired_tracing_returns_empty(self):
        assert not subject._customize_device_tracing_output("d1", {}, {})

    def test_synced(self):
        desired = {TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 50}}
        reported = {
            TRACING_PROPERTY: {
                "sampling_mode": {"value": 1},
                "sampling_rate": {"value": 50},
            }
        }
        out = subject._customize_device_tracing_output("d1", desired, reported)
        assert out["deviceId"] == "d1"
        assert out["samplingMode"] == "enabled"
        assert out["samplingRate"] == "50%"
        assert out["isSynced"] is True

    def test_not_synced_on_mismatch(self):
        desired = {TRACING_PROPERTY: {"sampling_mode": 2, "sampling_rate": 50}}
        reported = {
            TRACING_PROPERTY: {
                "sampling_mode": {"value": 1},
                "sampling_rate": {"value": 50},
            }
        }
        out = subject._customize_device_tracing_output("d1", desired, reported)
        assert out["samplingMode"] == "disabled"
        assert out["isSynced"] is False


# ---------------------------------------------------------------------------
# _validate_device_tracing
# ---------------------------------------------------------------------------
class TestValidateDeviceTracing:
    @staticmethod
    def _twin(edge=False):
        return {"deviceId": "d1", "capabilities": {"iotEdge": edge}}

    def test_happy_path_resolves_missing_target_fields(self, mocker):
        discovery = mocker.MagicMock()
        discovery.find_resource.return_value = {
            "location": "westus2",
            "sku": {"tier": "Standard"},
        }
        target = {"name": "h1", "location": None, "sku_tier": None}
        # Should not raise.
        subject._validate_device_tracing(discovery, target, self._twin())
        discovery.find_resource.assert_called_once()

    def test_location_not_allowed(self, mocker):
        discovery = mocker.MagicMock()
        target = {"name": "h1", "location": "eastus", "sku_tier": "Standard"}
        with pytest.raises(ClientRequestError, match="location"):
            subject._validate_device_tracing(discovery, target, self._twin())

    def test_sku_not_allowed(self, mocker):
        discovery = mocker.MagicMock()
        target = {"name": "h1", "location": "westus2", "sku_tier": "Free"}
        with pytest.raises(ClientRequestError, match="sku"):
            subject._validate_device_tracing(discovery, target, self._twin())

    def test_edge_device_rejected(self, mocker):
        discovery = mocker.MagicMock()
        target = {"name": "h1", "location": "westus2", "sku_tier": "Standard"}
        with pytest.raises(ClientRequestError, match="non-edge"):
            subject._validate_device_tracing(discovery, target, self._twin(edge=True))


# ---------------------------------------------------------------------------
# iot_hub_distributed_tracing_update
# ---------------------------------------------------------------------------
class TestIotHubDistributedTracingUpdate:
    @pytest.fixture(autouse=True)
    def _discovery(self, mocker):
        self.disc = mocker.patch.object(subject, "IotHubDiscovery").return_value
        self.disc.get_target.return_value = {"name": "h1"}
        return self.disc

    def test_sampling_rate_out_of_range(self, fixture_cmd):
        with pytest.raises(InvalidArgumentValueError):
            subject.iot_hub_distributed_tracing_update(
                fixture_cmd, "h1", "d1", "on", 101
            )

    def test_happy_path_sets_desired_and_returns_output(self, mocker, fixture_cmd):
        twin = {"properties": {"desired": {}}}
        mocker.patch.object(
            subject, "_iot_hub_distributed_tracing_show", return_value=twin
        )
        updated = mocker.MagicMock()
        updated.device_id = "d1"
        updated.properties.desired = {TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 30}}
        updated.properties.reported = {}
        mocker.patch.object(subject, "iot_device_twin_update", return_value=updated)

        result = subject.iot_hub_distributed_tracing_update(
            fixture_cmd, "h1", "d1", "on", 30
        )
        # desired tracing was populated before update
        assert twin["properties"]["desired"][TRACING_PROPERTY]["sampling_rate"] == 30
        assert twin["properties"]["desired"][TRACING_PROPERTY]["sampling_mode"] == 1
        assert result["samplingRate"] == "30%"


# ---------------------------------------------------------------------------
# _iot_hub_distributed_tracing_show / iot_hub_distributed_tracing_show
# ---------------------------------------------------------------------------
class TestIotHubDistributedTracingShow:
    def test_internal_show_validates_then_returns_twin(self, mocker):
        twin = {"deviceId": "d1", "properties": {"desired": {}, "reported": {}}}
        mocker.patch.object(subject, "_iot_device_twin_show", return_value=twin)
        validate = mocker.patch.object(subject, "_validate_device_tracing")
        discovery = mocker.MagicMock()
        result = subject._iot_hub_distributed_tracing_show(
            discovery=discovery, target={"name": "h1"}, device_id="d1"
        )
        assert result is twin
        validate.assert_called_once()

    def test_show_command_returns_customized_output(self, mocker, fixture_cmd):
        mocker.patch.object(subject, "IotHubDiscovery")
        twin = {
            "deviceId": "d1",
            "properties": {
                "desired": {TRACING_PROPERTY: {"sampling_mode": 1, "sampling_rate": 40}},
                "reported": {},
            },
        }
        mocker.patch.object(
            subject, "_iot_hub_distributed_tracing_show", return_value=twin
        )
        result = subject.iot_hub_distributed_tracing_show(fixture_cmd, "h1", "d1")
        assert result["deviceId"] == "d1"
        assert result["samplingRate"] == "40%"
