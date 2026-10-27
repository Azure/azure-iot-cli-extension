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
    hub_description_for_write,
    hub_etag_arguments,
    sanitize_arm_identity,
)


RESOURCE_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)


@pytest.mark.parametrize(
    "resource",
    [
        {"id": RESOURCE_ID},
        {"id": RESOURCE_ID, "resourcegroup": "stale-rg"},
        {"resourcegroup": "rg"},
    ],
)
def test_hub_resource_group_supports_modeless_and_legacy_resources(resource):
    from azext_iot.core.custom import _get_resource_group_from_hub

    original = deepcopy(resource)
    assert _get_resource_group_from_hub(resource) == "rg"
    assert resource == original


@pytest.mark.parametrize("resource", [None, {}, {"id": 42}, {"id": "invalid"}])
def test_hub_resource_group_reports_missing_resource_context(resource):
    from azext_iot.core.custom import _get_resource_group_from_hub

    with pytest.raises(CLIInternalError, match="IoT Hub response did not include a usable resource ID"):
        _get_resource_group_from_hub(resource)


@pytest.mark.parametrize("resource", [None, {"id": RESOURCE_ID}, {"resourcegroup": "legacy-rg"}])
def test_explicit_resource_group_takes_precedence_without_mutating_resource(resource):
    original = deepcopy(resource)
    assert get_resource_group(resource, fallback="explicit-rg") == "explicit-rg"
    assert resource == original


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
                "disabled": None,
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
    assert body["properties"]["eventHubEndpoints"]["disabled"] is None
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
