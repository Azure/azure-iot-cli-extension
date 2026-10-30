# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, InvalidArgumentValueError
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from azure.mgmt.core.polling.arm_polling import ARMPolling
from knack.util import CLIError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_helpers import endpoint_update_body, failed_link_recovery_commands


ROOT = "/subscriptions/sub/resourceGroups/rg/providers/"
HUB = ROOT + "Microsoft.Devices/IotHubs/hub"
DPS = ROOT + "Microsoft.Devices/provisioningServices/dps"
NS = ROOT + "Microsoft.DeviceRegistry/namespaces/ns"


@pytest.fixture
def batch(fixture_cmd):
    namespace = {
        "id": NS, "location": "centraluseuap",
        "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
        "properties": {"provisioningState": "Succeeded", "messaging": {"endpoints": {}},
                       "provisioning": {"endpoints": {}}},
    }
    dps = {
        "location": "centraluseuap", "identity": {"type": "SystemAssigned", "principalId": "dps-principal"},
        "properties": {"provisioningState": "Succeeded", "iotHubs": [{"name": "hub.azure-devices.net"}]},
    }
    hub = {
        "location": "centraluseuap", "identity": {"type": "SystemAssigned", "principalId": "hub-principal"},
        "sku": {"name": "S1"}, "properties": {"provisioningState": "Succeeded"},
    }
    client = Mock()
    client.namespaces.get.return_value = namespace
    provider = LinkProvider(fixture_cmd, client=client)
    provider._rbac = Mock(created=[])
    provider._get_target = Mock(side_effect=lambda parsed, _: dps if parsed["name"] == "dps" else hub)
    provider._wait = Mock()
    args = {
        "namespace_name": "ns", "resource_group_name": "rg", "hub_endpoint_name": "hub", "hub_resource_id": HUB,
        "dps_endpoint_name": "dps", "dps_resource_id": DPS, "dps_mi_system_assigned": True,
    }
    return provider, namespace, dps, args


def test_brownfield_dps_alone_stops_before_role_assignments(batch):
    provider, _, _, _ = batch
    with pytest.raises(InvalidArgumentValueError, match="hub.azure-devices.net"):
        provider.dps_add("dps", "ns", "rg", DPS, mi_system_assigned=True)
    provider._rbac.ensure.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("extra_hub", [False, True])
def test_brownfield_add_submits_required_hubs_and_dps_once(batch, extra_hub):
    provider, _, dps, args = batch
    if extra_hub:
        dps["properties"]["iotHubs"].append({"hostName": "hub2.azure-devices.net"})
        args["hub_endpoints"] = {"hub2": {
            "resourceId": HUB + "2", "inboundCallerIdentity": {"type": "SystemAssigned"},
            "provisioning": {"availability": "Disabled", "allocationWeight": 3},
        }}
    provider.link_add(**args, no_wait=True)
    provider.client.namespaces.begin_update.assert_called_once()
    arguments = provider.client.namespaces.begin_update.call_args.kwargs
    assert arguments["retry_total"] == 0
    assert isinstance(arguments["polling"], ARMPolling)
    assert arguments["polling"]._operation_config == {}
    body = arguments["properties"]["properties"]
    assert set(body) == {"provisioning", "messaging"}
    assert set(body["messaging"]["endpoints"]) == ({"hub", "hub2"} if extra_hub else {"hub"})
    requests = provider._rbac.ensure_many.call_args.args[0]
    assert set(requests[0]["hub_scopes"]) == {
        value["resourceId"].lower() for value in body["messaging"]["endpoints"].values()
    }
    if extra_hub:
        assert body["messaging"]["endpoints"]["hub2"]["provisioning"]["allocationWeight"] == 3


