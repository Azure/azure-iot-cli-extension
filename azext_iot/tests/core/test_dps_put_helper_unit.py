# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from types import SimpleNamespace

import pytest

from azext_iot.core import custom
from azext_iot.core.shared import IotHubAuthenticationType


def _client(mocker, dps):
    client = mocker.Mock()
    client.iot_dps_resource.get.return_value = dps
    client.iot_dps_resource.begin_create_or_update.return_value = mocker.sentinel.poller
    client.iot_dps_resource.list_keys.return_value = deepcopy(
        dps["properties"].get("authorizationPolicies", [])
    )
    client.iot_dps_resource.list_keys_for_key_name.return_value = {"keyName": "policy"}
    return client


@pytest.fixture
def lro(mocker):
    runner = mocker.Mock()
    mocker.patch.object(custom, "LongRunningOperation", return_value=runner)
    return runner


@pytest.fixture
def cmd(mocker):
    return SimpleNamespace(cli_ctx=mocker.sentinel.cli_ctx)


def _assert_put(client, dps):
    client.iot_dps_resource.begin_create_or_update.assert_called_once()
    assert client.iot_dps_resource.begin_create_or_update.call_args.kwargs == {
        "resource_group_name": "rg",
        "provisioning_service_name": "dps",
        "iot_dps_description": custom._dps_description_for_write(dps),  # pylint: disable=protected-access
    }


def test_dps_policy_create_uses_shared_put_for_wait(cmd, mocker, lro):
    dps = {"location": "eastus", "sku": {"capacity": 1}, "properties": {"authorizationPolicies": []}}
    client = _client(mocker, dps)

    assert custom.iot_dps_policy_create(cmd, client, "dps", "policy", ["ServiceConfig"], "rg") == {"keyName": "policy"}

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)


def test_dps_policy_update_uses_shared_put_for_wait(cmd, mocker, lro):
    policy = {"keyName": "policy", "rights": "ServiceConfig"}
    dps = {"location": "eastus", "sku": {"capacity": 1}, "properties": {"authorizationPolicies": [policy]}}
    client = _client(mocker, dps)

    assert custom.iot_dps_policy_update(cmd, client, "dps", "policy", "rg", rights=["EnrollmentRead"]) == {
        "keyName": "policy"
    }

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)


def test_dps_policy_delete_uses_shared_put_for_wait(cmd, mocker, lro):
    dps = {
        "location": "eastus",
        "sku": {"capacity": 1},
        "properties": {"authorizationPolicies": [{"keyName": "policy", "rights": "ServiceConfig"}]},
    }
    client = _client(mocker, dps)

    assert custom.iot_dps_policy_delete(cmd, client, "dps", "policy", "rg") == [
        {"keyName": "policy", "rights": "ServiceConfig"}
    ]

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)


def test_dps_linked_hub_create_uses_shared_put_for_wait(cmd, mocker, lro):
    dps = {"location": "eastus", "sku": {"capacity": 1}, "properties": {"iotHubs": []}}
    client = _client(mocker, dps)
    mocker.patch.object(custom, "iot_hub_service_factory")
    mocker.patch.object(custom, "iot_hub_get", return_value={"properties": {}})

    assert custom.iot_dps_linked_hub_create(
        cmd,
        client,
        "dps",
        connection_string="HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=key",
        location="eastus",
        resource_group_name="rg",
    ) == dps["properties"]["iotHubs"]

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)


def test_dps_linked_hub_update_uses_shared_put_for_wait(cmd, mocker, lro):
    entry = {
        "name": "hub.azure-devices.net",
        "hostName": "hub.azure-devices.net",
        "authenticationType": IotHubAuthenticationType.KEY_BASED.value,
        "connectionString": "HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=key",
    }
    dps = {"location": "eastus", "sku": {"capacity": 1}, "properties": {"iotHubs": [entry]}}
    client = _client(mocker, dps)

    assert custom.iot_dps_linked_hub_update(
        cmd, client, "dps", linked_hub="hub.azure-devices.net", resource_group_name="rg", allocation_weight=2
    ) is entry

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)


def test_dps_linked_hub_delete_uses_shared_put_for_wait(cmd, mocker, lro):
    dps = {
        "location": "eastus",
        "sku": {"capacity": 1},
        "properties": {"iotHubs": [{"name": "hub.azure-devices.net", "hostName": "hub.azure-devices.net"}]},
    }
    client = _client(mocker, dps)

    assert custom.iot_dps_linked_hub_delete(cmd, client, "dps", "hub.azure-devices.net", "rg") == []

    lro.assert_called_once_with(mocker.sentinel.poller)
    _assert_put(client, dps)
