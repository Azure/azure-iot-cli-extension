# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Scope picking, scope switching, local search and contextual actions, driven by keys and clicks."""

import asyncio
import threading
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
from rich.color import ColorType
from textual.widgets import DataTable, Input, OptionList

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.ops import OpState
from azext_iot.adr.ui.core.scope import SUBSCRIPTIONS, ScopeCatalog, group_key
from azext_iot.adr.ui.core.session import Session, SessionError
from azext_iot.adr.ui.core.spec import Action, ChildRef, Guide, Registry
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.theme import DARK_THEME, DEFAULT_THEME, HIGH_CONTRAST_THEME, LIGHT_THEME
from azext_iot.adr.ui.widgets.actions import ActionMenu, ReviewDialog
from azext_iot.adr.ui.widgets.chrome import FlashLine
from azext_iot.adr.ui.widgets.minimal import GUTTER
from azext_iot.adr.ui.widgets.scope import GROUP, SUBSCRIPTION, ScopeDialog
from azext_iot.adr.ui.widgets.tray import OperationsScreen
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec
from azext_iot.tests.adr.ui.test_app_coverage_unit import settle

SUB_A = "00000000-0000-4000-8000-00000000000a"
SUB_B = "00000000-0000-4000-8000-00000000000b"
SUB_C = "00000000-0000-4000-8000-00000000000c"
SUBS = [
    {"id": SUB_A, "name": "Contoso Dev", "state": "Enabled", "isDefault": True},
    {"id": SUB_B, "name": "Contoso Prod", "state": "Enabled"},
    {"id": SUB_C, "name": "Fabrikam Lab", "state": "Disabled"},
]


class Denied(Exception):
    status_code = 403


def fixture_groups(sub):
    if sub == SUB_B:
        raise Denied("AuthorizationFailed")
    if sub == SUB_C:
        return []
    return [{"name": "rg-dev", "location": "eastus"}, {"name": "rg-edge", "location": "westus"},
            {"name": "rg-lab", "location": "westus2"}]


def rows_for(scope):
    group = scope.get("resource_group_name") or "all"
    tag = "b" if scope.get("subscription_id") == SUB_B else "a"
    return [make_payload(f"{tag}-{group}-gateway"), make_payload(f"{tag}-{group}-sensor"),
            make_payload(f"{tag}-{group}-camera", state="Failed")]


def counted_catalog(groups=fixture_groups, subs=SUBS):
    calls = []

    def list_groups(sub):
        calls.append(sub)
        return groups(sub)

    catalog = ScopeCatalog(lambda: list(subs), list_groups)
    catalog.group_calls = calls
    return catalog


def nav_app(actions=(), read_only=False, catalog=None, session=None, lister=rows_for, children=(), **extra):
    registry = Registry()
    registry.register(widget_spec(children=children, list=lister, actions=actions, **extra))
    app = RadrApp(registry=registry, resource_group_name="rg-dev", read_only=read_only, refresh_interval=900,
                  catalog=catalog if catalog is not None else counted_catalog(), session=session)
    if session is None:
        app.scope.update(subscription="Contoso Dev", subscription_id=SUB_A)
    return app


def run(app, scenario, size=(100, 30)):
    async def runner():
        async with app.run_test(size=size) as pilot:
            await settle(app, pilot)
            await scenario(app, pilot)
    asyncio.run(runner())


def option_ids(screen):
    options = screen.query_one(OptionList)
    return [str(options.get_option_at_index(index).id) for index in range(options.option_count)]


def highlighted(screen):
    options = screen.query_one(OptionList)
    return str(options.get_option_at_index(options.highlighted).id)


def text_of(screen, selector):
    return str(screen.query_one(selector).render())


def row_names(screen):
    table = screen.query_one("#rows", DataTable)
    return [str(table.get_row_at(index)[1]) for index in range(table.row_count)]


# -- the picker ---------------------------------------------------------------------------------------


def test_header_group_click_opens_the_picker_on_the_current_group_and_typing_never_lists():
    async def scenario(app, pilot):
        root = app.screen
        assert "rg-dev" in text_of(root, "#group-selector") and "\u25be" in text_of(root, "#group-selector")
        assert "Contoso Dev" in text_of(root, "#subscription-selector")
        await pilot.click("#group-selector")
        await settle(app, pilot)
        picker = app.screen
        assert isinstance(picker, ScopeDialog) and picker.mode == GROUP
        assert option_ids(picker) == ["all", "rg:rg-dev", "rg:rg-edge", "rg:rg-lab", "reload"]
        assert highlighted(picker) == "rg:rg-dev", "opens on the current scope"
        assert "current" in str(picker.query_one(OptionList).get_option_at_index(1).prompt)
        assert text_of(picker, "#scope-context") == "in Contoso Dev"
        assert text_of(picker, "#scope-status").startswith("3 resource groups")
        assert app.focused is picker.query_one("#scope-input", Input)
        await pilot.press(*"edg")
        await pilot.pause()
        assert option_ids(picker) == ["rg:rg-edge"] and highlighted(picker) == "rg:rg-edge"
        assert text_of(picker, "#scope-status").startswith("1 of 3 resource groups")
        assert app.catalog.group_calls == [SUB_A], "typing filters the cached list locally"
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, BrowseScreen) and app.screen is not root
        assert len(app.screen_stack) == 2
        assert app.scope["resource_group_name"] == "rg-edge" and app.scope["subscription_id"] == SUB_A
        assert app.screen.scope["resource_group_name"] == "rg-edge"
        assert row_names(app.screen)[0].startswith("a-rg-edge-")
        assert "rg-edge" in text_of(app.screen, "#group-selector")
        assert app.screen.query_one(FlashLine).text == "Now viewing rg-edge \u00b7 Contoso Dev."

    run(nav_app(), scenario)


