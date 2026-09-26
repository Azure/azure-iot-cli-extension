# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from shlex import split
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, InvalidArgumentValueError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE, SU_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_helpers import failed_link_recovery_commands


NS_ID = "/subscriptions/ns-sub/resourceGroups/ns-rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
UAMI_ID = "/subscriptions/target-sub/resourceGroups/target-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
LINK_TYPES = [
    ("dps", "provisioning", DPS_ENDPOINT_TYPE),
    ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
    ("su", "updating", SU_ENDPOINT_TYPE),
]


def _namespace(section, endpoint_type, identity):
    return {
        "id": NS_ID,
        "location": "centraluseuap",
        "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
        "properties": {
            "provisioningState": "Failed",
            section: {"endpoints": {"primary": {
                "endpointType": endpoint_type,
                "resourceId": f"/subscriptions/target-sub/resourceGroups/target-rg/providers/{endpoint_type}/target",
                "inboundCallerIdentity": identity,
                "linkingState": "Failed",
                "linkingError": {"code": "AuthorizationFailed", "message": "Managed identity is not authorized"},
            }}},
        },
    }


@pytest.mark.parametrize("kind,section,endpoint_type", LINK_TYPES)
@pytest.mark.parametrize("user_assigned", [False, True])
def test_failed_link_guidance_renders_scoped_update_with_existing_identity(
    fixture_adr_provider, kind, section, endpoint_type, user_assigned,
):
    identity = (
        {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        if user_assigned else {"type": "SystemAssigned"}
    )
    namespace = _namespace(section, endpoint_type, identity)
    original = deepcopy(namespace)
    identity_args = ["--user-assigned-mi", UAMI_ID] if user_assigned else ["--system-assigned-mi"]
    commands = failed_link_recovery_commands(namespace)
    assert len(commands) == 1
    assert split(commands[0]) == [
        "az", "iot", "adr", "ns", "link", kind, "update", "-n", "primary",
        "--ns", "ns", "-g", "ns-rg", "--subscription", "ns-sub", *identity_args,
    ]
    message = fixture_adr_provider._format_failure(
        "Failed", namespace, SimpleNamespace(headers={"x-ms-correlation-request-id": "corr"}),
    )
    assert commands[0] in message
    assert "roles are incomplete" not in message
    assert "exact remediation commands" not in message
    assert "Correlation ID from the resource-status response: corr." in message
    assert namespace == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ns: ns.pop("id"),
        lambda ns: ns.update(id="invalid"),
        lambda ns: ns.update(id="/subscriptions/ns-sub/providers/Microsoft.DeviceRegistry/namespaces/ns"),
        lambda ns: ns.update(id=UAMI_ID),
        lambda ns: ns.update(id=NS_ID + "/groups/child"),
        lambda ns: ns["properties"]["provisioning"].update(endpoints=[]),
        lambda ns: ns["properties"]["provisioning"]["endpoints"].update(primary="invalid"),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(linkingState="Succeeded"),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(inboundCallerIdentity=None),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(inboundCallerIdentity="invalid"),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(
            inboundCallerIdentity={"type": "UserAssigned", "userAssignedIdentity": "invalid"},
        ),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(
            inboundCallerIdentity={"type": "UserAssigned", "userAssignedIdentity": NS_ID},
        ),
        lambda ns: ns["properties"]["provisioning"]["endpoints"]["primary"].update(
            inboundCallerIdentity={"type": "UserAssigned"},
        ),
    ],
)
def test_recovery_does_not_invent_missing_scope_or_identity(mutate):
    namespace = _namespace("provisioning", DPS_ENDPOINT_TYPE, {"type": "SystemAssigned"})
    mutate(namespace)
    assert not failed_link_recovery_commands(namespace)


def test_recovery_quotes_arguments_and_accepts_legacy_failed_state():
    namespace = _namespace("provisioning", DPS_ENDPOINT_TYPE, {"type": "SystemAssigned"})
    endpoint = namespace["properties"]["provisioning"]["endpoints"].pop("primary")
    endpoint.pop("linkingState")
    endpoint["provisioningStatus"] = {"status": "Failed"}
    namespace["properties"]["provisioning"]["endpoints"]["quoted'name"] = endpoint
    assert split(failed_link_recovery_commands(namespace)[0])[8] == "quoted'name"


def test_recovery_commands_follow_dps_first_topology():
    identity = {"type": "SystemAssigned"}
    namespace = _namespace("provisioning", DPS_ENDPOINT_TYPE, identity)
    for _, section, endpoint_type in LINK_TYPES:
        namespace["properties"][section] = _namespace(section, endpoint_type, identity)["properties"][section]
    assert [split(command)[5] for command in failed_link_recovery_commands(namespace)] == ["dps", "hub", "su"]


