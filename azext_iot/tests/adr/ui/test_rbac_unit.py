# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""UI plans execute the real base RBAC manager, never an alternative grant policy."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.rbac import LINK_ROLE_MATRIX, LinkRbacManager
from azext_iot.adr.ui.core import rbac
from azext_iot.adr.ui.core.session import Session, SessionError
from azext_iot.adr.ui.screens.onboard.identity import IdentityChoice, USER_ASSIGNED
from azext_iot.adr.ui.screens.onboard.permissions import ensure_link_roles, plan_link_roles
from azext_iot.adr.ui.screens.onboard.pickers import Candidate

NS_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
SU_ID = "/subscriptions/target-sub/resourceGroups/rg/providers/Microsoft.DeviceUpdate/updateInstances/su"


def namespace():
    return {
        "id": NS_ID, "location": "eastus2",
        "identity": {"type": "SystemAssigned", "principalId": "namespace-pid"},
        "properties": {"outboundIdentity": {"type": "SystemAssigned"}},
    }


def target():
    return {
        "id": SU_ID, "location": "eastus2",
        "identity": {"type": "SystemAssigned", "principalId": "su-pid"},
        "properties": {"provisioningState": "Succeeded"},
    }


def context():
    return {
        "namespace": namespace(), "namespace_name": "ns", "resource_group_name": "rg",
        "subscription_id": "sub",
        "selected_sus": [Candidate(name="su", resource_id=SU_ID, raw=target())],
    }


def execution_fixture():
    """No clients or tokens: exercise manager policy against mocked assignment reads."""
    cli = Mock()
    cli.invoke.return_value = Mock(success=lambda: True, as_json=lambda: {})
    manager = LinkRbacManager(cli_ctx=Mock(), cli=cli)
    manager._resolve_adu_principal = Mock(return_value="adu-pid")
    manager._current_assignee_object_id = Mock(return_value="operator-pid")
    manager._caller_can_assign = Mock(return_value=True)
    manager._assignment_exists = Mock(return_value=True)
    manager._wait_for_assignments = Mock()
    provider = LinkProvider.__new__(LinkProvider)
    provider._rbac = manager
    provider._get_target = Mock(return_value=target())
    session = Session(None)
    session._providers.update(link=provider, namespace=SimpleNamespace(show=Mock(return_value=namespace())))
    return session, manager, cli


@pytest.mark.parametrize("permissions, action, expected", [
    ([{"actions": ["*"]}], "Microsoft.DeviceRegistry/namespaces/write", True),
    ([{"actions": ["*"], "notActions": ["*/write"]}], "Microsoft.DeviceRegistry/namespaces/write", False),
    ([{"actions": ["microsoft.deviceregistry/*"]}], "Microsoft.DeviceRegistry/namespaces/write", True),
    ([], "Microsoft.DeviceRegistry/namespaces/write", False),
])
def test_resource_permission_matching(permissions, action, expected):
    assert rbac.permits(permissions, action) is expected


def test_permission_probe_failure_is_unknown_not_permission(monkeypatch):
    session = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=SimpleNamespace(
        cloud=SimpleNamespace(endpoints=SimpleNamespace(resource_manager="https://management.azure.com/"))
    )))
    cli = Mock()
    cli.invoke.return_value.success.return_value = False
    monkeypatch.setattr(rbac, "_embedded_cli", lambda _: cli)
    assert rbac.permissions_at_scope(session, NS_ID, ["namespaces/write"]) is None


def test_permission_probe_uses_current_cloud_and_never_acquires_tokens(monkeypatch):
    session = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=SimpleNamespace(
        cloud=SimpleNamespace(endpoints=SimpleNamespace(resource_manager="https://arm.example/"))
    )))
    cli = Mock()
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.return_value = {"value": [{"actions": ["*"]}]}
    monkeypatch.setattr(rbac, "_embedded_cli", lambda _: cli)
    assert rbac.permissions_at_scope(session, NS_ID, ["namespaces/write"]) == {"namespaces/write": True}
    command = cli.invoke.call_args.args[0]
    assert "https://arm.example/" in command
    assert "get-access-token" not in command