def test_subscription_tab_by_mouse_then_denied_groups_fall_back_to_a_typed_name():
    async def scenario(app, pilot):
        await pilot.click("#subscription-selector")
        await settle(app, pilot)
        picker = app.screen
        assert picker.mode == SUBSCRIPTION
        assert option_ids(picker) == [f"sub:{SUB_A}", f"sub:{SUB_B}", f"sub:{SUB_C}", "reload"]
        assert highlighted(picker) == f"sub:{SUB_A}"
        first = str(picker.query_one(OptionList).get_option_at_index(1).prompt)
        assert "Contoso Prod" in first and "00000000\u2026" in first
        assert "Disabled" in str(picker.query_one(OptionList).get_option_at_index(2).prompt)
        assert "az defaults stay unchanged" in text_of(picker, "#scope-context")
        await pilot.click("#scope-options", offset=(4, 1))
        await settle(app, pilot)
        assert app.screen is picker and picker.mode == GROUP
        assert app.scope["subscription_id"] == SUB_A, "a subscription alone changes nothing"
        assert "in Contoso Prod \u00b7 not applied yet" == text_of(picker, "#scope-context")
        status = text_of(picker, "#scope-status")
        assert status == "Not authorized to list resource groups; type a name."
        assert option_ids(picker) == ["all", "retry"], "retry is a row: arrows and Enter, no special key"
        await pilot.press(*"rg-prod")
        await pilot.pause()
        assert option_ids(picker) == ["use:rg-prod"]
        assert "typed name" in str(picker.query_one(OptionList).get_option_at_index(0).prompt)
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.scope == {"subscription": "Contoso Prod", "subscription_id": SUB_B,
                             "resource_group_name": "rg-prod", "namespace_name": None}
        assert row_names(app.screen) == ["b-rg-prod-camera", "b-rg-prod-gateway", "b-rg-prod-sensor"]
        assert "Contoso Prod" in text_of(app.screen, "#subscription-selector")

    run(nav_app(), scenario)


def test_tabs_by_key_and_click_empty_and_all_groups_and_escape_changes_nothing():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("at")
        await settle(app, pilot)
        picker = app.screen
        assert picker.mode == GROUP
        await pilot.press("tab")
        assert picker.mode == SUBSCRIPTION and picker.query_one("#tab-subscription").has_class("-active")
        assert [key.label for key in picker.query_one("#dialog-keys").keys][2] == "resource group"
        await pilot.press("shift+tab")
        assert picker.mode == GROUP
        await pilot.click("#tab-subscription")
        await pilot.pause()
        assert picker.mode == SUBSCRIPTION
        picker.action_show_mode(SUBSCRIPTION)
        await pilot.press(*"fab", "enter")
        await settle(app, pilot)
        assert picker.target == (SUB_C, "Fabrikam Lab") and picker.mode == GROUP
        assert text_of(picker, "#scope-status").startswith("No resource groups in this subscription.")
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root and app.scope["subscription_id"] == SUB_A
        assert app.scope["resource_group_name"] == "rg-dev"
        await pilot.click("#group-selector")
        await settle(app, pilot)
        picker = app.screen
        await pilot.press("up", "up")
        assert highlighted(picker) == "reload", "up from the first row wraps to the reload row"
        await pilot.press("down")
        assert highlighted(picker) == "all", "and back"
        options = picker.query_one(OptionList)
        marks = [str(options.get_option_at_index(i).prompt).startswith(GUTTER) for i in range(options.option_count)]
        assert marks == [True, False, False, False, False], "exactly one row carries the selection mark"
        await pilot.click("#dialog-keys", offset=picker.query_one("#dialog-keys").offset_of("select"))
        await settle(app, pilot)
        assert app.scope["resource_group_name"] is None
        assert row_names(app.screen) == ["a-all-camera", "a-all-gateway", "a-all-sensor"]
        assert "all resource groups" in text_of(app.screen, "#group-selector")

    run(nav_app(), scenario)