@pytest.mark.parametrize("kind,section,endpoint_type", LINK_TYPES)
@pytest.mark.parametrize("user_assigned", [False, True])
@pytest.mark.parametrize("repeat_identity", [False, True])
def test_persisted_failed_link_rejects_add_but_update_reruns_real_preflight(
    kind, section, endpoint_type, user_assigned, repeat_identity,
):
    identity = (
        {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        if user_assigned else {"type": "SystemAssigned"}
    )
    namespace = _namespace(section, endpoint_type, identity)
    if kind == "hub":
        namespace["properties"]["provisioning"] = {
            "endpoints": {"dps": {"endpointType": DPS_ENDPOINT_TYPE}},
        }
        namespace["properties"][section]["endpoints"]["primary"]["provisioning"] = {
            "availability": "Available", "allocationWeight": 2,
        }
    target_id = namespace["properties"][section]["endpoints"]["primary"]["resourceId"]
    provider = LinkProvider(Mock(), client=Mock())
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = Mock(return_value={
        "id": target_id,
        "location": "centraluseuap",
        "sku": {"name": "S1"},
        "properties": {"provisioningState": "Succeeded"},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "target-system",
            "userAssignedIdentities": {UAMI_ID: {"principalId": "target-user"}},
        },
    })
    provider._rbac = Mock()
    provider._warn_if_hub_classically_linked = Mock()
    provider._wait = Mock()
    identity_args = {"mi_user_assigned": UAMI_ID} if user_assigned else {"mi_system_assigned": True}

    with pytest.raises(ArgumentUsageError):
        getattr(provider, f"{kind}_add")("primary", "ns", "ns-rg", target_id, **identity_args)
    provider._rbac.ensure.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()

    # Prove public update preflight/submission independently of service readiness.
    update_args = identity_args if repeat_identity else {}
    getattr(provider, f"{kind}_update")("primary", "ns", "ns-rg", no_wait=True, **update_args)
    extra = {"namespace_system_principal_id": "namespace-principal"} if kind == "dps" else {}
    provider._rbac.ensure.assert_called_once_with(
        link_type=kind, namespace_scope=NS_ID, target_scope=target_id,
        namespace_principal_id="namespace-principal",
        linked_principal_id="target-user" if user_assigned else "target-system",
        **extra,
    )
    patch = provider.client.namespaces.begin_update.call_args.kwargs["properties"]
    expected_patch = {
        "endpointType": endpoint_type, "resourceId": target_id, "inboundCallerIdentity": identity,
    }
    if kind == "hub":
        expected_patch["provisioning"] = {"availability": "Available", "allocationWeight": 2}
    assert patch == {"properties": {section: {"endpoints": {"primary": expected_patch}}}}

    provider.client.namespaces.begin_update.reset_mock()
    provider._rbac.ensure.side_effect = AzureResponseError("RBAC preflight failed")
    with pytest.raises(AzureResponseError, match="RBAC preflight failed"):
        getattr(provider, f"{kind}_update")("primary", "ns", "ns-rg", **update_args)
    provider.client.namespaces.begin_update.assert_not_called()
    provider._rbac.ensure.side_effect = None
    provider._get_target.return_value["identity"] = {}
    with pytest.raises(InvalidArgumentValueError, match="not enabled|not attached"):
        getattr(provider, f"{kind}_update")("primary", "ns", "ns-rg", **update_args)
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("state_field", ["linkingState", "provisioningStatus", "status"])
def test_failed_hub_without_inbound_identity_retries_without_inventing_one(state_field):
    namespace = _namespace("messaging", IOT_HUB_ENDPOINT_TYPE, None)
    endpoint = namespace["properties"]["messaging"]["endpoints"]["primary"]
    endpoint.pop("inboundCallerIdentity")
    endpoint.pop("linkingState")
    endpoint[state_field] = "fAiLeD" if state_field == "linkingState" else {"status": "Failed"}
    endpoint["provisioning"] = {"availability": "Unavailable", "allocationWeight": 0}
    namespace["properties"]["provisioning"] = {"endpoints": {"dps": {"endpointType": DPS_ENDPOINT_TYPE}}}
    original = deepcopy(namespace)
    command = split(failed_link_recovery_commands(namespace)[0])
    assert command[-2:] == ["--subscription", "ns-sub"]
    provider = LinkProvider(Mock(), client=Mock())
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = Mock(return_value={
        "location": "centraluseuap", "sku": {"name": "S1"}, "properties": {"provisioningState": "Succeeded"},
    })
    provider._rbac = Mock()
    provider._warn_if_hub_classically_linked = Mock()
    provider._wait = Mock()
    provider.hub_update("primary", "ns", "ns-rg", no_wait=True)
    assert provider._rbac.ensure.call_args.kwargs["linked_principal_id"] is None
    patch = provider.client.namespaces.begin_update.call_args.kwargs["properties"]["properties"]["messaging"]["endpoints"]
    assert patch["primary"] == {
        "endpointType": IOT_HUB_ENDPOINT_TYPE, "resourceId": endpoint["resourceId"],
        "provisioning": endpoint["provisioning"],
    }
    assert namespace == original
    namespace["properties"]["provisioning"]["endpoints"].clear()
    provider.client.namespaces.begin_update.reset_mock()
    with pytest.raises(ArgumentUsageError, match="DPS link is required"):
        provider.hub_update("primary", "ns", "ns-rg", no_wait=True)
    provider.client.namespaces.begin_update.assert_not_called()
