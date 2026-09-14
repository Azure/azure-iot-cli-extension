# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Onboarding controls: real headless UI, deterministic catalog and Azure boundaries."""

import asyncio
import shlex
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.widgets import Button, DataTable, Input, ListView, Static

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core import rbac
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.onboard.create import CreateRequest
from azext_iot.adr.ui.screens.onboard.execution import ExecutionScreen, ExecutionState
from azext_iot.adr.ui.screens.onboard.flow import Flow, PlanItem, ScriptCheck, Step
from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice, USER_ASSIGNED, get_choice, has_choice, set_choice, system_choice,
)
from azext_iot.adr.ui.screens.onboard.identity_dialog import IdentityChoiceDialog
from azext_iot.adr.ui.screens.onboard.pickers import Candidate, INELIGIBLE, catalog_key
from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen, PlanDialog
from azext_iot.adr.ui.screens.onboard.steps import has_namespace, link_targets
from azext_iot.adr.ui.widgets.tray import CommandPreviewDialog


def resource(name="factory", kind="Microsoft.DeviceRegistry/namespaces", **extra):
    return {
        "name": name,
        "id": f"/subscriptions/sub-1/resourceGroups/rg-test/providers/{kind}/{name}",
        "location": "eastus2",
        "identity": {"type": "SystemAssigned", "principalId": f"principal-{name}"},
        "properties": {"outboundIdentity": {"type": "SystemAssigned"}},
        **extra,
    }


def candidate(name="hub-test", kind="Microsoft.Devices/IotHubs", **extra):
    raw = resource(name, kind)
    return Candidate(name, raw["id"], resource_group="rg-test", location="eastus2", raw=raw, **extra)


def make_screen(**context):
    return OnboardScreen(
        None,
        {"subscription_id": "sub-1", "resource_group_name": "rg-test", "namespace_name": "factory", **context},
        namespace=resource(),
    )


async def settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def drive(scenario, screen=None):
    async def run():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(140, 50)) as pilot:
            await settle(app, pilot)
            onboard = screen if screen is not None else make_screen()
            await app.push_screen(onboard)
            await settle(app, pilot)
            await scenario(app, pilot, onboard)
            await settle(app, pilot)

    asyncio.run(run())


def rendered(screen, selector):
    return str(screen.query_one(selector, Static).render())


def focus_step(screen, step_id, candidates=()):
    screen._focus_step = step_id
    screen._candidates_for = step_id
    screen._candidates = list(candidates)
    screen._candidates_loading = False
    screen.refresh_view()
    screen._paint_candidates()


def review_flow(screen, items):
    screen.flow = Flow([Step("review", "Review and run", plan=lambda _: items)], screen.context)
    screen._focus_step = "review"
    screen.refresh_view()


def test_permission_requirements_include_planned_resources_and_uamis_at_their_real_scopes():
    screen = make_screen()
    screen.context["create_resource_group"] = CreateRequest("resource_group", "new-rg", "new-rg", "eastus2")
    uami = IdentityChoice(USER_ASSIGNED, "/identities/shared", create_uami=True, uami_resource_group="new-rg")
    screen.context["create_namespace"] = CreateRequest("namespace", "factory", "rg-test", "eastus2", identity=uami)
    for kind in ("dps", "hub", "su"):
        screen.context[f"create_{kind}"] = CreateRequest(kind, f"new-{kind}", "new-rg", "eastus2")
    existing = candidate()
    screen.context["selected_hubs"] = [existing]
    set_choice(screen.context, "hub", system_choice(), existing.resource_id)
    requirements = screen._permission_requirements()
    assert requirements == {
        resource()["id"]: {"Microsoft.DeviceRegistry/namespaces/write"},
        "/subscriptions/sub-1": {
            "Microsoft.Devices/provisioningServices/write",
            "Microsoft.Devices/IotHubs/write",
            "Microsoft.DeviceUpdate/updateInstances/write",
            "Microsoft.Resources/subscriptions/resourceGroups/write",
            "Microsoft.ManagedIdentity/userAssignedIdentities/read",
            "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
            "Microsoft.ManagedIdentity/userAssignedIdentities/write",
        },
    }
    assert existing.raw == resource("hub-test", "Microsoft.Devices/IotHubs")


@pytest.mark.parametrize("result, ready", [({"write": True}, True), ({"write": False}, False), (None, False)])
def test_permission_worker_publishes_results_once_and_rejects_stale_probe(monkeypatch, result, ready):
    check = Mock(return_value=result)
    monkeypatch.setattr(rbac, "permissions_at_scope", check)

    async def scenario(app, pilot, screen):
        session = SimpleNamespace()
        screen.session = session
        screen._probe_grant_rights()
        assert screen.context["permission_checking"]
        signature = screen.context["_grant_probe_for"]
        await settle(app, pilot)
        check.assert_called_once_with(session, resource()["id"], ["Microsoft.DeviceRegistry/namespaces/write"])
        assert screen.context["can_write_resources"] is ready
        assert not screen.context["permission_checking"]
        assert screen.context["permission_matrix"] == {resource()["id"]: result}
        screen._probe_grant_rights()
        check.assert_called_once()
        before = deepcopy(screen.context)
        screen._grant_rights_read(("old subscription",), {}, not ready)
        assert screen.context == before
        screen.context["_grant_probe_for"] = signature

    drive(scenario)


@pytest.mark.parametrize("mode", ["missing-identity", "ready", "changes", "blocked"])
def test_review_explains_blockers_required_roles_and_truncates_only_long_change_lists(mode):
    async def scenario(app, pilot, screen):
        operation = Mock()
        items = []
        if mode == "missing-identity":
            screen.context["identity_choices"].clear()
        elif mode in ("changes", "blocked"):
            items = [PlanItem(f"resource-{index}", f"Change {index}", invoke=operation) for index in range(8)]
            items += [
                PlanItem("grant-preflight", "Check roles", invoke=operation),
                PlanItem("grant-propagation", "Wait for roles", invoke=operation),
                PlanItem("role", "Device Registry role", action="required", target="/scope"),
            ]
            if mode == "blocked":
                items.append(PlanItem("blocked", "Missing target", action="blocked", blocked_reason="Choose DPS"))
        review_flow(screen, items)
        body = rendered(screen, "#step-body")
        if mode == "missing-identity":
            assert "BLOCKED" in body and "namespace 'factory'" in body and "press i" in body
        elif mode == "ready":
            assert "Everything is already configured. Nothing to run." in body
        else:
            assert "10 operations (8 resource changes)" in body
            assert "Change 5" in body and "Change 6" not in body
            assert "2 more; press p for details" in body
            assert "REQUIRED SERVICE ROLES" in body and "Scope: /scope" in body
            assert ("Choose DPS" if mode == "blocked" else "a Run setup") in body
        operation.assert_not_called()

    drive(scenario)


@pytest.mark.parametrize(
    "guard, message",
    [
        ("read-only", "read-only session: apply is disabled"),
        ("identity", "choose the managed identity for namespace 'factory' before running"),
        ("busy", "permission preflight is still running"),
        ("denied", "setup needs resource-write access"),
        ("blocked", "setup is blocked: Choose DPS"),
        ("empty", "nothing to apply"),
    ],
)
def test_apply_guards_never_open_confirmation_or_execute(guard, message):
    async def scenario(app, pilot, screen):
        invoke = Mock()
        items = [PlanItem("safe", "Offline operation", invoke=invoke)]
        if guard == "read-only":
            app.read_only = True
        elif guard == "identity":
            screen.context["identity_choices"].clear()
        elif guard == "busy":
            screen.context["permission_checking"] = True
        elif guard == "denied":
            screen.context["can_write_resources"] = False
        elif guard == "blocked":
            items.append(PlanItem("stop", "Stop", action="blocked", blocked_reason="Choose DPS"))
        elif guard == "empty":
            items = []
        review_flow(screen, items)
        before = deepcopy(screen.context)
        screen.action_apply()
        await pilot.pause()
        assert app.screen is screen
        assert message in rendered(screen, "#flash-line")
        assert screen.context == before
        invoke.assert_not_called()

    drive(scenario)


