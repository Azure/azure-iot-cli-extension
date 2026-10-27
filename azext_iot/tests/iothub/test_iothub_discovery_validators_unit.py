# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from argparse import Namespace

import pytest
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    ResourceNotFoundError,
)

from azext_iot.iothub._validators import validate_device_model_id
from azext_iot.iothub.models.iothub_target import IotHubTarget
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.common.shared import GatewayVersion

logging.disable(logging.CRITICAL)


class TestValidateDeviceModelId:
    def test_valid_model_id(self):
        ns = Namespace(model_id="dtmi:com:example:TemperatureController;1")
        # Should not raise.
        validate_device_model_id(ns)

    def test_invalid_model_id(self):
        ns = Namespace(model_id="not-a-dtmi")
        with pytest.raises(InvalidArgumentValueError):
            validate_device_model_id(ns)

    def test_no_model_id_attr(self):
        ns = Namespace()
        # No model_id attribute -> noop.
        validate_device_model_id(ns)

    def test_model_id_none(self):
        ns = Namespace(model_id=None)
        validate_device_model_id(ns)


def _disc(mocker):
    disc = IotHubDiscovery.__new__(IotHubDiscovery)
    disc.cmd = mocker.MagicMock()
    disc.sub_id = "sub-123"
    disc.client = None
    disc.resource_type = "IoT Hub"
    return disc


class TestInitializeClient:
    def test_with_cli_ctx(self, mocker):
        disc = _disc(mocker)
        factory = mocker.patch("azext_iot.iothub.providers.discovery.iot_hub_service_factory")
        mocker.patch(
            "azext_iot.iothub.providers.discovery.get_subscription_id", return_value="sub-x"
        )
        disc._initialize_client()
        assert disc.client == factory.return_value.iot_hub_resource
        assert disc.sub_id == "sub-x"

    def test_without_cli_ctx(self, mocker):
        disc = _disc(mocker)
        disc.cmd = mocker.MagicMock(spec=[])
        disc._initialize_client()
        assert disc.client == disc.cmd


class TestMakeKwargs:
    def test_make_kwargs(self, mocker):
        disc = _disc(mocker)
        assert disc._make_kwargs(a=1, b=2) == {"a": 1, "b": 2}


class TestGetTargetByCstring:
    def test_eventhub_cstring(self, mocker):
        mocker.patch(
            "azext_iot.iothub.providers.discovery.is_eventhub_connection_string", return_value=True
        )
        result = IotHubDiscovery.get_target_by_cstring("Endpoint=sb://x;EntityPath=eh")
        assert result["cs"] == "Endpoint=sb://x;EntityPath=eh"
        assert result["entity"] == "eventhub"

    def test_iot_hub_cstring(self, mocker):
        mocker.patch(
            "azext_iot.iothub.providers.discovery.is_eventhub_connection_string", return_value=False
        )
        target = mocker.patch("azext_iot.iothub.providers.discovery.IotHubTarget")
        target.from_connection_string.return_value.as_dict.return_value = {"name": "hub"}
        result = IotHubDiscovery.get_target_by_cstring("HostName=hub.azure-devices.net;...")
        assert result == {"name": "hub"}

    @pytest.mark.parametrize(
        "hostname,entity,service_hostname,device_hostname",
        [
            (
                "hub.device.azure-devices.net",
                "hub.device.azure-devices.net",
                "hub.service.azure-devices.net",
                "hub.device.azure-devices.net",
            ),
            (
                "hub.service.azure-devices.net",
                "hub.service.azure-devices.net",
                "hub.service.azure-devices.net",
                "hub.device.azure-devices.net",
            ),
        ],
    )
    def test_iot_hub_target_hostnames(self, hostname, entity, service_hostname, device_hostname):
        target = IotHubTarget.from_connection_string(
            f"HostName={hostname};SharedAccessKeyName=policy;SharedAccessKey=key"
        ).as_dict()
        assert target["entity"] == entity
        assert target["serviceHostName"] == service_hostname
        assert target["deviceHostName"] == device_hostname

    def test_iot_hub_target_classic_hostname_is_unchanged(self):
        target = IotHubTarget.from_connection_string(
            "HostName=hub.azure-devices.net;SharedAccessKeyName=policy;SharedAccessKey=key"
        ).as_dict()
        assert target["entity"] == "hub.azure-devices.net"
        assert "serviceHostName" not in target
        assert "deviceHostName" not in target


