# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
import asyncio
from copy import deepcopy
import inspect
from unittest.mock import Mock, call

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


@pytest.mark.parametrize(
    "module_name",
    [
        "azext_iot.core.custom",
        "azext_iot.iothub.providers.base",
    ],
)
def test_every_core_and_provider_hub_dps_begin_call_uses_lro_adapter(
    module_name
):
    module = __import__(module_name, fromlist=["unused"])
    tree = ast.parse(inspect.getsource(module))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    begin_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("begin_")
    ]

    assert begin_calls
    assert [
        (node.lineno, node.func.attr)
        for node in begin_calls
        if not (
            isinstance(parents.get(node), ast.Call)
            and isinstance(parents[node].func, ast.Name)
            and parents[node].func.id == "adapt_modeless_lro_poller"
        )
    ] == []


def _configure_dps_policy_create(mocker):
    mocker.patch(
        "azext_iot.core.custom._ensure_dps_resource_group_name",
        return_value="rg",
    )
    mocker.patch(
        "azext_iot.core.custom.iot_dps_policy_list",
        return_value=[],
    )
    mocker.patch(
        "azext_iot.core.custom.iot_dps_get",
        return_value={"properties": {}},
    )
    mocker.patch(
        "azext_iot.core.custom.iot_dps_policy_get",
        return_value={"keyName": "policy"},
    )


def test_no_wait_returns_adapted_generated_poller(mocker):
    from azext_iot.core.custom import iot_dps_policy_create

    _configure_dps_policy_create(mocker)
    client = mocker.MagicMock()
    raw_poller = object()
    adapted_poller = object()
    client.iot_dps_resource.begin_create_or_update.return_value = raw_poller
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        return_value=adapted_poller,
    )
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")

    result = iot_dps_policy_create(
        mocker.MagicMock(),
        client,
        "dps",
        "policy",
        ["ServiceConfig"],
        no_wait=True,
    )

    assert result is adapted_poller
    adapter.assert_called_once_with(raw_poller)
    lro.assert_not_called()


def test_direct_cli_lro_consumes_adapted_generated_poller(mocker):
    from azext_iot.core.custom import iot_dps_policy_create

    _configure_dps_policy_create(mocker)
    client = mocker.MagicMock()
    raw_poller = object()
    adapted_poller = object()
    client.iot_dps_resource.begin_create_or_update.return_value = raw_poller
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        return_value=adapted_poller,
    )
    runner = mocker.MagicMock()
    lro = mocker.patch(
        "azext_iot.core.custom.LongRunningOperation",
        return_value=runner,
    )

    result = iot_dps_policy_create(
        mocker.MagicMock(),
        client,
        "dps",
        "policy",
        ["ServiceConfig"],
    )

    assert result == {"keyName": "policy"}
    adapter.assert_called_once_with(raw_poller)
    lro.assert_called_once()
    runner.assert_called_once_with(adapted_poller)


def test_dps_resource_begin_calls_are_adapted_at_runtime(mocker):
    from azext_iot.core.custom import (
        iot_dps_create,
        iot_dps_delete,
        iot_dps_update,
    )

    mocker.patch("azext_iot.core.custom._check_dps_name_availability")
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="eastus",
    )
    mocker.patch(
        "azext_iot.core.custom._ensure_dps_resource_group_name",
        return_value="rg",
    )
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        side_effect=lambda poller: poller,
    )
    client = mocker.MagicMock()
    create_poller = object()
    update_poller = object()
    delete_poller = object()
    client.iot_dps_resource.begin_create_or_update.side_effect = [
        create_poller,
        update_poller,
    ]
    client.iot_dps_resource.begin_delete.return_value = delete_poller
    client.iot_dps_resource.get.return_value = {"identity": None}

    assert iot_dps_create(
        mocker.MagicMock(),
        client,
        "dps",
        "rg",
    ) is create_poller
    assert iot_dps_update(
        client,
        "dps",
        {"location": "eastus", "properties": {}},
        "rg",
    ) is update_poller
    assert iot_dps_delete(client, "dps", "rg") is delete_poller

    assert adapter.call_args_list == [
        call(create_poller),
        call(update_poller),
        call(delete_poller),
    ]