def test_reload_by_key_and_click_and_failed_listing_retries():
    outcomes = [RuntimeError("socket closed"), None]

    def flaky(_sub):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome
        return [{"name": "rg-dev"}]

    async def scenario(app, pilot):
        await pilot.press("at")
        await settle(app, pilot)
        picker = app.screen
        status = text_of(picker, "#scope-status")
        assert status == "Could not list resource groups: socket closed"
        assert option_ids(picker) == ["all", "retry"]
        await pilot.press("down", "enter")
        await settle(app, pilot)
        assert app.screen is picker and option_ids(picker) == ["all", "rg:rg-dev", "reload"], "keyboard-only retry"
        assert len(app.catalog.group_calls) == 2
        assert text_of(picker, "#scope-status") == "1 resource group"
        await pilot.press("ctrl+r")
        await settle(app, pilot)
        assert len(app.catalog.group_calls) == 3
        await pilot.click("#scope-status")
        await settle(app, pilot)
        assert len(app.catalog.group_calls) == 4
        picker._loading.add(group_key(SUB_A))
        picker._load(group_key(SUB_A))
        picker._paint_status()
        assert text_of(picker, "#scope-status").endswith("reloading\u2026")
        picker._loading.clear()
        await settle(app, pilot)
        assert len(app.catalog.group_calls) == 4, "a key already loading is not requested twice"

    outcomes.extend([None, None])
    run(nav_app(catalog=counted_catalog(groups=flaky)), scenario)


def test_loading_status_and_late_listing_for_an_abandoned_subscription_is_not_shown():
    release = threading.Event()

    def slow(sub):
        if sub == SUB_B:
            release.wait(5)
            return [{"name": "rg-prod-only"}]
        return fixture_groups(sub)

    async def scenario(app, pilot):
        app.catalog.fetch(group_key(SUB_A))
        await pilot.click("#subscription-selector")
        await settle(app, pilot)
        picker = app.screen
        await pilot.press(*"prod", "enter")
        await pilot.pause()
        assert picker.target[0] == SUB_B
        assert text_of(picker, "#scope-status") == "Listing resource groups\u2026 type a name to skip"
        await pilot.press("tab", "enter")
        await pilot.pause()
        assert picker.target[0] == SUB_A and option_ids(picker)[1] == "rg:rg-dev"
        release.set()
        await settle(app, pilot)
        assert "rg:rg-prod-only" not in option_ids(picker), "late listing is cached, never shown"
        assert app.catalog.peek(group_key(SUB_B)).items[0].name == "rg-prod-only"
        async with app.io_slots:
            async with app.io_slots:
                async with app.io_slots:
                    async with app.io_slots:
                        picker._loading.add(group_key(SUB_C))
                        picker.target = (SUB_C, "Fabrikam Lab")
                        picker._paint_status()
                        assert text_of(picker, "#scope-status").startswith("Waiting for a request slot")
        picker._loading.clear()

    release_after = nav_app(catalog=counted_catalog(groups=slow))
    try:
        run(release_after, scenario)
    finally:
        release.set()


def test_no_subscription_resolved_and_unknown_typed_subscription_are_explicit():
    async def scenario(app, pilot):
        app.scope["subscription_id"] = None
        app.scope["subscription"] = None
        await pilot.press("at")
        await settle(app, pilot)
        picker = app.screen
        assert text_of(picker, "#scope-status") == "Choose a subscription first (Tab)."
        assert option_ids(picker) == ["all"]
        picker.action_reload()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is picker, "nothing to apply without a subscription"
        await pilot.press("tab")
        await settle(app, pilot)
        await pilot.press(*"ffffffff-0000-4000-8000-000000000999")
        await pilot.pause()
        assert option_ids(picker) == []
        assert text_of(picker, "#scope-status").startswith("Not in your az login profile.")
        picker.action_choose()
        picker.action_move(1)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)

    run(nav_app(catalog=counted_catalog(subs=SUBS[:1])), scenario)


def test_scope_entry_points_command_bar_header_and_guards():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("colon")
        await pilot.pause()
        bar = app.screen
        assert isinstance(bar, CommandBar)
        assert not [entry for entry in bar._entries if entry[0].startswith("@")], "scope is not duplicated here"
        await pilot.press("escape")
        await pilot.press("at")
        await settle(app, pilot)
        assert isinstance(app.screen, ScopeDialog) and app.screen.mode == GROUP
        app.action_pick_scope()
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, ScopeDialog)]) == 1, "modal: no stacking"
        await pilot.press("escape")
        assert app.screen is root
        app.catalog = None
        app.action_pick_scope()
        assert root.query_one(FlashLine).text == "Scope discovery is unavailable in this session."
        app.switch_scope(None)
        app.switch_scope({"subscription_id": SUB_A, "resource_group_name": "rg-dev"})
        assert root.query_one(FlashLine).text == "Already viewing rg-dev \u00b7 Contoso Dev."
        assert app.screen is root

    run(nav_app(), scenario)


