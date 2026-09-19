# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Focused contracts for assigned entire-PR runtime coverage gaps."""

from copy import deepcopy
from shlex import split
from unittest.mock import Mock, NonCallableMock, call

import pytest

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider, _HUB_TARGET
from azext_iot.adr.providers.link_helpers import (
    failed_link_recovery_commands,
    parse_hub_resource_id,
    sanitize_identity,
)
from azext_iot.adr.providers.link_preflight import preflight_target
from azext_iot.tests.adr import test_adr_link_runtime_preflight_unit as preflight_tests


@pytest.mark.parametrize("identity,expected", [
    (None, None),
    ({}, None),
    (
        {"type": "SystemAssigned", "principalId": "server-principal", "tenantId": "server-tenant"},
        {"type": "SystemAssigned"},
    ),
    (
        {"type": "SystemAssigned", "userAssignedIdentities": None},
        {"type": "SystemAssigned"},
    ),
    ({"type": "UserAssigned", "userAssignedIdentities": {}}, {"type": "UserAssigned", "userAssignedIdentities": {}}),
    (
        {"type": "SystemAssigned,UserAssigned", "principalId": "server-principal",
         "userAssignedIdentities": {preflight_tests.UAMI: {"principalId": "user-principal", "clientId": "client"}}},
        {"type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {preflight_tests.UAMI: {}}},
    ),
])
def test_identity_sanitizer_keeps_only_writable_fields_without_mutating_input(identity, expected):
    original = deepcopy(identity)
    assert sanitize_identity(identity) == expected
    assert identity == original


@pytest.mark.parametrize("endpoints", [["not-an-endpoint-map"], "not-an-endpoint-map"])
def test_recovery_guidance_ignores_truthy_non_mapping_sections(endpoints):
    namespace = preflight_tests._namespace()
    namespace["properties"] = {
        "messaging": {"endpoints": endpoints},
        "provisioning": {"endpoints": {"dps": {
            "endpointType": DPS_ENDPOINT_TYPE, "linkingState": "Failed",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}},
    }
    commands = failed_link_recovery_commands(namespace)
    assert len(commands) == 1
    assert split(commands[0]) == [
        "az", "iot", "adr", "ns", "link", "dps", "update", "-n", "dps",
        "--ns", "ns", "-g", "ns-rg", "--subscription", "ns-sub", "--system-assigned-mi",
    ]


@pytest.mark.parametrize("outbound_identity", [None, {"type": "SystemAssigned"}])
def test_namespace_outbound_preflight_preserves_sami_and_ignores_unrelated_endpoint_types(
    fixture_namespace_provider, mocker, outbound_identity,
):
    namespace = preflight_tests._namespace()
    namespace["properties"]["messaging"] = {"endpoints": {
        "unrelated": {"endpointType": "Microsoft.Example/other", "resourceId": "/not-a-hub"},
        "hub": {"endpointType": IOT_HUB_ENDPOINT_TYPE, "resourceId": preflight_tests.HUB_ID},
    }}
    original = deepcopy(namespace)
    provider = mocker.patch("azext_iot.adr.providers.link.LinkProvider").return_value
    provider._preflight_link.side_effect = lambda **kwargs: kwargs["rbac_requests"].append({"link_type": kwargs["link_type"]})

    fixture_namespace_provider._preflight_outbound_identity_change(namespace, outbound_identity)

    provider._preflight_link.assert_called_once()
    options = provider._preflight_link.call_args.kwargs
    assert options["target_resource_id"] == preflight_tests.HUB_ID
    assert options["namespace"]["identity"] == original["identity"]
    assert options["namespace"]["properties"]["outboundIdentity"] == outbound_identity
    provider._rbac_manager.return_value.ensure_many.assert_called_once_with([{"link_type": "hub"}])
    assert namespace == original


def test_namespace_clear_outbound_and_observability_update_share_one_get(fixture_namespace_provider, mocker):
    endpoint = {
        "endpointType": "Microsoft.EventGrid/namespaces", "address": "eventgrid.example", "scopeId": "scope",
        "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventGrid/namespaces/eg",
    }
    namespace = preflight_tests._namespace()
    namespace["properties"]["observability"] = {"enabled": False, "endpoints": {"events": endpoint}}
    original = deepcopy(namespace)
    fixture_namespace_provider.client.namespaces.get.return_value = namespace
    mocker.patch.object(fixture_namespace_provider, "_wait", return_value={"name": "ns"})

    fixture_namespace_provider.update("ns", "ns-rg", outbound_mi_system_assigned=False, observability_enabled=True)

    fixture_namespace_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="ns-rg", namespace_name="ns",
    )
    assert fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs["properties"] == {
        "properties": {"outboundIdentity": None, "observability": {"enabled": True, "endpoints": {"events": endpoint}}},
    }
    assert namespace == original


@pytest.mark.parametrize("manager_factory", [False, True])
def test_preflight_immediately_ensures_rbac_when_no_request_queue_is_supplied(manager_factory):
    namespace, target = preflight_tests._namespace(), preflight_tests._hub()
    manager = NonCallableMock(ensure=Mock())
    factory = Mock(return_value=manager)
    lookup = Mock(return_value=target)
    parsed = parse_hub_resource_id(preflight_tests.HUB_ID)

    assert preflight_target(
        link_type="hub", namespace=namespace, target_resource_id=preflight_tests.HUB_ID,
        inbound_identity={"type": "SystemAssigned"}, parsed=parsed, strategy=_HUB_TARGET,
        lookup=lookup, rbac_manager=factory if manager_factory else manager,
    ) is target

    lookup.assert_called_once_with(parsed, _HUB_TARGET)
    manager.ensure.assert_called_once_with(
        link_type="hub", namespace_scope=preflight_tests.NS_ID, target_scope=preflight_tests.HUB_ID,
        namespace_principal_id="namespace-principal", linked_principal_id="hub-system",
    )
    assert factory.call_count == int(manager_factory)


@pytest.mark.parametrize("first_hubs", [[], [{"name": "other.azure-devices.net"}]])
def test_classic_hub_warning_continues_after_empty_or_nonmatching_dps(fixture_link_provider, mocker, caplog, first_hubs):
    namespace = preflight_tests._namespace()
    ids = [
        f"/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/{name}"
        for name in ("first", "second")
    ]
    namespace["properties"]["provisioning"] = {"endpoints": {
        str(index): {"endpointType": DPS_ENDPOINT_TYPE, "resourceId": resource_id}
        for index, resource_id in enumerate(ids)
    }}
    side_get = mocker.patch.object(fixture_link_provider, "_side_get_dps_resource", side_effect=[
        {"properties": {"iotHubs": first_hubs}},
        {"properties": {"iotHubs": [{"name": "hub.azure-devices.net"}]}},
    ])

    LinkProvider._warn_if_hub_classically_linked(fixture_link_provider, namespace, {"name": "hub"}, preflight_tests._hub())

    assert side_get.call_args_list == [call(resource_id) for resource_id in ids]
    assert caplog.text.count("also configured") == 1


@pytest.mark.parametrize("argument,value,property_name", [
    ("display_name", "New name", "displayName"),
    ("description", "", "description"),
])
def test_group_property_update_leaves_unspecified_tags_untouched(fixture_group_provider, argument, value, property_name):
    result = {"name": "group", "properties": {property_name: value}}
    fixture_group_provider.client.groups.update.return_value = result
    assert fixture_group_provider.update("group", "ns", "rg", **{argument: value}) == result
    fixture_group_provider.client.groups.update.assert_called_once_with(
        resource_group_name="rg", namespace_name="ns", group_name="group", properties={"properties": {property_name: value}},
    )