def test_incomplete_batch_stops_before_all_mutations(batch):
    provider, _, dps, args = batch
    dps["properties"]["iotHubs"].append({"name": "missing.azure-devices.net"})
    with pytest.raises(InvalidArgumentValueError, match="missing.azure-devices.net"):
        provider.link_add(**args)
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"resourceId": 123},
    {"inboundCallerIdentity": {"type": "Invalid"}},
    {"inboundCallerIdentity": {"type": "UserAssigned"}},
    {"inboundCallerIdentity": {"type": "SystemAssigned", "userAssignedIdentity": "unexpected"}},
    {"inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": 123}},
    {"provisioning": {"availability": "Invalid"}},
    {"provisioning": {"availability": None}},
    {"provisioning": {"availability": []}},
    {"provisioning": {"allocationWeight": True}},
    {"provisioning": {"allocationWeight": "3"}},
    {"provisioning": {"allocationWeight": 1.5}},
])
def test_invalid_additional_hub_settings_fail_before_preflight_or_mutation(batch, changes):
    provider, _, _, args = batch
    with pytest.raises(ArgumentUsageError):
        provider.link_add(**args, hub_endpoints={"hub2": {"resourceId": HUB + "2", **changes}})
    provider._get_target.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("hubs", [{"unexpected": "object"}, [{}], [{"name": 123}]])
def test_malformed_dps_hub_inventory_stops_before_role_assignments(batch, hubs):
    provider, _, dps, args = batch
    dps["properties"]["iotHubs"] = hubs
    with pytest.raises(AzureResponseError, match="properties.iotHubs"):
        provider.link_add(**args)
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


def test_batch_preserves_explicit_zero_allocation_weight(batch):
    provider, _, _, args = batch
    provider.link_add(
        **args, hub_endpoints={"hub2": {"resourceId": HUB + "2", "provisioning": {"allocationWeight": 0}}}, no_wait=True,
    )
    body = provider.client.namespaces.begin_update.call_args.kwargs["properties"]
    assert body["properties"]["messaging"]["endpoints"]["hub2"]["provisioning"] == {"allocationWeight": 0}


@pytest.mark.parametrize("hubs,message", [
    ({"": {"resourceId": HUB + "2"}}, "empty or already in use"),
    ({"hub": {"resourceId": HUB + "2"}}, "empty or already in use"),
    ({"duplicate": {"resourceId": HUB.upper()}}, "only once"),
    ({f"hub-{index}": {"resourceId": HUB + str(index)} for index in range(10)}, "10"),
])
def test_invalid_batch_topology_never_reaches_preflight_or_mutation(batch, hubs, message):
    provider, _, _, args = batch
    with pytest.raises(ArgumentUsageError, match=message):
        provider.link_add(**args, hub_endpoints=hubs)
    provider._get_target.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


def failed_pair(namespace):
    for section, name, kind, resource_id in (
        ("provisioning", "dps", DPS_ENDPOINT_TYPE, DPS), ("messaging", "hub", IOT_HUB_ENDPOINT_TYPE, HUB),
    ):
        namespace["properties"][section]["endpoints"][name] = {
            "endpointType": kind, "resourceId": resource_id, "linkingState": "Failed",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }
    namespace["properties"]["messaging"]["endpoints"]["hub"]["provisioning"] = {
        "availability": "Disabled", "allocationWeight": 7,
    }


@pytest.mark.parametrize("state_field", ["linkingState", "provisioningStatus", "status"])
def test_failed_pair_retry_keeps_settings_and_excludes_unselected_endpoints(batch, state_field):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    if state_field != "linkingState":
        for section in ("provisioning", "messaging"):
            for endpoint in namespace["properties"][section]["endpoints"].values():
                endpoint.pop("linkingState")
                endpoint[state_field] = {"status": "Failed"}
    other = deepcopy(namespace["properties"]["messaging"]["endpoints"]["hub"])
    other["resourceId"] += "-other"
    namespace["properties"]["messaging"]["endpoints"]["unrelated"] = other
    original = deepcopy(namespace)
    provider.link_update("ns", "rg", "dps", ["hub"], no_wait=True)
    body = provider.client.namespaces.begin_update.call_args.kwargs["properties"]["properties"]
    assert set(body["messaging"]["endpoints"]) == {"hub"}
    assert body["messaging"]["endpoints"]["hub"] == endpoint_update_body(
        original["properties"]["messaging"]["endpoints"]["hub"],
    )
    assert set(body["provisioning"]["endpoints"]) == {"dps"}
    assert namespace == original
    assert not failed_link_recovery_commands(namespace)