def test_switch_keeps_a_top_level_kind_and_child_lists_return_to_the_root():
    async def scenario(app, pilot):
        other = app.registry.resolve("extra")
        app.push_kind(other, dict(app.scope))
        await settle(app, pilot)
        app.switch_scope({"subscription_id": SUB_A, "subscription": "Contoso Dev", "resource_group_name": "rg-lab"})
        await settle(app, pilot)
        assert app.screen.spec.kind == "extra" and len(app.screen_stack) == 2
        app.open_scoped_child(ChildRef("gadget", "Gadgets"), dict(app.scope, widget_name="x"))
        await settle(app, pilot)
        app.open_detail(app.screen.spec, make_payload("x"))
        await settle(app, pilot)
        assert [type(screen).__name__ for screen in app.screen_stack[1:]] == [
            "BrowseScreen", "BrowseScreen", "DetailScreen"]
        app.switch_scope({"subscription_id": SUB_A, "subscription": "Contoso Dev", "resource_group_name": "rg-dev"})
        await settle(app, pilot)
        # The nearest top-level list survives; the child list and details of the old scope do not.
        assert app.screen.spec.kind == "extra" and len(app.screen_stack) == 2

    registry_extra = [
        widget_spec(kind="extra", children=(), aliases=("ex",), title_plural="Extras", list=rows_for),
        widget_spec(kind="gadget", children=(), aliases=("gd",), parent="widget", list=rows_for),
    ]
    app = nav_app()
    for spec in registry_extra:
        app.registry.register(spec)
    run(app, scenario)


# -- switching is trustworthy ------------------------------------------------------------------------


def test_late_results_of_the_previous_scope_never_reach_the_new_one():
    gate = threading.Event()
    seen = []

    def lister(scope):
        seen.append((scope.get("subscription_id"), scope.get("resource_group_name")))
        if scope.get("resource_group_name") == "rg-dev" and len(seen) > 1:
            gate.wait(5)
            return [make_payload("stale-dev-row")]
        return rows_for(scope)

    async def scenario(app, pilot):
        old = app.screen
        await pilot.press("r")
        await pilot.pause()
        app.switch_scope({"subscription_id": SUB_B, "subscription": "Contoso Prod", "resource_group_name": "rg-prod"})
        await settle(app, pilot)
        gate.set()
        await asyncio.sleep(0.2)
        await settle(app, pilot)
        assert not old.is_attached
        assert row_names(app.screen) == ["b-rg-prod-camera", "b-rg-prod-gateway", "b-rg-prod-sensor"]
        assert ("00000000-0000-4000-8000-00000000000b", "rg-prod") in seen

    try:
        run(nav_app(lister=lister), scenario)
    finally:
        gate.set()


def test_reviews_and_forms_opened_before_a_switch_cannot_run_afterwards():
    invoke = Mock()
    update = Action("update", "Update", invoke=invoke, command="iot adr ns device update")

    async def scenario(app, pilot):
        root = app.screen
        payload = make_payload("a-rg-dev-gateway")
        generation = app._context_generation
        command = app._command_for(root.spec, update, payload["name"], dict(app.scope), payload)
        assert "--subscription 00000000-0000-4000-8000-00000000000a" in command and "-g rg-dev" in command
        app._review_action(root.spec, update, payload, dict(app.scope), generation)
        await pilot.pause()
        assert isinstance(app.screen, ReviewDialog)
        app.switch_scope({"subscription_id": SUB_B, "subscription": "Contoso Prod", "resource_group_name": "rg-prod"})
        await settle(app, pilot)
        assert not any(isinstance(screen, ReviewDialog) for screen in app.screen_stack)
        app._start_action(root.spec, update, payload, dict(root.scope), command, generation)
        app._review_action(root.spec, update, payload, dict(root.scope), generation)
        invoke.assert_not_called()
        assert "invalidated" in app.screen.query_one(FlashLine).text or \
            "Context changed" in app.screen.query_one(FlashLine).text
        app._review_action(root.spec, update, payload, dict(root.scope), generation)
        assert app.screen.query_one(FlashLine).text == "Context changed. Open the action again."

    run(nav_app(actions=(update,)), scenario)