@pytest.mark.parametrize("approve", [False, True])
def test_apply_confirmation_freezes_commands_and_only_approval_executes_then_reloads(approve, monkeypatch):
    check = Mock(return_value={"write": True})
    monkeypatch.setattr(rbac, "permissions_at_scope", check)

    async def scenario(app, pilot, screen):
        invoke = Mock(return_value=None)
        live = resource(properties={"outboundIdentity": {"type": "SystemAssigned"}, "provisioning": {"endpoints": {"dps": {}}}})
        provider = SimpleNamespace(show=Mock(return_value=live))
        session = SimpleNamespace(provider=Mock(return_value=provider), call=lambda fn, **kw: fn(**kw))
        screen.session = session
        items = [
            PlanItem("role", "Read service role", action="required", target="/resource-scope"),
            PlanItem("safe", "Offline operation", command="az example run", invoke=invoke),
        ]
        review_flow(screen, items)
        await settle(app, pilot)
        build_plan = Mock(wraps=screen.flow.build_plan)
        monkeypatch.setattr(screen.flow, "build_plan", build_plan)
        screen.action_apply()
        build_plan.assert_called_once_with()
        await pilot.pause()
        assert isinstance(app.screen, CommandPreviewDialog)
        assert "Scope: /resource-scope" in app.screen._note
        assert "az example run" in app.screen._command
        assert "Only missing grants require Owner/User Access Administrator" in app.screen._note
        invoke.assert_not_called()
        if approve:
            app.screen.query_one("#run", Button).press()
        else:
            await pilot.press("escape")
        await settle(app, pilot)
        if approve:
            assert isinstance(app.screen, ExecutionScreen)
            assert app.screen.records[0].state is ExecutionState.SUCCEEDED
            invoke.assert_called_once_with(session, screen.context)
            provider.show.assert_called_once_with(namespace_name="factory", resource_group_name="rg-test")
            assert screen.context["namespace"] == live
            assert screen._state_loaded
        else:
            assert app.screen is screen
            invoke.assert_not_called()
            provider.show.assert_not_called()

    drive(scenario)


@pytest.mark.parametrize("failure", [False, True])
def test_export_copies_the_reviewed_script_or_explains_clipboard_unavailability(monkeypatch, failure):
    async def scenario(app, pilot, screen):
        copy = Mock(side_effect=RuntimeError("SSH has no clipboard") if failure else None)
        monkeypatch.setattr(app, "copy_to_clipboard", copy)
        before = deepcopy(screen.context)
        screen.action_export()
        copy.assert_called_once_with(screen.flow.script())
        message = "clipboard unavailable; press p" if failure else "runnable setup script copied"
        assert message in rendered(screen, "#flash-line")
        assert screen.context == before

    drive(scenario)


@pytest.mark.parametrize(
    "kind, field, value, problem",
    [
        ("namespace", "create-name", " ", "a name is required"),
        ("namespace", "create-location", "", "a region is required"),
        ("namespace", "create-tags", "no-equals", "must use key=value"),
        ("namespace", "resource_group_name", "", "a resource group is required"),
        ("hub", "create-sku", "B1", "Standard Hub SKU"),
        ("hub", "create-capacity", "0", "whole number greater than zero"),
        ("hub", "create-capacity", "1.5", "whole number greater than zero"),
        ("dps", "create-capacity", "-1", "whole number greater than zero"),
    ],
)
def test_inline_creation_errors_keep_the_form_and_context_unchanged(kind, field, value, problem):
    async def scenario(app, pilot, screen):
        focus_step(screen, kind)
        screen.action_create_new()
        screen.query_one("#create-name", Input).value = "new-resource"
        if field == "resource_group_name":
            screen.context[field] = value
        else:
            screen.query_one(f"#{field}", Input).value = value
        before = deepcopy(screen.context)
        screen.query_one("#create-confirm", Button).press()
        await pilot.pause()
        assert app.screen is screen
        assert screen.query_one("#create-form").display
        assert problem in rendered(screen, "#create-error")
        assert screen.context == before
        await pilot.press("escape")
        assert not screen.query_one("#create-form").display
        assert screen.context == before

    drive(scenario)