def test_review_uses_all_four_authoritative_su_rules():
    items = plan_link_roles(context())
    required = [item for item in items if item.action == "required"]
    assert len(required) == len(LINK_ROLE_MATRIX["su"]) == 4
    for rule in LINK_ROLE_MATRIX["su"]:
        assert any(f"'{rule.role}'" in item.description for item in required)
    assert sum(item.invoke is not None for item in items) == 1
    assert all(item.invoke is None for item in required)
    assert all(item.target in (NS_ID, SU_ID) for item in required)
    assert all(
        f"--subscription {'sub' if item.target == NS_ID else 'target-sub'}" in item.command
        for item in required
    )


def test_existing_inherited_grants_do_not_require_owner_or_assignment_write():
    session, manager, cli = execution_fixture()
    ctx = {**context(), "can_grant_roles": False}
    preflight = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    preflight.invoke(session, ctx)
    manager._current_assignee_object_id.assert_not_called()
    manager._caller_can_assign.assert_not_called()
    cli.invoke.assert_not_called()
    manager._wait_for_assignments.assert_not_called()
    assert manager._assignment_exists.call_count == 4
    manager._assignment_exists.assert_any_call("namespace-pid", "Device Update Administrator", SU_ID)
    manager._resolve_adu_principal.assert_called_once_with("target-sub")


def test_missing_roles_authorize_all_scopes_before_creating_any():
    session, manager, cli = execution_fixture()
    manager._assignment_exists.return_value = False
    manager._caller_can_assign.side_effect = [True, False]
    ctx = context()
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    with pytest.raises(SessionError, match="Owner or User Access Administrator") as error:
        item.invoke(session, ctx)
    assert "Device Update Administrator" in str(error.value)
    cli.invoke.assert_not_called()
    assert manager._caller_can_assign.call_count == 2


def test_missing_roles_are_created_once_and_waited_on_by_base():
    session, manager, cli = execution_fixture()
    manager._assignment_exists.return_value = False
    ctx = context()
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    item.invoke(session, ctx)
    assert cli.invoke.call_count == 4
    manager._wait_for_assignments.assert_called_once()
    assignments = manager._wait_for_assignments.call_args.args[0]
    assert ("namespace-pid", "Device Update Administrator", SU_ID) in assignments
    assert ("adu-pid", "Contributor", SU_ID) in assignments
    assert ("su-pid", "Contributor", NS_ID) in assignments


def test_invalid_target_is_rejected_by_base_before_any_assignment():
    session, manager, cli = execution_fixture()
    session.provider("link")._get_target.return_value = {**target(), "location": "westus2"}
    ctx = context()
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    with pytest.raises(SessionError, match="Cross-region"):
        item.invoke(session, ctx)
    manager._assignment_exists.assert_not_called()
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("resource", ["namespace", "target"])
def test_changed_principal_is_not_silently_granted_roles(resource):
    session, manager, cli = execution_fixture()
    current = namespace() if resource == "namespace" else target()
    current["identity"]["principalId"] = "unreviewed-principal"
    if resource == "namespace":
        session.provider("namespace").show.return_value = current
    else:
        session.provider("link")._get_target.return_value = current
    ctx = context()
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    with pytest.raises(AzureResponseError, match="principal changed"):
        item.invoke(session, ctx)
    manager._assignment_exists.assert_not_called()
    cli.invoke.assert_not_called()


def test_manual_confirmation_cannot_bypass_base_preflight():
    from azext_iot.adr.ui.screens.onboard.steps import build_flow

    ctx = context()
    ctx["namespace"]["properties"]["provisioning"] = {"endpoints": {"dps": {"linkingState": "Succeeded"}}}
    ctx["permissions_confirmed"] = True
    assert any(item.key == "grant-preflight" and item.invoke for item in build_flow(ctx).build_plan())


def test_read_only_cannot_run_even_an_existing_grant_preflight():
    session, manager, cli = execution_fixture()
    session.read_only = True
    with pytest.raises(AzureResponseError, match="Read-only"):
        ensure_link_roles(session, context(), (), IdentityChoice())
    manager._assignment_exists.assert_not_called()
    cli.invoke.assert_not_called()


