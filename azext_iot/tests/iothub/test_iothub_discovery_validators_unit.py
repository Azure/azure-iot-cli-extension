# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from argparse import Namespace

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot.iothub._validators import validate_device_model_id
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


class TestBuildTargetFromHostname:
    def test_build(self, mocker):
        disc = _disc(mocker)
        result = disc._build_target_from_hostname("myhub.azure-devices.net")
        assert result["name"] == "myhub"
        assert result["entity"] == "myhub.azure-devices.net"
        assert result["subscription"] == "sub-123"


class TestBuildTarget:
    def _resource(self, gw_version=None):
        return {
            "name": "myhub",
            "resourcegroup": "rg",
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