@pytest.mark.parametrize("kind", ["scope", "namespace", "dps", "hub", "su"])
def test_inline_creation_queues_only_after_identity_confirmation_and_can_be_edited(kind):
    async def scenario(app, pilot, screen):
        focus_step(screen, kind)
        screen.action_create_new()
        await pilot.pause()
        assert app.focused.id == "create-name"
        screen.query_one("#create-name", Input).value = " new-resource "
        screen.query_one("#create-location", Input).value = " eastus2 "
        screen.query_one("#create-tags", Input).value = "owner=team"
        if kind in ("hub", "dps"):
            screen.query_one("#create-capacity", Input).value = "3"
        if kind == "hub":
            screen.query_one("#create-sku", Input).value = "s2"
        screen.query_one("#create-location", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        key = "create_resource_group" if kind == "scope" else f"create_{kind}"
        if kind != "scope":
            assert isinstance(app.screen, IdentityChoiceDialog)
            assert key not in screen.context
            app.screen.query_one("#identity-sami", Button).press()
            await pilot.pause()
        request = screen.context[key]
        assert request.name == "new-resource"
        assert request.location == "eastus2"
        assert request.resource_group_name == ("new-resource" if kind == "scope" else "rg-test")
        assert request.capacity == (3 if kind in ("hub", "dps") else 1)
        assert request.sku == {"hub": "S2", "dps": "S1"}.get(kind)
        assert request.tags == ({"owner": "team"} if kind == "namespace" else None)
        assert request.identity == system_choice()
        assert screen.context["namespace"] == ({} if kind == "namespace" else resource())
        focus_step(screen, kind)
        screen.action_create_new()
        assert "EDIT PLANNED" in rendered(screen, "#create-kicker")
        assert screen.query_one("#create-name", Input).value == "new-resource"
        assert str(screen.query_one("#create-confirm", Button).label) == "Update setup"
        screen.query_one("#create-name", Input).value = "edited-resource"
        screen.query_one("#create-confirm", Button).press()
        await pilot.pause()
        if kind != "scope":
            app.screen.query_one("#identity-sami", Button).press()
            await pilot.pause()
        assert screen.context[key].name == "edited-resource"
        assert request.name == "new-resource", "Editing replaces the old request rather than mutating it"
        assert "updated" in rendered(screen, "#flash-line")

    drive(scenario)


def test_editing_namespace_tags_round_trips_whitespace_quotes_and_backslashes():
    async def scenario(app, pilot, screen):
        tags = {"owner": "two people", "note": "it's a test", "path": r"team\west"}
        request = CreateRequest("namespace", "planned", "rg-test", "eastus2", tags=tags)
        screen.context["create_namespace"] = request
        focus_step(screen, "namespace")
        screen.action_create_new()
        screen.query_one("#create-confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog), rendered(screen, "#create-error")
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert screen.context["create_namespace"].tags == tags
        assert request.tags == tags

    drive(scenario)


def test_identity_cancel_does_not_queue_a_creation_and_editing_changes_only_its_identity():
    async def scenario(app, pilot, screen):
        focus_step(screen, "dps")
        screen.action_create_new()
        screen.query_one("#create-name", Input).value = "new-dps"
        screen.query_one("#create-confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog)
        await pilot.press("escape")
        assert "create_dps" not in screen.context
        request = CreateRequest("dps", "planned-dps", "rg-test", "eastus2")
        screen.context["create_dps"] = request
        screen.action_configure_identity()
        await pilot.pause()
        assert app.screen.current == system_choice()
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert screen.context["create_dps"] is request
        assert "DPS will use System-assigned" in rendered(screen, "#flash-line")

    drive(scenario)


@pytest.mark.parametrize("kind, method", [
    ("subscription", "subscriptions"), ("scope", "resource_groups"), ("namespace", "namespaces"),
    ("dps", "provisioning_services"), ("hub", "hubs"), ("su", "update_instances"),
])
def test_each_picker_worker_uses_its_catalog_and_repaints_ranked_rows(kind, method):
    async def scenario(app, pilot, screen):
        rows = [resource("zulu", sku={"name": "S1"}), resource("alpha", sku={"name": "S1"})]
        list_resources = Mock(return_value=rows)
        catalog = SimpleNamespace(**{method: list_resources}, registered_hub_names=Mock(return_value=["zulu.azure-devices.net"]))
        screen.catalog = catalog
        selected_dps = candidate("dps-test", "Microsoft.Devices/provisioningServices")
        screen.context["selected_dps"] = selected_dps
        screen._focus_step = kind
        screen._candidates_for = None
        screen._reload_candidates()
        assert screen._candidates_loading
        assert screen.query_one("#candidate-loading").display
        assert not screen.query_one("#candidates").display
        assert "Loading" in rendered(screen, "#candidate-status")
        await settle(app, pilot)
        if kind == "namespace":
            list_resources.assert_called_once_with(None, "rg-test")
        else:
            list_resources.assert_called_once_with()
        expected = ["zulu", "alpha"] if kind == "hub" else ["alpha", "zulu"]
        assert [row.name for row in screen._candidates] == expected
        table = screen.query_one("#candidates", DataTable)
        assert table.row_count == 2
        assert table.display and not screen.query_one("#candidate-loading").display
        assert "2 candidates" in rendered(screen, "#candidate-status")
        if kind == "hub":
            catalog.registered_hub_names.assert_called_once_with(selected_dps.raw)
            assert screen._candidates[0].recommended
        screen._reload_candidates()
        list_resources.assert_called_once()
        screen._focus_step = "review"
        screen._reload_candidates()
        assert not table.display and table.row_count == 0
        assert rendered(screen, "#candidate-status") == ""

    drive(scenario)


@pytest.mark.parametrize("failure_style", ["exception", "errors", "error_for", "empty"])
def test_picker_failures_are_distinguished_from_empty_results(failure_style):
    async def scenario(app, pilot, screen):
        loader = Mock(return_value=[], side_effect=RuntimeError("list denied") if failure_style == "exception" else None)
        catalog = SimpleNamespace(namespaces=loader)
        if failure_style == "errors":
            catalog.errors = {catalog_key("namespace", "rg-test"): "list denied"}
        elif failure_style == "error_for":
            catalog.error_for = Mock(return_value="list denied")
        screen.catalog = catalog
        screen._focus_step = "namespace"
        screen._candidates_for = None
        screen._reload_candidates()
        await settle(app, pilot)
        assert not screen._candidates_loading
        assert screen.query_one("#candidates", DataTable).row_count == 0
        message = rendered(screen, "#candidate-status")
        assert ("could not list candidates: list denied" if failure_style in ("errors", "error_for")
                else "No Device Registry namespaces") in message
        if failure_style == "error_for":
            catalog.error_for.assert_called_with("namespace", "rg-test")
        assert "selected_dps" not in screen.context

    drive(scenario)


def test_filter_submit_keeps_matching_selection_and_escape_clears_without_leaving_setup():
    async def scenario(app, pilot, screen):
        rows = [candidate("alpha"), candidate("beta")]
        focus_step(screen, "hub", rows)
        screen.action_start_filter()
        field = screen.query_one("#candidate-filter", Input)
        field.value = "BETA"
        await pilot.pause()
        assert screen.query_one("#candidates", DataTable).row_count == 1
        assert "1 of 2 candidates" in rendered(screen, "#candidate-status")
        await pilot.press("enter")
        assert not field.display
        assert screen._selected_candidate() is rows[1]
        assert screen._candidate_filter == "BETA"
        screen.action_start_filter()
        await pilot.press("escape")
        assert app.screen is screen
        assert screen._candidate_filter == ""
        assert screen.query_one("#candidates", DataTable).row_count == 2
        assert screen._selected_candidate() is rows[1], "Clearing a filter preserves the row's resource identity"
        assert not screen.context.get("selected_hubs")
        await pilot.press("escape")
        assert app.screen is not screen

    drive(scenario)


@pytest.mark.parametrize("matrix", [None, {}, {"one": None, "two": {"write": False}, "three": {"write": True}}])
def test_plan_dialog_displays_permission_states_and_operation_commands(matrix):
    async def scenario(app, pilot, screen):
        screen.context["permission_checking"] = matrix is None
        screen.context["permission_matrix"] = matrix
        items = [
            PlanItem("new", "Create a resource", command="az example create"),
            PlanItem("blocked", "Blocked link", action="blocked", blocked_reason="DPS first"),
        ]
        review_flow(screen, items)
        screen.action_show_plan()
        await pilot.pause()
        plan = app.screen
        assert isinstance(plan, PlanDialog)
        text = rendered(plan, "#plan-body")
        assert "nothing has been applied yet" in text
        assert "Namespace -> targets" in text and "System-assigned" in text
        assert "az example create" in text and "DPS first" in text
        if matrix is None:
            assert "Checking every involved resource group" in text
        elif matrix:
            for status in ("UNKNOWN", "BLOCKED", "READY"):
                assert status in text
        else:
            assert "Permission preflight has not completed" in text
        assert plan.breadcrumb() == "plan"
        assert "Escape returns to setup" in plan.guide().action
        await pilot.press("escape")
        assert app.screen is screen

    drive(scenario)


@pytest.mark.parametrize("read_error", [False, True])
def test_switching_subscription_discards_scoped_selections_clients_catalog_and_store(monkeypatch, read_error):
    from azure.cli.core import get_default_cli
    from azure.cli.core._profile import Profile
    from azure.cli.core.commands.client_factory import get_subscription_id

    cli_ctx = get_default_cli()
    subscriptions = [
        {"id": "sub-a", "name": "Subscription A", "isDefault": True},
        {"id": "sub-b", "name": "Subscription B", "isDefault": False},
    ]
    monkeypatch.setattr(Profile, "load_cached_subscriptions", lambda self: subscriptions)
    monkeypatch.setitem(cli_ctx.data, "subscription_id", "sub-a")
    monkeypatch.setattr(rbac, "permissions_at_scope", Mock(return_value={}))
    started, release, delivered = threading.Event(), threading.Event(), threading.Event()
    providers = []

    class NamespaceProvider:
        def __init__(self, cmd):
            self.subscription = get_subscription_id(cmd.cli_ctx)
            self.calls = 0
            providers.append(self)

        def list(self, **kwargs):
            self.calls += 1
            if self.subscription == "sub-a" and self.calls > 1:
                started.set()
                if not release.wait(15):
                    raise RuntimeError("test did not release A read")
                if read_error:
                    raise RuntimeError("late A failure")
            return [self.show()]

        def show(self, **kwargs):
            return resource(
                f"namespace-{self.subscription}",
                resourceGroup=f"rg-{self.subscription}",
                id=f"/subscriptions/{self.subscription}/resourceGroups/rg-{self.subscription}/providers/"
                   f"Microsoft.DeviceRegistry/namespaces/namespace-{self.subscription}",
            )

    monkeypatch.setattr("azext_iot.adr.providers.namespace.NamespaceProvider", NamespaceProvider)
    catalog_factory = Mock(side_effect=lambda cmd: SimpleNamespace(
        cmd=cmd, clear=Mock(), resource_groups=Mock(return_value=[]), namespaces=Mock(return_value=[]),
    ))
    monkeypatch.setattr("azext_iot.adr.ui.app.ResourceCatalog", catalog_factory)

    async def scenario():
        app = RadrApp(cmd=SimpleNamespace(cli_ctx=cli_ctx), resource_group_name="rg-sub-a",
                      namespace_name="namespace-sub-a", refresh_interval=3600)
        async with app.run_test(size=(140, 50)) as pilot:
            try:
                await settle(app, pilot)
                root = app.screen
                assert root.scope["subscription_id"] == "sub-a"
                old_session = app.session
                original_loaded = root._on_loaded

                def loaded(*args):
                    original_loaded(*args)
                    delivered.set()

                monkeypatch.setattr(root, "_on_loaded", loaded)
                app.open_detail(root.spec, root.selected_payload())
                await pilot.pause()
                app.action_onboard()
                await settle(app, pilot)
                screen = app.screen
                screen.context.update({
                    "create_resource_group": CreateRequest("resource_group", "planned-rg", "planned-rg", "eastus2"),
                    "create_namespace": CreateRequest("namespace", "planned", "rg-sub-a", "eastus2"),
                    "create_dps": CreateRequest("dps", "dps", "rg-sub-a", "eastus2"),
                    "create_hub": CreateRequest("hub", "hub", "rg-sub-a", "eastus2"),
                    "create_su": CreateRequest("su", "updates", "rg-sub-a", "eastus2"),
                    "selected_dps": candidate("old-dps"),
                    "selected_hubs": [candidate("old-hub")],
                    "selected_sus": [candidate("old-su")],
                    "can_grant_roles": True, "location": "westus2",
                })
                old_screens = list(app.screen_stack[1:])
                old_catalog = screen.catalog
                old_namespace = deepcopy(screen.context["namespace"])
                old_signature = screen.context.get("_grant_probe_for")
                root.refresh_rows(force=True)
                assert await asyncio.to_thread(started.wait, 5)
                focus_step(screen, "subscription", [Candidate("Subscription B", "sub-b")])
                screen.action_select()
                await pilot.pause()
                assert app.scope["subscription_id"] == "sub-b"
                await settle(app, pilot)
                fresh = app.screen
                assert isinstance(fresh, OnboardScreen) and fresh is not screen
                assert fresh.session is app.session and fresh.session is not old_session
                assert app.session.scope.subscription_id == cli_ctx.data["subscription_id"] == "sub-b"
                assert app.scope["subscription"] == "Subscription B"
                assert app.scope["resource_group_name"] is app.scope["namespace_name"] is None
                assert all(not old.is_attached and old not in app.screen_stack for old in old_screens)
                assert fresh.catalog is not old_catalog
                assert fresh.active_step().id == "scope"
                assert not fresh._candidates
                assert fresh.context["namespace"] == {}
                for key in ("resource_group_name", "namespace_name", "location", "create_namespace",
                            "create_resource_group", "create_dps", "create_hub", "create_su", "selected_dps",
                            "selected_hubs", "selected_sus", "can_grant_roles", "identity_choices"):
                    assert not fresh.context.get(key)
                assert "Subscription B" in fresh.query_one("#context-bar").text
                # Queued A callbacks, not just still-running requests, must be inert after disposal.
                screen._apply_namespace({"name": "late-a"})
                screen._grant_rights_read(old_signature, {"old-a": {"write": True}}, True)
                screen._show_candidates("subscription", screen._candidate_generation, [candidate("late-a")])
                assert screen.context["namespace"] == old_namespace
                assert screen._candidates != [candidate("late-a")]
                app._apply_resolved_scope(old_session)
                assert app.scope["subscription_id"] == "sub-b"
                assert app.screen is fresh
                release.set()
                assert await asyncio.to_thread(delivered.wait, 5)
                await pilot.pause()
                root._on_load_failed("late A failure")
                assert root.model.error is None
                await pilot.press("escape")
                await settle(app, pilot)
                browse = app.screen
                assert isinstance(browse, BrowseScreen)
                assert browse.scope["subscription_id"] == "sub-b"
                assert browse.selected_payload()["name"] == "namespace-sub-b"
                assert browse.model.total_count == 1
                assert app.store.entry("namespace", app.scope).payloads == [providers[-1].show()]
                await pilot.press("n")
                await settle(app, pilot)
                assert isinstance(app.screen, OnboardScreen)
                assert app.screen.context["subscription_id"] == "sub-b"
                assert app.screen.context["namespace"] == {}
                assert app.screen.context.get("namespace_name") is None
                assert app.screen.context.get("resource_group_name") is None
                assert app.screen.session.provider("namespace").subscription == "sub-b"
                app.screen.context["create_resource_group"] = CreateRequest(
                    "resource_group", "new-b", "new-b", "eastus2")
                assert "/subscriptions/sub-b" in app.screen._permission_requirements()
                assert Profile(cli_ctx=cli_ctx).get_subscription()["id"] == "sub-a"
                assert [provider.subscription for provider in providers] == ["sub-a", "sub-b"]
            finally:
                release.set()

    asyncio.run(scenario())


def test_selecting_an_existing_group_retargets_pending_requests_without_changing_the_snapshot():
    async def scenario(app, pilot, screen):
        request = CreateRequest("dps", "planned-dps", "rg-test", "eastus2")
        screen.context["create_dps"] = request
        screen.context["create_resource_group"] = CreateRequest("resource_group", "new-rg", "new-rg", "eastus2")
        existing = Candidate("existing-rg", "/subscriptions/sub-1/resourceGroups/existing-rg", location="westus2")
        focus_step(screen, "scope", [existing])
        screen.action_select()
        await pilot.pause()
        assert screen.context["resource_group_name"] == request.resource_group_name == "existing-rg"
        assert screen.context["location"] == "westus2"
        assert "create_resource_group" not in screen.context
        assert screen.context["namespace"] == resource()
        assert screen.active_step().id != "scope"

    drive(scenario)


@pytest.mark.parametrize("kind", ["namespace", "dps", "hub", "su"])
def test_selecting_existing_resource_requires_identity_and_replaces_its_pending_creation(kind):
    async def scenario(app, pilot, screen):
        chosen = candidate(f"selected-{kind}")
        screen.context[f"create_{kind}"] = CreateRequest(kind, f"planned-{kind}", "rg-test", "eastus2")
        focus_step(screen, kind, [chosen])
        before = deepcopy(chosen.raw)
        screen.action_select()
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog)
        assert app.screen.resource_label == chosen.name
        assert ("namespace uses to call" if kind == "namespace" else "uses to call the namespace") in app.screen.purpose
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert f"create_{kind}" not in screen.context
        assert has_choice(screen.context, kind, chosen.resource_id)
        assert get_choice(screen.context, kind, chosen.resource_id) == system_choice()
        if kind == "namespace":
            assert screen.context["namespace"] == chosen.raw
            assert screen.context["namespace_name"] == chosen.name
            assert screen._state_loaded
        elif kind == "dps":
            assert screen.context["selected_dps"] is chosen
        else:
            key = "selected_hubs" if kind == "hub" else "selected_sus"
            assert screen.context[key] == [chosen]
        assert chosen.raw == before
        if kind == "hub":
            assert screen.active_step().id == "hub"
            assert "[selected]" in str(screen.query_one("#candidates", DataTable).get_row_at(0)[0])
            screen.action_toggle_multi()
            assert not screen.context["selected_hubs"]
            assert not has_choice(screen.context, kind, chosen.resource_id)

    drive(scenario)


@pytest.mark.parametrize("kind", ["namespace", "dps", "hub", "su"])
def test_identity_shortcut_on_unselected_resource_adds_it_only_after_a_choice(kind):
    async def scenario(app, pilot, screen):
        chosen = candidate(f"configured-{kind}")
        focus_step(screen, kind, [chosen])
        before = deepcopy(screen.context)
        screen.action_configure_identity()
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog)
        await pilot.press("escape")
        assert screen.context == before
        screen.action_configure_identity()
        await pilot.pause()
        app.screen.query_one("#identity-new", Button).press()
        await pilot.pause()
        app.screen.query_one("#identity-name", Input).value = "shared-mi"
        app.screen.query_one("#identity-new-confirm", Button).press()
        await pilot.pause()
        choice = get_choice(screen.context, kind, chosen.resource_id)
        assert choice.is_user_assigned and choice.create_uami
        assert choice.uami_name == "shared-mi"
        assert screen._identity_indicator(kind, chosen.resource_id) == "UAMI shared-mi"
        if kind == "hub":
            assert screen.context["selected_hubs"] == [chosen]
            screen._accept_candidate_identity(kind, chosen, choice)
            assert screen.context["selected_hubs"] == [chosen], "An identity edit must not duplicate a link target"

    drive(scenario)


def test_software_updates_selection_clears_previous_identity_and_can_be_toggled_off():
    async def scenario(app, pilot, screen):
        old, new = candidate("old-su"), candidate("new-su")
        screen.context["selected_sus"] = [old]
        set_choice(screen.context, "su", system_choice(), old.resource_id)
        focus_step(screen, "su", [new])
        screen.action_select()
        await pilot.pause()
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert screen.context["selected_sus"] == [new]
        assert not has_choice(screen.context, "su", old.resource_id)
        assert has_choice(screen.context, "su", new.resource_id)
        focus_step(screen, "su", [new])
        screen.action_select()
        assert screen.context["selected_sus"] == []
        assert not has_choice(screen.context, "su", new.resource_id)
        assert "removed Software Updates selection new-su" in rendered(screen, "#flash-line")

    drive(scenario)


def test_existing_update_link_rejects_new_target_and_creation_without_losing_the_current_choice():
    async def scenario(app, pilot, screen):
        old, new = candidate("linked-su"), candidate("different-su")
        screen.context["namespace"]["properties"]["updating"] = {"endpoints": {"updates": {"resourceId": old.resource_id}}}
        focus_step(screen, "su", [new])
        before = deepcopy(screen.context)
        screen.action_select()
        assert app.screen is screen
        assert "already has a Software Updates instance" in rendered(screen, "#flash-line")
        screen._accept_candidate_identity("su", new, system_choice())
        assert screen.context == before
        request = CreateRequest("su", "new-su", "rg-test", "eastus2")
        screen._accept_create("su", "create_su", request)
        assert screen.context == before
        assert "already has a Software Updates instance" in rendered(screen, "#flash-line")

    drive(scenario)


@pytest.mark.parametrize("with_raw", [False, True])
def test_candidate_json_is_read_only_and_falls_back_to_summary_fields(with_raw):
    async def scenario(app, pilot, screen):
        chosen = candidate()
        if not with_raw:
            chosen.raw = None
        focus_step(screen, "hub", [chosen])
        before = deepcopy(screen.context)
        screen.action_show_json()
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        expected = chosen.raw if with_raw else {
            "name": chosen.name, "id": chosen.resource_id, "resourceGroup": chosen.resource_group,
            "location": chosen.location,
        }
        assert app.screen.payload == expected
        assert screen.context == before
        await pilot.press("escape")
        assert app.screen is screen
        assert screen._selected_candidate() is chosen

    drive(scenario)


def test_unavailable_actions_and_ineligible_rows_explain_why_without_mutation():
    async def scenario(app, pilot, screen):
        focus_step(screen, "subscription")
        before = deepcopy(screen.context)
        screen.action_create_new()
        assert "nothing to create" in rendered(screen, "#flash-line")
        screen.action_configure_identity()
        assert "identity is configured on namespace and link resources" in rendered(screen, "#flash-line")
        screen.action_select()
        screen.action_toggle_multi()
        screen.action_show_json()
        assert "move to a resource row" in rendered(screen, "#flash-line")
        focus_step(screen, "hub")
        screen.action_configure_identity()
        assert "highlight a resource first" in rendered(screen, "#flash-line")
        denied = candidate(verdict=INELIGIBLE, reason="Standard Hub required")
        focus_step(screen, "hub", [denied])
        screen.action_select()
        assert "cannot be used: Standard Hub required" in rendered(screen, "#flash-line")
        assert screen.context == before
        table = screen.query_one("#candidates", DataTable)
        assert str(table.get_row_at(0)[0]) == denied.name
        assert table.get_row_at(0)[0].style.startswith("bold")

    drive(scenario)


def test_missing_identity_names_the_first_unconfigured_target_in_link_order():
    screen = make_screen()
    for kind, key, label in (("dps", "selected_dps", "DPS"), ("hub", "selected_hubs", "Hub"),
                             ("su", "selected_sus", "Update Instance")):
        chosen = candidate(f"selected-{kind}")
        screen.context[key] = chosen if kind == "dps" else [chosen]
        assert screen._missing_identity_choice() == f"{label} '{chosen.name}'"
        set_choice(screen.context, kind, system_choice(), chosen.resource_id)
        assert screen._missing_identity_choice() is None
    choice = IdentityChoice(USER_ASSIGNED, "/identities/fallback-name")
    set_choice(screen.context, "namespace", choice)
    assert screen._identity_indicator("namespace") == "UAMI fallback-name"


@pytest.mark.parametrize("raises", [False, True])
def test_initial_namespace_reload_reads_live_state_and_recovers_from_a_failed_show(monkeypatch, raises):
    payload = resource()
    show = Mock(return_value=payload, side_effect=RuntimeError("namespace not found") if raises else None)
    session = SimpleNamespace(provider=Mock(return_value=SimpleNamespace(show=show)), call=lambda fn, **kw: fn(**kw))
    monkeypatch.setattr(rbac, "permissions_at_scope", Mock(return_value={"write": True}))
    screen = OnboardScreen(session, {"subscription_id": "sub-1", "resource_group_name": "rg-test", "namespace_name": "factory"})
    assert not screen._state_loaded

    async def scenario(app, pilot, onboard):
        show.assert_called_once_with(namespace_name="factory", resource_group_name="rg-test")
        assert onboard._state_loaded
        assert onboard.context["namespace"] == ({} if raises else payload)
        assert "Loading setup" not in rendered(onboard, "#step-heading")
        if not raises:
            assert get_choice(onboard.context, "namespace") == system_choice()
        onboard.catalog = SimpleNamespace(clear=Mock(), provisioning_services=Mock(return_value=[]),
                                          namespaces=Mock(return_value=[]))
        onboard.action_reload()
        assert not onboard._state_loaded
        assert "Reading the namespace" in rendered(onboard, "#step-body")
        await settle(app, pilot)
        assert show.call_count == 2
        onboard.catalog.clear.assert_called_once_with()
        assert onboard._state_loaded

    drive(scenario, screen)


@pytest.mark.parametrize(
    "kind, fields",
    [("namespace", ["create-name", "create-location", "create-tags"]),
     ("dps", ["create-name", "create-location", "create-capacity"]),
     ("hub", ["create-name", "create-location", "create-sku", "create-capacity"])],
)
def test_form_arrow_navigation_includes_only_visible_fields_and_clamps_at_actions(kind, fields):
    async def scenario(app, pilot, screen):
        focus_step(screen, kind)
        screen.action_create_new()
        await pilot.pause()
        screen.action_focus_steps()
        await pilot.pause()
        screen.action_focus_details()
        await pilot.pause()
        assert app.focused.id == "create-name"
        await pilot.press("up")
        assert app.focused.id == "create-name"
        controls = fields + ["create-cancel", "create-plan", "create-confirm"]
        for control in controls[1:]:
            await pilot.press("down")
            assert app.focused.id == control
        await pilot.press("down")
        assert app.focused.id == "create-confirm"
        await pilot.press("up")
        assert app.focused.id == "create-plan"
        screen.action_focus_steps()
        await pilot.pause()
        screen.action_focus_form_control(1)
        await pilot.pause()
        assert app.focused.id == "create-name"
        screen.query_one("#create-cancel", Button).press()
        await pilot.pause()
        assert not screen.query_one("#create-form").display
        assert app.focused.id == "candidates"
        assert f"create_{kind}" not in screen.context

    drive(scenario)


def test_review_pane_and_rail_navigation_preserve_selection_and_ignore_invalid_step_numbers():
    async def scenario(app, pilot, screen):
        screen.catalog = SimpleNamespace()
        screen._focus_step = "review"
        screen._candidates_for = None
        screen._reload_candidates()
        screen.refresh_view()
        screen.action_focus_details()
        await pilot.pause()
        assert app.focused.id == "work-pane"
        await pilot.press("left")
        assert app.focused.id == "step-list"
        await pilot.press("right")
        assert app.focused.id == "work-pane"
        screen.action_focus_form_control(1)
        await pilot.pause()
        assert app.focused.id == "work-pane"
        for key in ("invalid", "9"):
            app.last_key_pressed = key
            screen.action_goto_step()
            assert screen.active_step().id == "review"
        screen.catalog = None
        app.last_key_pressed = "3"
        screen.action_goto_step()
        await pilot.pause()
        assert screen.active_step().id == "namespace"
        assert "step 3: Namespace" in rendered(screen, "#flash-line")
        rail = screen.query_one("#step-list", ListView)
        rail.focus()
        await pilot.pause()
        rail.index = None
        await pilot.pause()
        current = screen.active_step().id
        screen.on_list_view_highlighted(ListView.Highlighted(rail, None))
        assert screen.active_step().id == current
        assert screen.context["namespace"] == resource()

    drive(scenario)


@pytest.mark.parametrize("checking, ready, message", [
    (True, None, "checking resource-write access"),
    (False, False, "Resource-write access is missing"),
    (False, True, "Existing inherited grants need no assignment-write access"),
])
def test_permissions_detail_distinguishes_pending_denied_and_base_role_preflight(checking, ready, message):
    async def scenario(app, pilot, screen):
        screen.context["permission_checking"] = checking
        screen.context["can_write_resources"] = ready
        focus_step(screen, "permissions")
        body = rendered(screen, "#step-body")
        assert "Device Update Administrator" in body
        assert message in body
        assert message in screen._grant_rights_note()
        assert "command" not in screen.context

    drive(scenario)


def test_complete_flow_has_a_clear_heading_and_stale_actions_do_not_change_the_plan():
    async def scenario(app, pilot, screen):
        screen.flow = Flow([], screen.context)
        screen._focus_step = None
        screen.refresh_view()
        await pilot.pause()
        assert screen.active_step() is None
        assert "Setup complete" in rendered(screen, "#step-heading")
        assert "Connectivity is configured" in rendered(screen, "#step-body")
        assert rendered(screen, "#command-hint") == ""
        before = deepcopy(screen.context)
        screen._submit_form()
        await pilot.pause()
        assert app.focused.id == "work-pane"
        assert not screen.query_one("#create-form").display
        screen.action_done_step()
        screen.action_select()
        screen.action_focus_form_control(1)
        screen._load_candidates("hub", 0)  # A worker scheduled before its catalog was removed.
        screen.catalog = SimpleNamespace()
        screen._reload_candidates()
        screen._show_candidates("hub", 0, [candidate()])
        assert not screen._candidates
        assert screen.context == before
        assert screen.flow.build_plan() == []

    drive(scenario)


def test_repainting_a_stale_cursor_keeps_selected_identities_and_all_rail_choices(monkeypatch):
    async def scenario(app, pilot, screen):
        chosen = [candidate(f"hub-{index}") for index in range(12)]
        screen.context["selected_hubs"] = chosen
        screen.context["selected_dps"] = candidate("selected-dps")
        set_choice(screen.context, "dps", system_choice(), screen.context["selected_dps"].resource_id)
        set_choice(screen.context, "hub", system_choice(), chosen[0].resource_id)
        focus_step(screen, "hub", chosen)
        await pilot.pause()
        table = screen.query_one("#candidates", DataTable)
        assert table.row_count == 12
        assert screen._chosen_lines("hub")[-1] == "and 2 more"
        assert "hub-0 · SAMI" in screen._chosen_lines("hub")
        assert "hub-1 · choose identity" in screen._chosen_lines("hub")
        assert "choose identity" in str(table.get_row_at(1)[3])
        before = deepcopy(screen.context)
        cursor = Mock(side_effect=RuntimeError("cursor invalidated by row removal"))
        monkeypatch.setattr(table, "coordinate_to_cell_key", cursor)
        screen._paint_candidates()
        cursor.assert_called_once()
        assert table.row_count == 12
        assert screen.context == before
        assert all(str(table.get_row_at(index)[0]).startswith("[selected]") for index in range(12))
        assert screen._is_chosen(screen.context["selected_dps"])

    drive(scenario)


def test_auto_advance_survives_a_detached_candidate_focus_target(monkeypatch):
    async def scenario(app, pilot, screen):
        focus_step(screen, "scope")
        table = screen.query_one("#candidates", DataTable)
        focus = Mock(side_effect=RuntimeError("candidate table detached"))
        monkeypatch.setattr(table, "focus", focus)
        screen._advance("scope accepted")
        assert screen.active_step().id == "dps"
        assert "scope accepted" in rendered(screen, "#flash-line")
        focus.assert_called_once_with()
        assert screen.context["resource_group_name"] == "rg-test"

    drive(scenario)


def test_hub_done_requires_a_choice_and_identity_then_advances_with_the_count():
    async def scenario(app, pilot, screen):
        dps = candidate("selected-dps", "Microsoft.Devices/provisioningServices")
        screen.context["selected_dps"] = dps
        set_choice(screen.context, "dps", system_choice(), dps.resource_id)
        focus_step(screen, "hub")
        screen.action_done_step()
        assert screen.active_step().id == "hub"
        assert "select at least one IoT Hub" in rendered(screen, "#flash-line")
        chosen = candidate()
        screen.context["selected_hubs"] = [chosen]
        screen.action_done_step()
        assert screen.active_step().id == "hub"
        assert "choose an identity for hub-test" in rendered(screen, "#flash-line")
        set_choice(screen.context, "hub", system_choice(), chosen.resource_id)
        screen.action_done_step()
        assert screen.active_step().id == "su"
        assert "1 IoT Hub(s) will be linked" in rendered(screen, "#flash-line")
        screen.action_done_step()
        assert screen.active_step().id == "review"
        assert screen.context["selected_hubs"] == [chosen]

    drive(scenario)


def test_review_enter_on_a_remaining_row_obeys_the_same_read_only_apply_guard():
    async def scenario(app, pilot, screen):
        focus_step(screen, "review", [candidate()])
        app.read_only = True
        screen.action_select()
        assert app.screen is screen
        assert "read-only session: apply is disabled" in rendered(screen, "#flash-line")
        assert not screen.context.get("selected_hubs")

    drive(scenario)


def test_candidate_row_event_chooses_the_resource_but_unrelated_tables_are_ignored():
    async def scenario(app, pilot, screen):
        chosen = candidate("row-dps")
        focus_step(screen, "dps", [chosen])
        screen.on_data_table_row_selected(DataTable.RowSelected(DataTable(id="other"), 0, chosen.resource_id))
        assert app.screen is screen
        table = screen.query_one("#candidates", DataTable)
        screen.on_data_table_row_selected(DataTable.RowSelected(table, 0, chosen.resource_id))
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog)
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert screen.context["selected_dps"] is chosen

    drive(scenario)