def test_invalid_su_plan_blocks_roles_without_reads_or_grants():
    session, manager, cli = execution_fixture()
    ctx = context()
    ctx["selected_sus"] *= 2
    assert plan_link_roles(ctx)[0].action == "blocked"
    with pytest.raises(AzureResponseError, match="Only one"):
        ensure_link_roles(session, ctx, (), IdentityChoice())
    session.provider("namespace").show.assert_not_called()
    manager._assignment_exists.assert_not_called()
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("change", ["region", "topology"])
def test_roles_revalidate_namespace_before_target_reads_or_grants(change):
    session, manager, cli = execution_fixture()
    ctx = context()
    live = namespace()
    if change == "region":
        live["location"] = "westus2"
    else:
        live["properties"]["messaging"] = {"endpoints": {"unreviewed": {}}}
    session.provider("namespace").show.return_value = live
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    with pytest.raises(AzureResponseError, match="Cross-region" if change == "region" else "Namespace links"):
        item.invoke(session, ctx)
    session.provider("link")._get_target.assert_not_called()
    manager._assignment_exists.assert_not_called()
    cli.invoke.assert_not_called()


def test_reviewed_inbound_uami_is_forwarded_to_authoritative_base_preflight():
    from azext_iot.adr.ui.screens.onboard.identity import set_choice

    session, manager, cli = execution_fixture()
    ctx = context()
    uami_id = "/subscriptions/target-sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/inbound"
    choice = IdentityChoice(mode=USER_ASSIGNED, uami_id=uami_id, principal_id="uami-pid")
    set_choice(ctx, "su", choice, SU_ID)
    live = target()
    live["identity"]["userAssignedIdentities"] = {uami_id: {"principalId": "uami-pid"}}
    session.provider("link")._get_target.return_value = live
    manager._invoke_json = Mock(return_value={"principalId": "uami-pid"})
    item = next(item for item in plan_link_roles(ctx) if item.invoke is not None)
    item.invoke(session, ctx)
    manager._assignment_exists.assert_any_call("uami-pid", "Contributor", NS_ID)
    manager._caller_can_assign.assert_not_called()
    cli.invoke.assert_not_called()


def test_outbound_identity_change_requires_no_reverse_role_for_link_without_inbound_identity():
    from azext_iot.adr.ui.screens.onboard.identity import set_choice

    ctx = context()
    ctx.pop("selected_sus")
    ctx["namespace"]["properties"]["updating"] = {"endpoints": {"updates": {
        "endpointType": "Microsoft.DeviceUpdate/updateInstances", "resourceId": SU_ID,
        "linkingState": "Succeeded", "serviceAddress": "https://updates.example",
    }}}
    set_choice(ctx, "namespace", IdentityChoice(mode=USER_ASSIGNED, uami_id="/outbound", principal_id="outbound-pid"))
    requirements = [item for item in plan_link_roles(ctx) if item.action == "required"]
    assert len(requirements) == 3
    assert all(item.target == SU_ID for item in requirements)
    assert any("Device Update Administrator" in item.description for item in requirements)
    assert any("first-party" in item.description for item in requirements)


def test_outbound_change_does_not_invent_role_grants_for_unknown_endpoint_types():
    from azext_iot.adr.ui.screens.onboard.identity import set_choice
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    ctx = context()
    ctx.pop("selected_sus")
    ctx["namespace"]["properties"]["updating"] = {"endpoints": {"unsupported": {
        "endpointType": "Unsupported/resources", "resourceId": "/external",
    }}}
    set_choice(ctx, "namespace", IdentityChoice(mode=USER_ASSIGNED, uami_id="/outbound"))
    assert not role_targets(ctx)
    assert not plan_link_roles(ctx)


