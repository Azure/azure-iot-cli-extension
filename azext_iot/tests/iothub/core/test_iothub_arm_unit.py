# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
from copy import deepcopy
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import CLIInternalError
from azure.core import MatchConditions
from azure.core.polling import (
    AsyncLROPoller,
    AsyncNoPolling,
    LROPoller,
    NoPolling,
)
from msrestazure.azure_operation import AzureOperationPoller

from azext_iot.common.arm import (
    adapt_modeless_lro_poller,
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


@pytest.mark.parametrize(
    "content, expected",
    [
        (b'{"properties":{"state":"Active"}}', {"properties": {"state": "Active"}}),
        (b"", None),
    ],
)
def test_modeless_lro_adapter_deserializes_sync_json_and_empty_response(
    content, expected
):
    response = Mock(content=content)
    response.json.return_value = expected
    pipeline_response = Mock(http_response=response)
    broken_callback = Mock(side_effect=NameError("undefined response"))
    poller = LROPoller(
        None,
        pipeline_response,
        broken_callback,
        NoPolling(),
    )
    poller.polling_method().get_continuation_token = Mock(
        return_value="continuation"
    )

    adapted = adapt_modeless_lro_poller(poller)

    assert adapted is poller
    assert adapted.status() == "succeeded"
    assert adapted.done()
    adapted.wait()
    assert adapted.result() == expected
    assert adapted.continuation_token() == "continuation"
    done_callback = Mock()
    adapted.add_done_callback(done_callback)
    done_callback.assert_called_once_with(adapted.polling_method())
    broken_callback.assert_not_called()
    if content:
        response.json.assert_called_once_with()
    else:
        response.json.assert_not_called()


@pytest.mark.parametrize(
    "content, expected",
    [
        (b'{"properties":{"state":"Active"}}', {"properties": {"state": "Active"}}),
        (b"", None),
    ],
)
def test_modeless_lro_adapter_deserializes_async_json_and_empty_response(
    content, expected
):
    response = Mock(content=content)
    response.json.return_value = expected
    pipeline_response = Mock(http_response=response)
    broken_callback = Mock(side_effect=NameError("undefined response"))
    poller = AsyncLROPoller(
        None,
        pipeline_response,
        broken_callback,
        AsyncNoPolling(),
    )
    poller.polling_method().get_continuation_token = Mock(
        return_value="continuation"
    )

    adapted = adapt_modeless_lro_poller(poller)

    async def consume():
        await adapted.wait()
        return await adapted.result()

    assert adapted is poller
    assert adapted.status() == "succeeded"
    assert not adapted.done()
    assert asyncio.run(consume()) == expected
    assert adapted.done()
    assert adapted.continuation_token() == "continuation"
    broken_callback.assert_not_called()
    if content:
        response.json.assert_called_once_with()
    else:
        response.json.assert_not_called()


def test_modeless_lro_adapter_does_not_touch_legacy_poller():
    legacy_poller = Mock(spec=AzureOperationPoller)

    assert adapt_modeless_lro_poller(legacy_poller) is legacy_poller


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