def test_dps_policy_no_wait_paths_return_adapted_pollers(mocker):
    from azext_iot.core.custom import (
        iot_dps_policy_delete,
        iot_dps_policy_update,
    )

    mocker.patch(
        "azext_iot.core.custom._ensure_dps_resource_group_name",
        return_value="rg",
    )
    policy = {
        "keyName": "policy",
        "rights": "ServiceConfig",
        "primaryKey": "primary",
        "secondaryKey": "secondary",
    }
    mocker.patch(
        "azext_iot.core.custom.iot_dps_policy_list",
        return_value=[policy],
    )
    mocker.patch(
        "azext_iot.core.custom.iot_dps_get",
        return_value={"properties": {}},
    )
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        side_effect=lambda poller: poller,
    )
    client = mocker.MagicMock()
    update_poller = object()
    delete_poller = object()
    client.iot_dps_resource.begin_create_or_update.side_effect = [
        update_poller,
        delete_poller,
    ]

    assert iot_dps_policy_update(
        mocker.MagicMock(),
        client,
        "dps",
        "policy",
        no_wait=True,
    ) is update_poller
    assert iot_dps_policy_delete(
        mocker.MagicMock(),
        client,
        "dps",
        "policy",
        no_wait=True,
    ) is delete_poller

    assert adapter.call_args_list == [
        call(update_poller),
        call(delete_poller),
    ]


def test_dps_linked_hub_no_wait_paths_return_adapted_pollers(mocker):
    from azext_iot.core.custom import (
        iot_dps_linked_hub_create,
        iot_dps_linked_hub_delete,
        iot_dps_linked_hub_update,
    )

    mocker.patch(
        "azext_iot.core.custom._ensure_dps_resource_group_name",
        return_value="rg",
    )
    dps = {"properties": {"iotHubs": []}}
    mocker.patch("azext_iot.core.custom.iot_dps_get", return_value=dps)
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        side_effect=lambda poller: poller,
    )
    client = mocker.MagicMock()
    create_poller = object()
    update_poller = object()
    delete_poller = object()
    client.iot_dps_resource.begin_create_or_update.side_effect = [
        create_poller,
        update_poller,
        delete_poller,
    ]
    linked_hub = "hub.azure-devices.net"

    assert iot_dps_linked_hub_create(
        mocker.MagicMock(),
        client,
        "dps",
        connection_string=(
            f"HostName={linked_hub};"
            "SharedAccessKeyName=owner;SharedAccessKey=key"
        ),
        location="eastus",
        no_wait=True,
    ) is create_poller
    dps["properties"]["iotHubs"][0]["name"] = linked_hub
    dps["properties"]["iotHubs"][0]["authenticationType"] = "KeyBased"
    assert iot_dps_linked_hub_update(
        mocker.MagicMock(),
        client,
        "dps",
        linked_hub=linked_hub,
        allocation_weight=2,
        no_wait=True,
    ) is update_poller
    assert iot_dps_linked_hub_delete(
        mocker.MagicMock(),
        client,
        "dps",
        linked_hub,
        no_wait=True,
    ) is delete_poller

    assert adapter.call_args_list == [
        call(create_poller),
        call(update_poller),
        call(delete_poller),
    ]


def test_hub_delete_and_failover_no_wait_return_adapted_pollers(mocker):
    from azext_iot.core.custom import (
        iot_hub_delete,
        iot_hub_manual_failover,
    )

    mocker.patch(
        "azext_iot.core.custom._ensure_hub_resource_group_name",
        return_value="rg",
    )
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get",
        return_value={
            "id": RESOURCE_ID,
            "properties": {
                "locations": [
                    {"location": "eastus", "role": "primary"},
                    {"location": "westus", "role": "secondary"},
                ]
            },
        },
    )
    adapter = mocker.patch(
        "azext_iot.core.custom.adapt_modeless_lro_poller",
        side_effect=lambda poller: poller,
    )
    client = mocker.MagicMock()
    delete_poller = object()
    failover_poller = object()
    client.iot_hub_resource.begin_delete.return_value = delete_poller
    client.iot_hub.begin_manual_failover.return_value = failover_poller

    assert iot_hub_delete(client, "hub", "rg") is delete_poller
    assert iot_hub_manual_failover(
        mocker.MagicMock(),
        client,
        "hub",
        "rg",
        no_wait=True,
    ) is failover_poller

    assert adapter.call_args_list == [
        call(delete_poller),
        call(failover_poller),
    ]


def test_dps_resource_group_falls_back_to_modeless_resource_id(mocker):
    from azext_iot.core.custom import _ensure_dps_resource_group_name

    mocker.patch(
        "azext_iot.core.custom._get_iot_dps_by_name",
        return_value={
            "id": (
                "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.Devices/provisioningServices/dps"
            )
        },
    )

    assert _ensure_dps_resource_group_name(
        mocker.MagicMock(),
        None,
        "dps",
    ) == "rg"


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
