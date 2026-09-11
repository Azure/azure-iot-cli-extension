# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.core import custom


@pytest.fixture(autouse=True)
def block_core_test_network(mocker, mocked_response):
    mocker.patch("socket.socket.connect", side_effect=AssertionError("Unit tests must not use the network"))
    mocker.patch("socket.socket.connect_ex", side_effect=AssertionError("Unit tests must not use the network"))


@pytest.fixture
def preview_mgmt(mocker):
    cmd, client = mocker.Mock(), mocker.Mock()
    hub = {
        "name": "hub", "resourcegroup": "rg", "location": "westus", "etag": "hub-etag",
        "sku": {"name": "S1", "capacity": 1, "tier": "Standard"},
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "hostName": "hub.azure-devices.net",
            "eventHubEndpoints": {"events": {"retentionTimeInDays": 1}},
            "cloudToDevice": {"feedback": {}},
            "messagingEndpoints": {"fileNotifications": {}},
            "storageEndpoints": {"$default": {"connectionString": "old", "containerName": "old"}},
            "locations": [{"role": "Primary", "location": "westus"}, {"role": "Secondary", "location": "eastus"}],
            "routing": {
                "endpoints": {key: [] for key in (
                    "eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"
                )},
                "routes": [],
            },
        },
    }
    dps = {
        "name": "dps", "resourcegroup": "rg", "location": "westus",
        "identity": {"type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {"/identities/user": {}}},
        "properties": {"iotHubs": []},
    }
    client.iot_hub_resource.get.return_value = hub
    client.iot_hub_resource.list_by_subscription.return_value = [hub]
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": False}
    client.iot_dps_resource.get.return_value = dps
    client.iot_dps_resource.list_by_subscription.return_value = [dps]
    client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {"nameAvailable": True}
    resource_factory = mocker.patch.object(custom, "resource_service_factory")
    resource_factory.return_value.resource_groups.check_existence.return_value = True
    resource_factory.return_value.resource_groups.get.return_value.location = "westus"
    mocker.patch.object(custom, "iot_hub_service_factory", return_value=client)
    wait = mocker.patch.object(custom, "LongRunningOperation").return_value
    return cmd, client, hub, dps, wait
