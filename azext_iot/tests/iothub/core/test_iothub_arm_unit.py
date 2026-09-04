# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy

import pytest
from azure.cli.core.azclierror import CLIInternalError
from azure.core import MatchConditions

from azext_iot.common.arm import (
    get_resource_group,
    get_subscription_id,
    hub_description_for_write,
    hub_etag_arguments,
    sanitize_arm_identity,
)
from azext_iot.iothub.providers.base import IoTHubProvider


RESOURCE_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)


def test_arm_metadata_uses_caller_context_or_resource_id():
    resource = {
        "id": RESOURCE_ID,
        # Legacy SDK projections must not be consulted.
        "resourcegroup": "wrong-rg",
        "subscriptionid": "wrong-sub",
    }
    assert get_resource_group(resource) == "rg"
    assert get_subscription_id(resource) == "sub"
    assert get_resource_group(resource, fallback="caller-rg") == "caller-rg"
    assert get_subscription_id({}, fallback="caller-sub") == "caller-sub"


@pytest.mark.parametrize("resolver", [get_resource_group, get_subscription_id])
def test_arm_metadata_requires_id_or_caller_context(resolver):
    with pytest.raises(CLIInternalError, match="usable resource ID"):
        resolver({}, resource_label="IoT Hub")


def test_hub_write_sanitizer_is_non_mutating_and_removes_all_projections():
    hub = {
        "id": RESOURCE_ID,
        "name": "hub",
        "type": "Microsoft.Devices/IotHubs",
        "systemData": {"createdBy": "caller"},
        "etag": "etag",
        "location": "centraluseuap",
        "tags": {"env": "test"},
        "sku": {"name": "S1", "tier": "Standard", "capacity": 1},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "system-principal",
            "tenantId": "tenant",
            "userAssignedIdentities": {
                "/identities/one": {
                    "principalId": "user-principal",
                    "clientId": "client",
                }
            },
        },
        "properties": {
            "deviceRegistry": {"namespaceResourceId": "/namespaces/ns"},
            "provisioningState": "Succeeded",
            "state": "Active",
            "hostName": "hub.azure-devices.net",
            "deviceHostName": "hub.device.azure-devices.net",
            "serviceHostName": "hub.service.azure-devices.net",
            "locations": [{"location": "centraluseuap"}],
            "iotHubDetails": {"gatewayVersion": "V2"},
            "privateEndpointConnections": [{"id": "/private/one"}],
            "eventHubEndpoints": {
                "events": {
                    "retentionTimeInDays": 1,
                    "partitionCount": 4,
                    "partitionIds": ["0", "1", "2", "3"],
                    "path": "hub",
                    "endpoint": "sb://service-owned/",
                }
            },
            "routing": {"routes": [{"name": "route"}]},
        },
    }
    original = deepcopy(hub)

    body = hub_description_for_write(hub)

    assert hub == original
    assert set(body) == {"location", "tags", "sku", "identity", "properties"}
    assert body["sku"] == {"name": "S1", "capacity": 1}
    assert body["identity"] == {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {"/identities/one": {}},
    }
    assert body["properties"]["eventHubEndpoints"]["events"] == {
        "retentionTimeInDays": 1,
        "partitionCount": 4,
    }
    assert body["properties"]["routing"] == {"routes": [{"name": "route"}]}
    assert {
        "deviceRegistry",
        "provisioningState",
        "state",
        "hostName",
        "deviceHostName",
        "serviceHostName",
        "locations",
        "iotHubDetails",
        "privateEndpointConnections",
    }.isdisjoint(body["properties"])


def test_identity_and_etag_helpers_cover_empty_values():
    assert sanitize_arm_identity(None) is None
    assert sanitize_arm_identity({"type": "None"}) == {"type": "None"}
    assert not hub_etag_arguments({})
    assert hub_etag_arguments({"etag": "etag"}) == {
        "etag": "etag",
        "match_condition": MatchConditions.IfNotModified,
    }


def test_dataplane_provider_uses_discovery_context_and_resolver(mocker):
    discovery_type = mocker.patch(
        "azext_iot.iothub.providers.base.IotHubDiscovery"
    )
    discovery = discovery_type.return_value
    discovery.get_target.return_value = {"entity": "hub.azure-devices.net"}
    discovery.last_resource_group = "rg-from-id"
    resolver_type = mocker.patch(
        "azext_iot.iothub.providers.base.SdkResolver"
    )

    provider = IoTHubProvider(
        cmd=mocker.MagicMock(),
        hub_name="hub",
        rg=None,
    )

    assert provider.rg == "rg-from-id"
    assert provider.target == {"entity": "hub.azure-devices.net"}
    assert provider.get_sdk("service") is (
        resolver_type.return_value.get_sdk.return_value
    )


def test_control_plane_provider_derives_arm_metadata(mocker):
    discovery_type = mocker.patch(
        "azext_iot.iothub.providers.base.IotHubDiscovery"
    )
    discovery = discovery_type.return_value
    discovery.sub_id = "fallback-sub"
    discovery.find_resource.return_value = {
        "id": RESOURCE_ID,
        "name": "hub",
        "etag": "etag",
        "properties": {},
    }

    provider = IoTHubProvider(
        cmd=mocker.MagicMock(),
        hub_name="hub",
        rg=None,
        dataplane=False,
    )

    assert provider.rg == "rg"
    assert provider.subscription_id == "sub"
    provider._begin_hub_update()
    kwargs = discovery.client.begin_create_or_update.call_args.kwargs
    assert kwargs["resource_group_name"] == "rg"
    assert kwargs["match_condition"] == MatchConditions.IfNotModified