def test_rail_repaint_marks_new_rows_even_while_old_rows_are_pending_removal():
    async def scenario(app, pilot, screen):
        rail = screen.query_one("#step-list", ListView)
        steps = screen.flow.visible_steps()
        old_rows = tuple(rail.children)
        screen._focus_step = "hub"
        screen._render_rail()
        # Textual removes old rows asynchronously; repainting must not count them as
        # the new rail, or it strips the selected class from the incoming Hub row.
        incoming_rows = tuple(rail.children)[-len(steps):]
        assert all(row not in old_rows for row in incoming_rows)
        index = next(index for index, step in enumerate(steps) if step.id == "hub")
        assert incoming_rows[index].has_class("selected-step")
        assert sum(row.has_class("selected-step") for row in incoming_rows) == 1
        await pilot.pause()
        assert len(rail.children) == len(steps)
        assert rail.children[index].has_class("selected-step")
        assert screen.active_step().id == "hub"
        assert not rail.has_focus

    drive(scenario)


def test_creating_dps_replaces_selected_target_identity_and_final_verification_expectation(monkeypatch):
    client = Mock()
    factory = Mock(return_value=SimpleNamespace(iot_dps_resource=client))
    monkeypatch.setattr("azext_iot._factory.iot_service_provisioning_factory", factory)

    async def scenario(app, pilot, screen):
        old = candidate("selected-old", "Microsoft.Devices/provisioningServices")
        old_identity = IdentityChoice(
            USER_ASSIGNED, "/subscriptions/sub-1/resourceGroups/rg-test/providers/"
                           "Microsoft.ManagedIdentity/userAssignedIdentities/old-mi",
            create_uami=True, uami_resource_group="rg-test", uami_location="eastus2",
        )
        screen._accept_candidate_identity("dps", old, old_identity)
        assert old.resource_id in next(item.command for item in screen.flow.build_plan() if item.key == "dps")
        focus_step(screen, "dps")
        screen.action_create_new()
        screen.query_one("#create-name", Input).value = "created-new"
        screen.query_one("#create-confirm", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, IdentityChoiceDialog)
        app.screen.query_one("#identity-sami", Button).press()
        await pilot.pause()

        request = screen.context["create_dps"]
        target_id = request.arm_id("sub-1")
        assert screen.context.get("selected_dps") is None
        assert not has_choice(screen.context, "dps", old.resource_id)
        assert [target.resource_id for target in link_targets(screen.context, "dps")] == [target_id]
        plan = screen.flow.build_plan()
        assert all(old.resource_id not in item.command and "old-mi" not in item.command for item in plan)
        create = next(item for item in plan if item.key == "dps-create")
        link = next(item for item in plan if item.key == "dps")
        verify = next(item for item in plan if item.key == "verify-readiness")
        session = Session(None)
        linker = SimpleNamespace(dps_add=Mock(return_value=None))
        live = resource(properties={
            "outboundIdentity": {"type": "SystemAssigned"},
            "provisioning": {"endpoints": {
                "dps": {"resourceId": target_id, "linkingState": "Succeeded"},
            }},
        })
        session._providers.update(link=linker, namespace=SimpleNamespace(show=Mock(return_value=live)))
        catalog = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=object()))
        screen.context["_catalog"] = catalog
        create.invoke(session, screen.context)
        factory.assert_called_once_with(catalog.cmd.cli_ctx)
        assert client.begin_create_or_update.call_args.kwargs["provisioning_service_name"] == "created-new"
        link.invoke(session, screen.context)
        linker.dps_add.assert_called_once_with(
            endpoint_name="dps", namespace_name="factory", resource_group_name="rg-test",
            mi_system_assigned=True, mi_user_assigned=None, no_wait=True, dps_resource_id=target_id,
        )
        notify = Mock()
        assert verify.verify(session, screen.context, notify) == live
        notify.assert_called_once_with("1 endpoint(s) ready")

    drive(scenario)


