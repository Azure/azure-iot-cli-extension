# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Per-operation guided-linking execution behavior."""

from unittest.mock import Mock

import pytest

from azext_iot.adr.ui.screens.onboard.create import CreateRequest
from azext_iot.adr.ui.screens.onboard.execution import (
    ExecutionRecord,
    ExecutionState,
    execute_records,
)
from azext_iot.adr.ui.screens.onboard.flow import PlanItem
from azext_iot.adr.ui.screens.onboard.pickers import Candidate, evaluate
from azext_iot.adr.ui.screens.onboard.steps import build_flow


def test_execution_tracks_mutation_polling_and_success():
    seen = []
    item = PlanItem(
        key="link",
        description="Link DPS",
        invoke=lambda _session, _context: None,
        verify=lambda _session, _context, notify: notify("linkingState: Succeeded"),
    )
    record = ExecutionRecord(item)
    assert execute_records(
        [record],
        object(),
        {},
        lambda _poller: None,
        lambda current: seen.append(current.state),
    )
    assert ExecutionState.RUNNING in seen
    assert ExecutionState.POLLING in seen
    assert record.state is ExecutionState.SUCCEEDED
    assert record.detail == "linkingState: Succeeded"


def test_critical_failure_skips_remaining_operations():
    def fail(_session, _context):
        raise RuntimeError("role assignment denied")

    records = [
        ExecutionRecord(PlanItem(key="grant", description="Grant role", invoke=fail)),
        ExecutionRecord(
            PlanItem(
                key="link",
                description="Link Hub",
                invoke=lambda _session, _context: None,
            )
        ),
    ]
    assert not execute_records(records, object(), {}, lambda _poller: None)
    assert records[0].state is ExecutionState.FAILED
    assert records[1].state is ExecutionState.SKIPPED


def planned_namespace_context():
    return {
        "namespace": {}, "namespace_name": "ns", "resource_group_name": "rg", "subscription_id": "sub",
        "create_namespace": CreateRequest("namespace", "ns", "rg", "eastus2"),
        "create_hub": CreateRequest("hub", "new-hub", "rg", "eastus2"),
        "selected_dps": Candidate("dps", "/dps", location="eastus2"),
    }


@pytest.mark.parametrize("kind", ["dps", "hub", "su"])
@pytest.mark.parametrize("location_source", ["summary", "payload"])
def test_known_target_region_mismatch_blocks_all_creates(monkeypatch, kind, location_source):
    from azext_iot.adr.ui.screens.onboard import steps

    ctx = planned_namespace_context()
    candidate = Candidate(
        kind, f"/{kind}",
        location="westus2" if location_source == "summary" else "",
        raw={"location": "westus2"} if location_source == "payload" else {},
    )
    key = {"dps": "selected_dps", "hub": "selected_hubs", "su": "selected_sus"}[kind]
    ctx[key] = candidate if kind == "dps" else [candidate]
    create_namespace = Mock()
    monkeypatch.setattr(steps, "create_namespace", create_namespace)
    session = Mock()
    ctx["_catalog"] = Mock()
    flow = build_flow(ctx)
    plan = flow.build_plan()
    assert len(plan) == 1 and plan[0].action == "blocked"
    assert "Cross-region linking is not supported" in plan[0].blocked_reason
    assert "exit 1" in flow.script()
    records = [ExecutionRecord(item) for item in plan if item.invoke is not None]
    assert not records
    execute_records(records, session, ctx, lambda _: None)
    create_namespace.assert_not_called()
    assert not session.mock_calls
    assert not ctx["_catalog"].mock_calls


@pytest.mark.parametrize("kind", ["dps", "hub", "su"])
def test_known_planned_target_region_mismatch_blocks_creation(kind):
    ctx = planned_namespace_context()
    ctx[f"create_{kind}"] = CreateRequest(kind, "cross-region", "rg", "westus2")
    plan = build_flow(ctx).build_plan()
    assert plan[0].action == "blocked"
    assert "Cross-region" in plan[0].blocked_reason
    assert not any(item.invoke for item in plan)


def test_initial_preflight_rechecks_known_regions_without_querying_placeholders(monkeypatch):
    from azext_iot.adr.ui.screens.onboard import steps

    ctx = planned_namespace_context()
    records = [
        ExecutionRecord(item) for item in build_flow(ctx).build_plan() if item.invoke is not None
    ]
    ctx["selected_dps"].location = "westus2"
    session = Mock(read_only=False)
    create_namespace = Mock()
    monkeypatch.setattr(steps, "create_namespace", create_namespace)
    assert not execute_records(records, session, ctx, lambda _: None)
    assert records[0].state is ExecutionState.FAILED
    assert "Cross-region" in records[0].error
    assert all(record.state is ExecutionState.SKIPPED for record in records[1:])
    session.provider.assert_not_called()
    create_namespace.assert_not_called()


def test_picker_uses_planned_namespace_location():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    ctx = planned_namespace_context()
    screen = OnboardScreen(None, scope=ctx)
    assert screen._namespace_location() == "eastus2"
    assert not evaluate(
        {"name": "target", "location": "westus2"},
        namespace_location=screen._namespace_location(),
    ).selectable
    # Once loaded, the namespace's actual location takes precedence over stale plans.
    screen.context["namespace"] = {"location": "westus2"}
    assert screen._namespace_location() == "westus2"