class TestBuildTargetFromHostname:
    def test_build(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target_from_hostname("myhub.azure-devices.net")
        assert result["name"] == "myhub"
        assert result["entity"] == "myhub.azure-devices.net"
        assert result["subscription"] == "sub-123"
        assert "serviceHostName" not in result
        assert "deviceHostName" not in result

    @pytest.mark.parametrize(
        "hostname",
        ["myhub.device.azure-devices.net", "myhub.service.azure-devices.net"],
    )
    def test_build_split_hostname(self, mocker, hostname):
        disc = _disc(mocker)
        result = disc._build_target_from_hostname(hostname)
        assert result["entity"] == hostname
        assert result["serviceHostName"] == "myhub.service.azure-devices.net"
        assert result["deviceHostName"] == "myhub.device.azure-devices.net"


class TestBuildTarget:
    def _resource(self, gw_version=None):
        return {
            "id": (
                "/subscriptions/sub-from-id/resourceGroups/rg/providers/"
                "Microsoft.Devices/IotHubs/myhub"
            ),
            "name": "myhub",
            "location": "westus",
            "sku": {"tier": "Standard"},
            "properties": {
                "hostName": "myhub.azure-devices.net",
                "deviceHostName": "device.host",
                "serviceHostName": "service.host",
                "iotHubDetails": {"gatewayVersion": gw_version} if gw_version else {},
                "eventHubEndpoints": {
                    "events": {
                        "endpoint": "sb://eh-endpoint/",
                        "partitionCount": 2,
                        "path": "events-path",
                        "partitionIds": ["0", "1"],
                    }
                },
            },
        }

    def _policy(self):
        return {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}

    def test_build_primary(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target(self._resource(), self._policy(), key_type="primary")
        assert result["name"] == "myhub"
        assert result["policy"] == "pol"
        assert result["entity"] == "myhub.azure-devices.net"
        assert result["resourcegroup"] == "rg"
        assert result["subscription"] == "sub-from-id"

    def test_build_secondary(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target(self._resource(), self._policy(), key_type="secondary")
        assert result["secondarykey"] == "sk"

    def test_build_gw_v2_service_hostname(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target(
            self._resource(gw_version=GatewayVersion.V2.value), self._policy(), key_type="primary"
        )
        assert result["entity"] == "service.host"

    def test_build_with_events(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target(
            self._resource(), self._policy(), key_type="primary", include_events=True
        )
        assert result["events"]["endpoint"] == "eh-endpoint"
        assert result["events"]["partition_count"] == 2
        assert result["events"]["path"] == "events-path"

    def test_get_target_derives_policy_resource_group_from_arm_id(
        self, mocker
    ):
        disc = _disc(mocker)
        resource = self._resource()
        disc.find_resource = mocker.MagicMock(return_value=resource)
        disc.find_policy = mocker.MagicMock(return_value=self._policy())

        target = disc.get_target(resource_name="myhub")

        disc.find_policy.assert_called_once_with(
            resource_name="myhub",
            rg="rg",
            policy_name="auto",
        )
        assert target["resourcegroup"] == "rg"
        assert target["subscription"] == "sub-from-id"

    @pytest.mark.parametrize(
        "resource_name",
        [
            "https://myhub.azure-devices.net",
            "http://myhub.azure-devices.net",
        ],
    )
    def test_get_target_normalizes_url_and_short_name(
        self, mocker, resource_name
    ):
        disc = _disc(mocker)
        resource = self._resource()
        disc.find_resource = mocker.MagicMock(return_value=resource)
        disc.find_policy = mocker.MagicMock(return_value=self._policy())

        target = disc.get_target(resource_name=resource_name)

        disc.find_resource.assert_called_once_with(
            resource_name="myhub", rg=None
        )
        assert target["name"] == "myhub"

    def test_get_target_forced_aad_lookup_derives_metadata(
        self, mocker
    ):
        disc = _disc(mocker)
        resource = self._resource()
        disc.find_resource = mocker.MagicMock(return_value=resource)

        target = disc.get_target(
            resource_name="myhub.azure-devices.net",
            auth_type="login",
            force_find_resource=True,
        )

        assert target["policy"] == "login"
        assert target["resourcegroup"] == "rg"
        assert target["subscription"] == "sub-from-id"

    def test_get_targets_uses_each_resource_id_without_mutating_resources(
        self, mocker
    ):
        disc = _disc(mocker)
        first = self._resource()
        second = self._resource()
        second["id"] = (
            "/subscriptions/sub-from-id/resourceGroups/other-rg/providers/"
            "Microsoft.Devices/IotHubs/other"
        )
        second["name"] = "other"
        second["properties"]["hostName"] = "other.azure-devices.net"
        disc.get_resources = mocker.MagicMock(return_value=[first, second])
        disc.find_resource = mocker.MagicMock(
            side_effect=[first, second]
        )
        disc.find_policy = mocker.MagicMock(return_value=self._policy())

        targets = disc.get_targets()

        assert [target["resourcegroup"] for target in targets] == [
            "rg",
            "other-rg",
        ]
        assert "resourcegroup" not in first
        assert "resourcegroup" not in second

    def test_get_targets_skips_inaccessible_resource(
        self, mocker
    ):
        disc = _disc(mocker)
        first = self._resource()
        second = self._resource()
        second["id"] = (
            "/subscriptions/sub-from-id/resourceGroups/other-rg/providers/"
            "Microsoft.Devices/IotHubs/other"
        )
        second["name"] = "other"
        disc.get_resources = mocker.MagicMock(return_value=[first, second])
        disc.get_target = mocker.MagicMock(
            side_effect=[
                {"name": "myhub"},
                ResourceNotFoundError("denied"),
            ]
        )

        assert disc.get_targets() == [{"name": "myhub"}]