def test_new_namespace_replaces_live_snapshot_and_scoped_plan_even_if_old_reload_finishes(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(rbac, "permissions_at_scope", Mock(return_value={}))

    async def scenario(app, pilot, screen):
        old_snapshot = deepcopy(screen.context["namespace"])
        old_snapshot["properties"]["outboundIdentity"] = {
            "type": "UserAssigned", "userAssignedIdentity": "/identities/old-owner",
        }
        old_snapshot["properties"]["provisioning"] = {"endpoints": {
            "old-dps-endpoint": {"resourceId": candidate("old-dps").resource_id, "linkingState": "Succeeded"},
        }}
        screen.context["namespace"] = old_snapshot
        set_choice(screen.context, "namespace", IdentityChoice(USER_ASSIGNED, "/identities/old-owner"))
        for kind, key in (("dps", "selected_dps"), ("hub", "selected_hubs"), ("su", "selected_sus")):
            selected = candidate(f"old-{kind}")
            screen.context[key] = selected if kind == "dps" else [selected]
            set_choice(screen.context, kind, system_choice(), selected.resource_id)
            screen.context[f"{kind}_endpoint_name"] = f"old-{kind}-endpoint"
        screen.context["create_hub"] = CreateRequest("hub", "old-planned-hub", "rg-test", "eastus2")
        screen.context.update(can_grant_roles=True, can_write_resources=True,
                              permission_matrix={"/old-namespace": {"write": True}})
        screen._candidates_for = "dps"
        screen._candidates = [candidate("old-picker-dps")]
        old_candidate_generation = screen._candidate_generation
        assert has_namespace(screen.context)

        def reload_old(**kwargs):
            started.set()
            if not release.wait(15):
                raise RuntimeError("test did not release old namespace reload")
            return old_snapshot

        session = Session(None)
        namespace_provider = SimpleNamespace(show=Mock(side_effect=reload_old), create=Mock(return_value=None))
        session._providers["namespace"] = namespace_provider
        screen.session = session
        screen.run_worker(screen._reload_namespace, thread=True)
        try:
            assert await asyncio.to_thread(started.wait, 5)
            focus_step(screen, "scope", [Candidate("new-rg", "/subscriptions/sub-1/resourceGroups/new-rg")])
            screen.action_select()
            focus_step(screen, "namespace")
            screen.action_create_new()
            screen.query_one("#create-name", Input).value = "new-factory"
            screen.query_one("#create-location", Input).value = "westus2"
            screen.query_one("#create-confirm", Button).press()
            await pilot.pause()
            assert isinstance(app.screen, IdentityChoiceDialog)
            app.screen.query_one("#identity-sami", Button).press()
            await pilot.pause()
        finally:
            release.set()
        await settle(app, pilot)

        assert not has_namespace(screen.context)
        screen._show_candidates("dps", old_candidate_generation, [candidate("late-old-picker")])
        assert not screen._candidates
        assert screen.context["namespace_name"] == "new-factory"
        assert screen.context["resource_group_name"] == "new-rg"
        assert screen.context["location"] == "westus2"
        assert not screen.context.get("can_grant_roles")
        assert "/old-namespace" not in screen.context.get("permission_matrix", {})
        for kind, key in (("dps", "selected_dps"), ("hub", "selected_hubs"), ("su", "selected_sus")):
            assert not screen.context.get(key)
            assert not screen.context.get(f"create_{kind}")
            assert not screen.context.get(f"{kind}_endpoint_name")
            assert not link_targets(screen.context, kind)
        assert all("old" not in str(choice) for choice in screen.context.get("identity_choices", {}).values())
        namespace_step = next(step for step in screen.flow.steps if step.id == "namespace")
        assert not namespace_step.is_satisfied(screen.context)
        assert namespace_step.is_planned(screen.context)
        plan = screen.flow.build_plan()
        creation = next(item for item in plan if item.key == "namespace")
        assert creation.action == "create"
        assert "new-factory" in creation.command and "new-rg" in creation.command
        assert "--outbound-system-assigned-mi" in creation.command
        namespace_provider.show.reset_mock()
        next(item for item in plan if item.key == "preflight").invoke(session, screen.context)
        namespace_provider.show.assert_not_called()
        creation.invoke(session, screen.context)
        assert namespace_provider.create.call_args.kwargs["namespace_name"] == "new-factory"
        assert namespace_provider.create.call_args.kwargs["resource_group_name"] == "new-rg"
        assert old_snapshot["name"] == "factory"
        assert old_snapshot["properties"]["outboundIdentity"]["userAssignedIdentity"] == "/identities/old-owner"

    drive(scenario)


def test_editing_same_planned_namespace_keeps_targets_but_switching_namespace_discards_them():
    async def scenario(app, pilot, screen):
        identity = IdentityChoice(USER_ASSIGNED, "/identities/planned-owner")
        request = CreateRequest("namespace", "planned", "rg-test", "eastus2", identity=identity)
        screen._accept_create("namespace", "create_namespace", request)
        dps = CreateRequest("dps", "planned-dps", "rg-test", "eastus2")
        screen._accept_create("dps", "create_dps", dps)
        hub = candidate("selected-hub", "Microsoft.Devices/IotHubs")
        screen._accept_candidate_identity("hub", hub, system_choice())
        edited = CreateRequest("namespace", "planned", "rg-test", "eastus2",
                               identity=identity, tags={"owner": "team"})
        screen._accept_create("namespace", "create_namespace", edited)
        await pilot.pause()
        assert screen.context["create_dps"] is dps
        assert screen.context["selected_hubs"] == [hub]
        assert get_choice(screen.context, "namespace") is identity
        plan = screen.flow.build_plan()
        namespace = next(item for item in plan if item.key == "namespace")
        assert "--outbound-user-assigned-mi /identities/planned-owner" in namespace.command
        assert "--tags owner=team" in namespace.command
        assert any(item.key == "dps-create" for item in plan)
        assert any(hub.resource_id in item.command for item in plan)
        screen.action_show_plan()
        await pilot.pause()
        assert "planned-owner" in rendered(app.screen, "#plan-body")
        await pilot.press("escape")

        existing = candidate("another-namespace", "Microsoft.DeviceRegistry/namespaces")
        screen._accept_candidate_identity("namespace", existing, system_choice())
        await pilot.pause()
        assert screen.context["namespace"] == existing.raw
        assert screen.context.get("create_namespace") is None
        assert screen.context.get("create_dps") is None
        assert screen.context.get("selected_hubs") is None
        assert not has_choice(screen.context, "hub", hub.resource_id)
        assert get_choice(screen.context, "namespace") == system_choice()
        updated = screen.flow.build_plan()
        assert next(item for item in updated if item.key == "namespace").action == "exists"
        assert all("planned-owner" not in item.command and "planned-dps" not in item.command for item in updated)

    drive(scenario)


def test_confirmation_clipboard_and_plan_commands_match_subscription_pinned_export(monkeypatch):
    async def scenario(app, pilot, screen):
        screen.context["subscription_id"] = "reviewed-b"
        commands = [
            "az group create -n new-group -l eastus2",
            "az identity show -n foreign -g rg --subscription foreign-c",
            "az identity show -n another -g rg --subscription=foreign-d",
            "# Verify the reviewed namespace topology",
        ]
        invoke = Mock()
        review_flow(screen, [PlanItem(str(index), f"Operation {index}", command, invoke=invoke)
                             for index, command in enumerate(commands)])
        exported = [line for line in screen.flow.script().splitlines() if line.startswith("az ")]
        assert shlex.split(exported[0])[-2:] == ["--subscription", "reviewed-b"]
        assert exported[1:3] == commands[1:3]
        copy = Mock()
        monkeypatch.setattr(app, "copy_to_clipboard", copy)
        screen.action_apply()
        await pilot.pause()
        preview = app.screen
        assert isinstance(preview, CommandPreviewDialog)
        await pilot.press("ctrl+y")
        copied = copy.call_args.args[0]
        assert [line for line in copied.splitlines() if line.startswith("az ")] == exported
        assert commands[-1] in copied
        invoke.assert_not_called()
        await pilot.press("escape")
        assert app.screen is screen
        screen.action_show_plan()
        await pilot.pause()
        assert isinstance(app.screen, PlanDialog)
        details = rendered(app.screen, "#plan-body")
        for command in exported:
            assert command in details
        invoke.assert_not_called()

    drive(scenario)


@pytest.mark.parametrize("exportable_verification", [True, False])
def test_run_setup_clipboard_uses_export_script_with_readiness_and_fail_closed_semantics(
    monkeypatch, exportable_verification,
):
    async def scenario(app, pilot, screen):
        screen.context["subscription_id"] = "reviewed-b"
        invoke, verify = Mock(), Mock()
        wait = "az iot adr ns wait -n factory -g rg-test --custom ready --timeout 60"
        check = ScriptCheck(
            command="az identity show -n foreign -g rg --query id -o tsv --subscription foreign-c",
            expected="/identities/reviewed-identity",
            description="Reviewed identity matches",
        )
        item = PlanItem(
            "setup", "Create then verify readiness",
            command="az group create -n new-group -l eastus2",
            invoke=invoke,
            verify=verify,
            verify_commands=(wait,) if exportable_verification else (),
            verify_checks=(check,) if exportable_verification else (),
        )
        review_flow(screen, [item])
        copy = Mock()
        monkeypatch.setattr(app, "copy_to_clipboard", copy)
        screen.action_export()
        exported = copy.call_args.args[0]
        copy.reset_mock()
        screen.action_apply()
        await pilot.pause()
        assert isinstance(app.screen, CommandPreviewDialog)
        assert "1 operation(s) will run in order" in app.screen._note
        await pilot.press("ctrl+y")
        copy.assert_called_once_with(exported)
        copied = copy.call_args.args[0]
        assert copied.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        creation = item.command + " --subscription reviewed-b"
        assert creation in copied
        if exportable_verification:
            assert wait + " --subscription reviewed-b" in copied
            assert f"radar_check=$({check.command})" in copied
            assert copied.index(creation) < copied.index(wait) < copied.index("radar_check=$(")
            assert 'if [ "$radar_check" != /identities/reviewed-identity ]; then' in copied
            assert "Verification failed: Reviewed identity matches" in copied
            assert "\n    exit 1\n" in copied
        else:
            assert "# No executable verification is available for: Create then verify readiness" in copied
            assert copied.index("\nexit 1\n") < copied.index(creation)
        invoke.assert_not_called()
        verify.assert_not_called()
        await pilot.press("escape")
        assert app.screen is screen

    drive(scenario)


@pytest.mark.parametrize("su_ready", [False, True])
def test_namespace_reset_discards_reconciled_repairs_and_rebuilds_reviewed_principal(monkeypatch, su_ready):
    ensure_roles = Mock()
    monkeypatch.setattr("azext_iot.adr.ui.screens.onboard.permissions.ensure_link_roles", ensure_roles)

    async def scenario(app, pilot, screen):
        identity = IdentityChoice(
            USER_ASSIGNED, "/identities/old-su-owner", principal_id="old-su-principal", create_uami=True,
        )
        request = CreateRequest("su", "old-updates", "rg-test", "eastus2", identity=identity)
        screen.context["create_su"] = request
        targets = {
            "dps": candidate("old-dps", "Microsoft.Devices/provisioningServices"),
            "hub": candidate("old-hub", "Microsoft.Devices/IotHubs"),
            "su": candidate("old-updates", "Microsoft.DeviceUpdate/updateInstances"),
        }
        properties = {"outboundIdentity": {"type": "SystemAssigned"}}
        for kind, section, endpoint_type in (
            ("dps", "provisioning", "Microsoft.Devices/provisioningServices"),
            ("hub", "messaging", "Microsoft.Devices/IotHubs"),
            ("su", "updating", "Microsoft.DeviceUpdate/updateInstances"),
        ):
            endpoint = {
                "resourceId": targets[kind].resource_id,
                "endpointType": endpoint_type,
                "linkingState": "Succeeded" if kind == "su" and su_ready else "Pending",
                "inboundCallerIdentity": {"type": "SystemAssigned"},
            }
            if kind == "su":
                endpoint["inboundCallerIdentity"] = {
                    "type": "UserAssigned", "userAssignedIdentity": identity.uami_id,
                }
                if su_ready:
                    endpoint["serviceAddress"] = "https://updates.example.test"
            properties[section] = {"endpoints": {f"old-{kind}-endpoint": endpoint}}
        screen._apply_namespace(resource(properties=properties))
        await pilot.pause()
        assert "create_su" not in screen.context
        assert get_choice(screen.context, "su", request.arm_id("sub-1")).principal_id == "old-su-principal"
        assert bool(screen.context.get("selected_sus")) is not su_ready
        assert [target.resource_id for target in link_targets(screen.context, "dps")] == [targets["dps"].resource_id]
        assert [target.resource_id for target in link_targets(screen.context, "hub")] == [targets["hub"].resource_id]
        old_plan = screen.flow.build_plan()
        old_grant = next(item for item in old_plan if item.key == "grant-preflight")
        old_grant.invoke(None, screen.context)
        assert ensure_roles.call_args.kwargs["reviewed_namespace_principal"] == "principal-factory"

        screen._accept_create(
            "namespace", "create_namespace", CreateRequest("namespace", "new-factory", "rg-test", "eastus2"),
        )
        await pilot.pause()
        for kind in targets:
            assert not link_targets(screen.context, kind)
            assert not has_choice(screen.context, kind, targets[kind].resource_id)
        cleared_plan = screen.flow.build_plan()
        assert not any(item.key == "grant-preflight" for item in cleared_plan)
        assert not any(item.key == "verify-readiness" for item in cleared_plan)

        fresh = CreateRequest("dps", "new-dps", "rg-test", "eastus2")
        screen._accept_create("dps", "create_dps", fresh)
        await pilot.pause()
        new_plan = screen.flow.build_plan()
        new_grant = next(item for item in new_plan if item.key == "grant-preflight")
        assert new_grant is not old_grant
        ensure_roles.reset_mock()
        new_grant.invoke(None, screen.context)
        ensure_roles.assert_called_once()
        assert ensure_roles.call_args.kwargs["reviewed_namespace_principal"] == ""
        assert [(kind, target.resource_id) for kind, target, _choice in ensure_roles.call_args.args[2]] == [
            ("dps", fresh.arm_id("sub-1")),
        ]
        assert all("old-" not in item.command and "principal-factory" not in item.command for item in new_plan)

    drive(scenario)