def test_outbound_change_displays_existing_link_roles_before_namespace_update():
    from azext_iot.adr.ui.screens.onboard.identity import set_choice
    from azext_iot.adr.ui.screens.onboard.steps import build_flow

    ctx = context()
    ctx.pop("selected_sus")
    ctx["namespace"]["properties"].update(
        provisioning={"endpoints": {"dps": {
            "endpointType": "Microsoft.Devices/provisioningServices",
            "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}},
        updating={"endpoints": {"updates": {
            "endpointType": "Microsoft.DeviceUpdate/updateInstances", "resourceId": SU_ID,
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}},
    )
    set_choice(ctx, "namespace", IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/outbound",
    ))
    plan = build_flow(ctx).build_plan()
    assert any("Device Update Administrator" in item.description for item in plan)
    assert any("first-party" in item.description for item in plan)
    keys = [item.key for item in plan]
    assert keys.index("grant-preflight") < keys.index("identity")


@pytest.mark.parametrize("mode", ["system", "user"], ids=["namespace-sami", "outbound-uami"])
def test_built_plan_keeps_reviewed_principal_after_initial_topology_refresh(mode):
    from azext_iot.adr.ui.screens.onboard.execution import ExecutionRecord, ExecutionState, execute_records
    from azext_iot.adr.ui.screens.onboard.identity import set_choice
    from azext_iot.adr.ui.screens.onboard.steps import PHASE_GRANT, build_flow

    session, manager, cli = execution_fixture()
    ctx = context()
    ctx["namespace"]["properties"]["provisioning"] = {"endpoints": {"dps": {"linkingState": "Succeeded"}}}
    uami_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/outbound"
    if mode == "user":
        set_choice(ctx, "namespace", IdentityChoice(mode=USER_ASSIGNED, uami_id=uami_id))
        ctx["namespace"]["properties"]["outboundIdentity"] = {
            "type": "UserAssigned", "userAssignedIdentity": uami_id,
        }
        ctx["namespace"]["identity"]["userAssignedIdentities"] = {
            uami_id: {"principalId": "reviewed-uami-pid"},
        }
    records = [
        ExecutionRecord(item) for item in build_flow(ctx).build_plan()
        if item.invoke is not None and item.phase <= PHASE_GRANT
    ]
    assert [record.item.key for record in records] == ["preflight", "grant-preflight"]
    live = deepcopy(ctx["namespace"])
    if mode == "system":
        live["identity"]["principalId"] = "recreated-principal"
    else:
        live["identity"]["userAssignedIdentities"][uami_id]["principalId"] = "recreated-principal"
        manager._invoke_json = Mock(return_value={"principalId": "recreated-principal"})
    session.provider("namespace").show.return_value = live

    assert not execute_records(records, session, ctx, lambda _: None)
    assert records[0].state is ExecutionState.SUCCEEDED
    assert ctx["namespace"] is live  # prove preflight replaced the payload before the RBAC step
    assert records[1].state is ExecutionState.FAILED
    assert "reviewed managed-identity principal changed" in records[1].error
    manager._assignment_exists.assert_not_called()
    manager._resolve_adu_principal.assert_not_called()
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("mode", ["system", "user"], ids=["new-namespace-sami", "new-namespace-uami"])
def test_built_plan_allows_principals_unknown_until_namespace_creation(monkeypatch, mode):
    from azext_iot.adr.ui.screens.onboard import steps
    from azext_iot.adr.ui.screens.onboard.create import CreateRequest
    from azext_iot.adr.ui.screens.onboard.execution import ExecutionRecord, execute_records

    session, manager, _cli = execution_fixture()
    uami_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/outbound"
    choice = IdentityChoice(mode=mode, uami_id=uami_id if mode == "user" else "")
    dps_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps"
    ctx = {
        "namespace": {}, "namespace_name": "ns", "resource_group_name": "rg", "subscription_id": "sub",
        "create_namespace": CreateRequest("namespace", "ns", "rg", "eastus2", identity=choice),
        "selected_dps": Candidate("dps", dps_id, raw=target()),
    }
    live = namespace()
    live["identity"]["principalId"] = "fresh-principal"
    if mode == "user":
        live["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": uami_id}
        live["identity"]["userAssignedIdentities"] = {uami_id: {"principalId": "fresh-principal"}}
        manager._invoke_json = Mock(return_value={"principalId": "fresh-principal"})
    create = Mock(return_value=None)
    monkeypatch.setattr(steps, "create_namespace", create)

    def show(**_):
        create.assert_called_once()  # initial preflight must not query a planned namespace
        return live

    session.provider("namespace").show.side_effect = show
    records = [
        ExecutionRecord(item) for item in steps.build_flow(ctx).build_plan()
        if item.invoke is not None and item.phase <= steps.PHASE_GRANT
    ]
    assert execute_records(records, session, ctx, lambda _: None)
    manager._assignment_exists.assert_any_call("fresh-principal", "Contributor", dps_id)