@pytest.mark.parametrize("dps_name,hub_names", [(None, ["hub"]), ("dps", [])])
def test_incomplete_retry_plan_does_not_grant_or_write(batch, dps_name, hub_names):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    with pytest.raises((ArgumentUsageError, InvalidArgumentValueError)):
        provider.link_update("ns", "rg", dps_name, hub_names)
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("selection", [{}, {"dps_endpoint_name": "dps"}, {"hub_endpoint_names": ["hub"]}])
def test_retry_rejects_empty_selection_and_succeeded_endpoints(batch, selection):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    for section in ("provisioning", "messaging"):
        for endpoint in namespace["properties"][section]["endpoints"].values():
            endpoint["linkingState"] = "Succeeded"
    with pytest.raises(ArgumentUsageError, match="Select|not Failed"):
        provider.link_update("ns", "rg", **selection)
    provider._get_target.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("failure,message", [
    ("namespace", "Failed"),
    ("endpoint", "Failed"),
    ("settings", "settings changed"),
])
def test_batch_wait_stops_on_terminal_failure_or_competing_settings(batch, failure, message):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    sections = {
        section: {"endpoints": {name: endpoint_update_body(endpoint) for name, endpoint in group["endpoints"].items()}}
        for section, group in namespace["properties"].items() if isinstance(group, dict)
    }
    for section in sections:
        for endpoint in namespace["properties"][section]["endpoints"].values():
            endpoint["linkingState"] = "Succeeded"
    if failure == "namespace":
        namespace["properties"]["provisioningState"] = "Failed"
    elif failure == "endpoint":
        namespace["properties"]["messaging"]["endpoints"]["hub"]["linkingState"] = "Failed"
    else:
        namespace["properties"]["messaging"]["endpoints"]["hub"]["provisioning"]["allocationWeight"] = 8
    with pytest.raises(AzureResponseError, match=message):
        provider._patch_link_batch("ns", "rg", sections, timeout_sec=2, wait_sec=0.01)
    provider.client.namespaces.begin_update.assert_called_once()
    provider.client.namespaces.get.assert_called_once()


@pytest.mark.parametrize("state", ["Failed", "Succeeded"])
def test_hub_retry_or_identity_update_overlays_only_requested_allocation_settings(batch, state):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] = "Succeeded"
    namespace["properties"]["messaging"]["endpoints"]["hub"]["linkingState"] = state
    provider.hub_update("hub", "ns", "rg", mi_system_assigned=True, allocation_weight=0, no_wait=True)
    body = provider.client.namespaces.begin_update.call_args.kwargs["properties"]
    endpoint = body["properties"]["messaging"]["endpoints"]["hub"]
    assert endpoint["provisioning"] == {"availability": "Disabled", "allocationWeight": 0}
    assert endpoint["inboundCallerIdentity"] == {"type": "SystemAssigned"}
    assert "linkingState" not in endpoint


def test_batch_wait_requires_every_requested_endpoint(batch):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    sections = {
        section: {"endpoints": {name: endpoint_update_body(endpoint) for name, endpoint in group["endpoints"].items()}}
        for section, group in namespace["properties"].items() if isinstance(group, dict)
    }
    pending = deepcopy(namespace)
    for section in sections:
        for endpoint in pending["properties"][section]["endpoints"].values():
            endpoint["linkingState"] = "Succeeded"
    pending["properties"]["messaging"]["endpoints"]["hub"]["linkingState"] = "InProgress"
    final = deepcopy(pending)
    final["properties"]["messaging"]["endpoints"]["hub"]["linkingState"] = "Succeeded"
    provider.client.namespaces.get.side_effect = [pending, final]
    result = provider._patch_link_batch("ns", "rg", sections, timeout_sec=2, wait_sec=0.01)
    assert result == final
    assert provider.client.namespaces.get.call_count == 2