def test_running_operation_keeps_its_session_scope_and_is_labelled_after_a_switch():
    started, release = threading.Event(), threading.Event()
    calls = []

    def invoke(session, scope, payload):
        calls.append((session.scope.subscription_id, scope["subscription_id"], scope["resource_group_name"],
                      payload["name"]))
        started.set()
        release.wait(5)

    update = Action("update", "Update", invoke=invoke, command="iot adr ns device update")
    session = Session(None, "rg-dev")
    session.scope.subscription_id, session.scope.subscription_name = SUB_A, "Contoso Dev"

    async def scenario(app, pilot):
        root = app.screen
        assert app.scope["subscription_id"] == SUB_A
        payload = make_payload("a-rg-dev-gateway")
        scope = dict(root.scope)
        command = app._command_for(root.spec, update, payload["name"], scope, payload)
        app._start_action(root.spec, update, payload, scope, command, app._context_generation)
        for _ in range(250):
            if started.is_set():
                break
            await asyncio.sleep(0.02)
        assert started.is_set()
        app.switch_scope({"subscription_id": SUB_B, "subscription": "Contoso Prod", "resource_group_name": "rg-prod"})
        # Wait for the new list only: the operation stays blocked until released below.
        for _ in range(100):
            await pilot.pause()
            others = [worker for worker in app.workers if not worker.name.startswith("action-")]
            if others:
                await app.workers.wait_for_complete(others)
            elif isinstance(app.screen, BrowseScreen) and app.screen.model.total_count:
                break
        assert app.session is not session and app.session.scope.subscription_id == SUB_B
        assert app.session.read_only is False
        assert app.screen.query_one(FlashLine).text == (
            "Now viewing rg-prod \u00b7 Contoso Prod. 1 running operation(s) keep their original scope (o).")
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, OperationsScreen)
        body = app.screen.query("OperationRow").first().query_one(".op-body")
        assert "in rg-dev \u00b7 Contoso Dev" in str(body.render())
        release.set()
        for _ in range(50):
            await asyncio.sleep(0.02)
            await pilot.pause()
            if not app.tracker.running:
                break
        await settle(app, pilot)
        assert calls == [(SUB_A, SUB_A, "rg-dev", "a-rg-dev-gateway")]
        operation = app.tracker.snapshot()[0]
        assert operation.state is OpState.SUCCEEDED and operation.context == "rg-dev \u00b7 Contoso Dev"
        assert "--subscription 00000000-0000-4000-8000-00000000000a" in operation.command
        assert isinstance(app.screen, OperationsScreen)
        assert app.screen.query_one(FlashLine).text == (
            "Update a-rg-dev-gateway - succeeded in 00:00 (in rg-dev \u00b7 Contoso Dev)")

    try:
        run(nav_app(actions=(update,), session=session), scenario)
    finally:
        release.set()


def test_invoke_boundary_rejects_a_scope_that_is_not_the_sessions_subscription():
    invoke = Mock()
    update = Action("update", "Update", invoke=invoke)
    session = Session(None, "rg-dev")
    session.scope.subscription_id = SUB_A

    async def scenario(app, pilot):
        operation = app.tracker.start("Update", "x", "az ...", ("widget",))
        app._busy.add("key")
        await asyncio.to_thread(app._invoke_action, update, {}, {"subscription_id": SUB_B}, operation, "key", session)
        await settle(app, pilot)
        invoke.assert_not_called()
        assert operation.state is OpState.FAILED and "nothing was sent" in operation.describe()

    run(nav_app(actions=(update,), session=session), scenario)


def test_live_session_switch_rebuilds_the_registry_and_keeps_read_only():
    session = Session(None, "rg-dev", read_only=True)
    session.scope.subscription_id, session.scope.subscription_name = SUB_A, "Contoso Dev"
    built = []

    def build(target):
        built.append(target.scope.subscription_id)
        registry = Registry()
        registry.register(widget_spec(children=(), list=rows_for))
        return registry

    async def scenario(app, pilot):
        app._registry_injected = False
        with patch("azext_iot.adr.ui.app.build_registry", side_effect=build):
            app.switch_scope({"subscription_id": SUB_B, "subscription": "Contoso Prod", "resource_group_name": None})
            await settle(app, pilot)
        assert built == [SUB_B]
        assert app.read_only and app.session.read_only
        assert app.screen.scope["subscription_id"] == SUB_B and app.screen.scope["resource_group_name"] is None
        assert "read-only" in text_of(app.screen, "#operations")

    run(nav_app(session=session, read_only=True), scenario)


def test_scope_catalog_defaults_to_the_cli_profile_for_live_sessions():
    session = Session(None, "rg-dev")
    session.cmd = Mock()
    with patch.object(ScopeCatalog, "for_cli", return_value="catalog") as for_cli:
        app = RadrApp(session=session, registry=Registry())
    for_cli.assert_called_once_with(session.cmd.cli_ctx)
    assert app.catalog == "catalog"


# -- search -----------------------------------------------------------------------------------------


