# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Software Updates cardinality and immutable-target behavior across review and execution."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.screens.onboard.create import CreateRequest
from azext_iot.adr.ui.screens.onboard.pickers import Candidate
from azext_iot.adr.ui.screens.onboard.steps import (
    build_flow, plan_permissions, plan_software_updates, software_updates_error,
)

SU_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceUpdate/updateInstances/updates"


def selected(resource_id=SU_ID):
    return Candidate(name=resource_id.rsplit("/", 1)[-1], resource_id=resource_id)


def context(existing=False):
    properties = {
        "outboundIdentity": {"type": "SystemAssigned"},
        "provisioning": {"endpoints": {"dps": {}}},
    }
    if existing:
        properties["updating"] = {"endpoints": {"existing-updates": {
            "endpointType": "Microsoft.DeviceUpdate/updateInstances", "resourceId": SU_ID,
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}}
    return {
        "subscription_id": "sub", "resource_group_name": "rg", "namespace_name": "ns",
        "namespace": {"properties": properties,
                      "identity": {"type": "SystemAssigned", "principalId": "ns-pid"}},
    }


def create_request():
    return CreateRequest(kind="su", name="new-instance", resource_group_name="rg", location="eastus2")


@pytest.mark.parametrize("existing, selections, creating", [
    (False, [SU_ID, SU_ID + "-2"], False),
    (False, [SU_ID], True),
    (False, [SU_ID, SU_ID], False),
    (True, [SU_ID + "-2"], False),
    (True, [], True),
    (True, [SU_ID], True),
])
def test_invalid_plan_has_no_executable_grants_identities_creates_or_links(existing, selections, creating):
    ctx = context(existing=existing)
    ctx["selected_sus"] = [selected(resource_id) for resource_id in selections]
    if creating:
        ctx["create_su"] = create_request()
    flow = build_flow(ctx)
    assert software_updates_error(ctx)
    assert all(item.invoke is None for item in flow.build_plan())
    assert plan_permissions(ctx)[0].action == "blocked"
    assert plan_software_updates(ctx)[0].action == "blocked"
    script = flow.script()
    assert "exit 1" in script
    assert "\naz role assignment create" not in script
    assert "\naz iot adr" not in script


def test_existing_and_unselected_instance_stays_untouched():
    ctx = context(existing=True)
    flow = build_flow(ctx)
    assert not software_updates_error(ctx)
    su = next(item for item in flow.build_plan() if item.key == "su")
    assert su.action == "exists"
    assert not any("link su add" in item.command for item in flow.build_plan())


def test_same_existing_target_updates_only_identity_and_preserves_endpoint_name():
    ctx = context(existing=True)
    ctx["selected_sus"] = [selected(SU_ID.upper() + "/")]
    ctx["su_endpoint_name"] = "must-not-rename"
    assert not software_updates_error(ctx)
    item = next(item for item in plan_software_updates(ctx) if item.key == "su")
    assert "link su update" in item.command
    assert "--endpoint-name existing-updates" in item.command
    assert "--su-id" not in item.command
    assert "--system-assigned-mi" in item.command
    assert "existing" in item.description
    provider = SimpleNamespace(su_update=Mock(), su_add=Mock())
    session = Session(None)
    session._providers["link"] = provider
    item.invoke(session, ctx)
    provider.su_add.assert_not_called()
    kwargs = provider.su_update.call_args.kwargs
    assert kwargs["endpoint_name"] == "existing-updates"
    assert kwargs["mi_system_assigned"] is True
    assert "su_resource_id" not in kwargs


def test_new_instance_is_created_before_linking_and_uses_canonical_flags():
    ctx = context()
    ctx["create_su"] = create_request()
    plan = plan_software_updates(ctx)
    assert next(item for item in plan if item.key == "su-create").phase < next(
        item for item in plan if item.key == "su"
    ).phase
    assert "--system-assigned-mi" in plan[0].command
    assert "--mi-system-assigned" not in plan[0].command


def test_newly_discovered_existing_instance_stops_before_any_mutation():
    ctx = context()
    ctx["selected_sus"] = [selected(SU_ID + "-other")]
    plan = build_flow(ctx).build_plan()
    runnable = [item for item in plan if item.invoke is not None]
    assert runnable[0].key == "preflight"
    session = Session(None)
    provider = Mock()
    provider.show.return_value = context(existing=True)["namespace"]
    session._providers["namespace"] = provider
    with pytest.raises(AzureResponseError, match="already has a Software Updates instance"):
        runnable[0].invoke(session, ctx)
    assert [call[0] for call in provider.method_calls] == ["show"]
    assert "link" not in session._providers


def test_existing_multiple_endpoints_are_rejected_even_without_a_new_selection():
    ctx = context(existing=True)
    endpoints = ctx["namespace"]["properties"]["updating"]["endpoints"]
    endpoints["second"] = deepcopy(endpoints["existing-updates"])
    assert build_flow(ctx).build_plan()[0].action == "blocked"


def test_export_does_not_blindly_create_role_assignments():
    ctx = context()
    ctx["selected_sus"] = [selected()]
    script = build_flow(ctx).script()
    assert "Device Update Administrator" in script
    assert "first-party" in script
    assert "# Remediation only: az role assignment create" in script
    assert "\naz role assignment create" not in script
    assert "\nsleep " not in script
    assert "\naz iot adr ns link su add" in script


@pytest.mark.parametrize("timed_out", [False, True], ids=["success-reload", "persisted-on-timeout-retry"])
def test_reload_reconciles_a_completed_su_creation(monkeypatch, timed_out):
    from azext_iot.adr.ui.screens.onboard import steps
    from azext_iot.adr.ui.screens.onboard.execution import ExecutionRecord, execute_records
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    ctx = context()
    request = create_request()
    ctx["create_su"] = request
    live = deepcopy(ctx["namespace"])
    create = Mock(return_value=None)
    monkeypatch.setattr(steps, "create_update_instance", create)

    def persist_link(**kwargs):
        assert kwargs["su_resource_id"] == request.arm_id("sub")
        live["properties"]["updating"] = {"endpoints": {"su": {
            "endpointType": "Microsoft.DeviceUpdate/updateInstances",
            "resourceId": request.arm_id("sub").upper() + "/",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
            "linkingState": "Succeeded", "serviceAddress": "updates.example",
        }}}
        if timed_out:
            raise TimeoutError("local timeout after Azure persisted the link")

    session = Session(None)
    session._providers.update(
        namespace=SimpleNamespace(show=Mock(return_value=live)),
        link=SimpleNamespace(su_add=Mock(side_effect=persist_link)),
    )
    records = [
        ExecutionRecord(item) for item in build_flow(ctx).build_plan()
        if item.key in ("su-create", "su")
    ]
    assert execute_records(records, session, ctx, lambda _: None) is not timed_out
    create.assert_called_once()
    assert "create_su" in ctx

    screen = OnboardScreen(session, scope=ctx, namespace=ctx["namespace"])
    screen.refresh_view = Mock()
    screen._reload_candidates = Mock()
    # The actual reload callback, used both after success and after a failed execution.
    screen._apply_namespace(live)
    assert "create_su" not in screen.context
    assert not software_updates_error(screen.context)
    retry = screen.flow.build_plan()
    assert not any(item.action == "blocked" and item.key == "validation" for item in retry)
    assert not any(item.key == "su-create" for item in retry)
    assert next(item for item in retry if item.key == "su").action == "exists"
    assert not any("link su add" in item.command for item in retry)


def test_reload_keeps_a_conflicting_su_creation_blocked():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    ctx = context()
    ctx["create_su"] = create_request()  # new-instance differs from the persisted updates instance
    screen = OnboardScreen(None, scope=ctx, namespace=ctx["namespace"])
    screen.refresh_view = Mock()
    screen._reload_candidates = Mock()
    screen._apply_namespace(context(existing=True)["namespace"])
    assert screen.context["create_su"] is ctx["create_su"]
    assert screen.flow.build_plan()[0].action == "blocked"