@pytest.mark.parametrize("existing_failed_hub", [False, True])
def test_failed_dps_missing_hub_has_actionable_rebuild_guidance(batch, existing_failed_hub):
    provider, namespace, dps, _ = batch
    failed_pair(namespace)
    if existing_failed_hub:
        dps["properties"]["iotHubs"].append({"name": "missing.azure-devices.net"})
    else:
        namespace["properties"]["messaging"]["endpoints"].clear()
    with pytest.raises(InvalidArgumentValueError) as raised:
        provider.dps_update("dps", "ns", "rg")
    assert "link dps remove" in str(raised.value)
    assert "link hub remove" in str(raised.value)
    assert "saved allocation settings" in str(raised.value)
    assert "--hub-endpoints" in str(raised.value)
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


def test_materialized_failed_pair_guidance_preserves_selected_retry(batch):
    provider, namespace, _, _ = batch
    failed_pair(namespace)
    with pytest.raises(InvalidArgumentValueError) as raised:
        provider.dps_update("dps", "ns", "rg")
    assert "link update" in str(raised.value)
    assert "link dps remove" not in str(raised.value)


def test_existing_dps_add_guidance_handles_missing_hubs(batch):
    provider, namespace, _, args = batch
    failed_pair(namespace)
    with pytest.raises(ArgumentUsageError) as raised:
        provider.link_add(**args)
    assert "link update" in str(raised.value)
    assert "missing" in str(raised.value)
    assert "Failed" in str(raised.value)
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("field", [None, "inboundCallerIdentity", "provisioning"])
def test_additional_hub_nested_file_references_are_rejected(batch, tmp_path, field):
    provider, _, _, args = batch
    contents = {
        None: {"resourceId": HUB + "2"},
        "inboundCallerIdentity": {"type": "SystemAssigned"},
        "provisioning": {"availability": "Available"},
    }
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(contents[field]), encoding="utf-8")
    nested = f"@{path}"
    value = {"resourceId": HUB + "2", field: nested} if field else nested
    with pytest.raises(ArgumentUsageError, match="JSON object"):
        provider.link_add(**args, hub_endpoints={"hub2": value}, no_wait=True)
    provider._get_target.assert_not_called()
    provider._rbac.ensure_many.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


def test_additional_hubs_accept_top_level_json_file(batch, tmp_path):
    provider, _, _, args = batch
    path = tmp_path / "hubs.json"
    path.write_text(json.dumps({"hub2": {"resourceId": HUB + "2"}}), encoding="utf-8")
    provider.link_add(**args, hub_endpoints=f"@{path}", no_wait=True)
    body = provider.client.namespaces.begin_update.call_args.kwargs["properties"]
    assert set(body["properties"]["messaging"]["endpoints"]) == {"hub", "hub2"}


@pytest.mark.parametrize("stage,error", [
    ("submit", ServiceRequestError("response lost")),
    ("submit", ServiceResponseError("response lost")),
    ("wait", CLIError("operation timed out")),
])
def test_batch_unknown_outcome_guidance_preserves_error_and_never_resubmits(batch, caplog, stage, error):
    provider, _, _, args = batch
    if stage == "submit":
        provider.client.namespaces.begin_update.side_effect = error
    else:
        provider._wait.side_effect = error
    with pytest.raises(type(error)) as raised:
        provider.link_add(**args)
    assert raised.value is error
    assert "link wait" in caplog.text
    assert "Failed" in caplog.text
    provider.client.namespaces.begin_update.assert_called_once()