def test_search_is_local_multi_term_and_arrow_keys_move_between_matches():
    lister = Mock(side_effect=rows_for)

    async def scenario(app, pilot):
        root = app.screen
        field = root.query_one("#filter-input", Input)
        assert field.display and field.placeholder == "search widgets"
        assert text_of(root, "#search-mark") == "/ "
        await pilot.press("slash")
        assert app.focused is field and root._filtering
        assert [key.label for key in root.query_one("#keys-line").keys] == ["select match", "done", "clear"]
        await pilot.press(*"a-rg")
        await pilot.pause()
        assert root.model.row_count == 3
        await pilot.press("space", *"!camera")
        await pilot.pause()
        assert root.model.filter_text == "a-rg !camera" and root.model.row_count == 2
        assert root.title_parts()[1] == "2 of 3"
        assert lister.call_count == 1, "no Azure call per keystroke"
        first = root.selected_row_id()
        await pilot.press("down")
        second = root.selected_row_id()
        assert first != second and app.focused is field
        await pilot.press("up")
        assert root.selected_row_id() == first
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.focused is root.query_one("#rows") and not root._filtering
        assert root.model.filter_text == "a-rg !camera" and field.value == "a-rg !camera"
        keys = [key.name for key in root.keys()]
        assert keys == ["open", "focus", "switch", "clear", "quit", "help"], "exit stays visible while searching"
        assert root.query_one("#actions-control").display
        await pilot.press("a")
        await pilot.pause()
        menu = app.screen
        assert isinstance(menu, ActionMenu) and menu.payload["name"] == second
        assert "--name " + second in text_of(menu, "#action-command") or second in text_of(menu, "#action-command")
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert root.model.filter_text == "" and root.model.row_count == 3 and field.value == ""
        assert lister.call_count == 1

    update = Action("update", "Update", invoke=Mock(), command="iot adr ns device update")
    run(nav_app(actions=(update,), lister=lister), scenario)


def test_search_by_mouse_keeps_the_filter_when_leaving_the_field_and_highlights_matches():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.click("#search-mark")
        await pilot.pause()
        field = root.query_one("#filter-input", Input)
        assert app.focused is field
        await pilot.press(*"dev-s")
        await pilot.pause()
        assert text_of(root, "#search-mark") == "/ "
        cell = root.query_one("#rows", DataTable).get_row_at(0)[1]
        assert any(span.style and str(cell)[span.start:span.end] == "dev-s" for span in cell.spans)
        await pilot.press("end", "ctrl+u", *"rg-dev", "space", *"!camera")
        await pilot.pause()
        assert row_names(root) == ["a-rg-dev-gateway", "a-rg-dev-sensor"]
        # A click on a match opens exactly that row; the search survives the round trip.
        await pilot.click("#rows", offset=(4, 2))
        await settle(app, pilot)
        assert isinstance(app.screen, DetailScreen) and app.screen.payload["name"] == "a-rg-dev-sensor"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root and not root._filtering and root.model.filter_text == "rg-dev !camera"
        assert root.selected_payload()["name"] == "a-rg-dev-sensor"
        await pilot.click("#filter-input")
        await pilot.pause()
        assert root._filtering
        await pilot.press("end", "ctrl+u", *"nothing")
        await pilot.pause()
        assert "No widgets match" in str(root.query_one("#empty-line").render())
        assert "actions" not in [key.name for key in root.keys()]
        root.action_move_match(1)
        await pilot.press("escape")
        await pilot.pause()
        assert root.model.row_count == 3
        root._filtering = False
        root.action_move_match(1)
        root.action_submit_filter()

    update = Action("update", "Update", invoke=Mock(), command="iot adr ns device update")
    run(nav_app(actions=(update,)), scenario)


def test_text_entry_never_triggers_app_shortcuts():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("slash", *"aoq@:r", "question_mark")
        await pilot.pause()
        assert app.screen is root and root.model.filter_text == "aoq@:r?"
        await pilot.press("escape", "at")
        await settle(app, pilot)
        picker = app.screen
        await pilot.press(*"aoq:r?/")
        await pilot.pause()
        assert app.screen is picker and picker.query_one(Input).value == "aoq:r?/"

    run(nav_app(actions=(Action("update", "Update", invoke=Mock()),)), scenario)


# -- contextual keys and actions ------------------------------------------------------------------------


def test_actions_follow_row_type_and_state_with_meaningful_notes_only():
    retry = Action("retry", "Retry", invoke=Mock(), applies_to=lambda p: p["properties"]["provisioningState"] == "Failed",
                   unavailable="Only failed widgets can be retried.")
    disable = Action("disable", "Disable", invoke=Mock(), applies_to=lambda p: False)
    add = Action("create", "Create", invoke=Mock(), collection=True, fields=())
    unfinished = Action("todo", "Todo")

    async def scenario(app, pilot):
        root = app.screen
        table = root.query_one("#rows", DataTable)
        table.move_cursor(row=1)
        await pilot.pause()
        assert root.selected_payload()["name"] == "a-rg-dev-gateway"
        await pilot.press("a")
        await pilot.pause()
        menu = app.screen
        assert [action.name for action in menu._actions] == ["create"]
        assert menu._notes == ["Retry: only failed widgets can be retried."]
        assert "Create widget" in str(menu.query_one(OptionList).get_option_at_index(0).prompt)
        assert "rg-dev \u00b7 Contoso Dev" == str(menu.query_one(".dialog-context").render())
        assert not menu.query_one("#action-note").display
        await pilot.press("escape")
        table.move_cursor(row=0)
        await pilot.pause()
        assert root.selected_payload()["name"] == "a-rg-dev-camera"
        await pilot.press("a")
        await pilot.pause()
        assert [action.name for action in app.screen._actions] == ["retry", "create"]
        assert app.screen._notes == []
        await pilot.press("escape")

    run(nav_app(actions=(retry, disable, add, unfinished)), scenario)


def test_no_action_reasons_and_detail_key_line():
    row_only = Action("update", "Update", invoke=Mock(), command="iot adr ns device update")

    async def scenario(app, pilot):
        root = app.screen
        assert app.no_actions_reason(root.spec, None) == "Select a widget first."
        assert app.no_actions_reason(replace(root.spec, actions=()), None) == "No actions for widgets."
        assert not app.has_actions(None, None)
        root.model.set_filter("nothing-matches")
        root._repaint()
        await pilot.pause()
        assert not root.query_one("#actions-control").display, "no control for actions that cannot run"
        await pilot.press("a")
        assert root.query_one(FlashLine).text == "Select a widget first."
        root.model.clear_filter()
        root._repaint()
        await pilot.press("enter")
        await settle(app, pilot)
        detail = app.screen
        assert isinstance(detail, DetailScreen) and detail.query_one("#actions-control").display
        assert app.focused is detail.query_one("#actions-control"), "details start on their first control"
        assert [key.name for key in detail.keys()] == ["focus", "back", "help"]
        app.read_only = True
        detail.paint_controls()
        assert not detail.query_one("#actions-control").display
        assert app.focused is not detail.query_one("#actions-control"), "a hidden control gives up focus"
        app.read_only = False

    run(nav_app(actions=(row_only,)), scenario)


def test_read_only_hides_writes_in_menu_and_still_blocks_execution():
    invoke = Mock()
    write = Action("update", "Update", invoke=invoke, command="iot adr ns device update")
    read = Action("check", "Check", invoke=Mock(), mutation=False)

    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("a")
        await pilot.pause()
        menu = app.screen
        assert [action.name for action in menu._actions] == ["check"]
        assert menu._notes == ["Read-only session: write actions are hidden."]
        assert "read" in str(menu.query_one(OptionList).get_option_at_index(0).prompt)
        await pilot.press("escape")
        app.perform_action(root.spec, write, root.selected_payload(), dict(app.scope))
        app._start_action(root.spec, write, root.selected_payload(), dict(app.scope), "az ...")
        await settle(app, pilot)
        invoke.assert_not_called()

    run(nav_app(actions=(write, read), read_only=True), scenario)


# -- help, theme, detail ---------------------------------------------------------------------------


def test_help_lists_scope_search_theme_and_this_pages_child_keys():
    children = (ChildRef("gadget", "Gadgets", "g"), ChildRef("thing", "Things"))

    async def scenario(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        help_screen = app.screen
        assert isinstance(help_screen, HelpScreen)
        basics = str(help_screen.query_one("#help-basics").render())
        shortcuts = str(help_screen.query_one("#help-shortcuts").render())
        for text in ("next control", "previous control", "open, accept", "press control", "back, close, clear",
                     "quit"):
            assert text in basics
        for text in ("search; !word hides", "resource group", "light / dark", "reload picker list"):
            assert text in shortcuts
        assert str(help_screen.query_one("#help-page-keys").render()) == "this page  g Gadgets"
        await pilot.press("escape")
        app.open_detail(app.screen.spec, make_payload("x"))
        await settle(app, pilot)
        app.action_help()
        await pilot.pause()
        assert str(app.screen.query_one("#help-page-keys").render()) == "this page  g Gadgets"
        await pilot.press("escape")
        await pilot.press("o")
        await pilot.pause()
        app.action_help()
        await pilot.pause()
        assert str(app.screen.query_one("#help-page-keys").render()) == (
            "this page  r re-read  x stop watching  d dismiss finished"
        )
        assert ChromeScreen().help_keys() == [], "pages without letters say nothing extra"

    run(nav_app(children=children), scenario)


def test_ctrl_t_cycles_terminal_dark_light_and_repaints_every_screen():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("enter")
        await settle(app, pilot)
        detail = app.screen
        await pilot.press("y")
        await pilot.pause()
        terminal_accent = app.theme_palette["accent"]
        assert app._theme_name == DEFAULT_THEME and app.ansi_color
        assert app.screen.styles.background.rich_color.is_default
        for strip in app.screen._compositor.render_update(full=True).strips:
            for segment in strip:
                if segment.style and segment.style.color:
                    assert segment.style.color.type != ColorType.TRUECOLOR
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app._theme_name == DARK_THEME and app.theme_palette["accent"] != terminal_accent
        assert detail.show_json
        mark_color = root.query_one("#search-mark").render().spans[0].style.foreground
        assert mark_color.hex.lower() == app.theme_palette["placeholder"]
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app._theme_name == LIGHT_THEME and not app.ansi_color
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app._theme_name == DEFAULT_THEME and app.ansi_color
        assert app.theme_palette["accent"] == terminal_accent
        assert app.screen.styles.background.rich_color.is_default
        app._theme_name = HIGH_CONTRAST_THEME
        await pilot.press("ctrl+t")
        assert "High contrast stays on" in detail.query_one(FlashLine).text

    run(nav_app(), scenario)


def test_detail_read_command_pins_the_viewed_subscription_and_hides_unrunnable_text():
    guide = Guide("Widgets.", runs="az iot adr ns widget list --ns <namespace> -g <resource-group>  \u00b7  read-only")

    async def scenario(app, pilot):
        app.open_detail(app.screen.spec, make_payload("x"))
        await settle(app, pilot)
        detail = app.screen
        detail.scope["namespace_name"] = "ns one"
        assert detail._read_command() == (
            "az iot adr ns widget list --ns 'ns one' -g rg-dev --subscription "
            "00000000-0000-4000-8000-00000000000a  \u00b7  read-only")
        detail.spec = replace(detail.spec, guide=replace(guide, runs="az iot adr ns widget list --job <job>"))
        assert detail._read_command() == ""
        detail.spec = replace(detail.spec, guide=replace(guide, runs="az iot adr ns link dps|hub list"))
        assert detail._read_command() == ""

    run(nav_app(guide=guide), scenario)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
def test_header_segments_and_picker_fit_both_capture_sizes(size):
    async def scenario(app, pilot):
        root = app.screen
        for selector in ("#namespace-selector", "#group-selector", "#subscription-selector", "#operations"):
            region = root.query_one(selector).region
            assert region.width > 0 and region.right <= size[0]
        await pilot.press("at")
        await settle(app, pilot)
        frame = app.screen.query_one(".dialog-frame").region
        assert frame.bottom <= size[1] and frame.right <= size[0]
        assert app.screen.query_one("#dialog-keys").region.bottom <= frame.bottom
        assert app.catalog.peek(SUBSCRIPTIONS) is None, "subscriptions are listed only when that tab opens"

    run(nav_app(), scenario, size=size)


# -- remaining contextual paths ------------------------------------------------------------------------


def test_child_letters_stay_accelerators_off_the_key_line():
    children = (ChildRef("gadget", "Gadgets", "g"),)

    async def scenario(app, pilot):
        root = app.screen
        assert "child-gadget" not in [key.name for key in root.keys()], "child letters are accelerators, in help"
        await pilot.press("g")
        await settle(app, pilot)
        assert app.screen.spec.kind == "gadget" and app.screen.scope["widget_name"] == "a-rg-dev-camera"
        assert "scope" not in [key.name for key in app.screen.keys()], "scope changes from top-level lists"

    app = nav_app(children=children)
    app.registry.register(widget_spec(kind="gadget", children=(), aliases=("gd",), parent="widget", list=rows_for))
    run(app, scenario)


def test_empty_list_search_and_operations_toggle():
    async def scenario(app, pilot):
        root = app.screen
        assert not root.query_one("#rows").display
        assert [key.name for key in root.keys()] == ["focus", "switch", "quit", "help"]
        await pilot.press("slash", *"x", "enter")
        await pilot.pause()
        assert app.focused is None and root.model.filter_text == "x"
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, OperationsScreen)
        await pilot.press("o")
        await pilot.pause()
        assert app.screen is root

    run(nav_app(lister=lambda _scope: []), scenario)


def test_truncated_group_listing_says_so_and_offers_typed_names():
    many = [{"name": f"rg-{index:04d}"} for index in range(1001)]

    async def scenario(app, pilot):
        await pilot.press("at")
        await settle(app, pilot)
        picker = app.screen
        assert "first 1000; type a name for others" in text_of(picker, "#scope-status")
        await pilot.press(*"rg-0001")
        await pilot.pause()
        assert option_ids(picker) == ["rg:rg-0001"], "an exact listed name is not offered twice"
        await pilot.press("end", "ctrl+u", *"rg-9999")
        await pilot.pause()
        assert option_ids(picker) == ["use:rg-9999"]

    run(nav_app(catalog=counted_catalog(groups=lambda _sub: many)), scenario)


def test_unresolved_subscription_is_reported_and_the_picker_still_opens():
    session = Session(None, "rg-dev")
    session.resolve_subscription = Mock(side_effect=SessionError("Could not resolve subscription: no login"))

    async def scenario(app, pilot):
        await settle(app, pilot)
        app.notify.assert_called_once_with("Could not resolve subscription: no login", severity="error")
        assert isinstance(app.screen, BrowseScreen)
        assert "subscription unresolved" in text_of(app.screen, "#subscription-selector")
        await pilot.press("at")
        await settle(app, pilot)
        assert text_of(app.screen, "#scope-status") == "Choose a subscription first (Tab)."

    app = nav_app(session=session)
    app.notify = Mock()
    run(app, scenario)


def test_namespace_read_command_needs_a_group():
    async def scenario(app, pilot):
        detail = DetailScreen(replace(app.registry.roots()[0], kind="namespace"), make_payload("ns"),
                              scope={"subscription_id": SUB_A})
        assert detail._read_command() == ""
        detail.scope["resource_group_name"] = "rg"
        assert detail._read_command() == f"az iot adr ns show -n ns -g rg --subscription {SUB_A}"

    run(nav_app(), scenario)
