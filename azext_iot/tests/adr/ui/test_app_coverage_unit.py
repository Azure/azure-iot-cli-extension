# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Minimal radar navigation, mouse interaction, narrow layout and write safety."""

import asyncio
from dataclasses import replace
import threading
from unittest.mock import Mock

import pytest
from textual.widgets import Button, DataTable, Input, OptionList

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.actions import Field
from azext_iot.adr.ui.core.session import SessionError
from azext_iot.adr.ui.core.spec import Action, ChildRef, Registry
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.widgets.actions import ActionForm, ActionMenu, QuitDialog, ReviewDialog
from azext_iot.adr.ui.widgets.chrome import FlashLine
from azext_iot.adr.ui.widgets.tray import OperationsDialog
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def app_for(action=None, read_only=False):
    registry = Registry()
    registry.register(widget_spec(
        children=(), list=lambda _scope: [make_payload("one"), make_payload("two")],
        actions=(action,) if action else (),
    ))
    app = RadrApp(registry=registry, resource_group_name="rg", read_only=read_only, refresh_interval=900)
    app.scope["subscription_id"] = "sub"
    return app


def run(app, scenario, size=(80, 24)):
    async def runner():
        async with app.run_test(size=size) as pilot:
            await settle(app, pilot)
            await scenario(app, pilot)
    asyncio.run(runner())


def test_requires_explicit_session_or_fixture_registry():
    with pytest.raises(ValueError, match="requires"):
        RadrApp()


def test_mouse_row_details_selectors_search_and_resize():
    async def scenario(app, pilot):
        browse = app.screen
        assert isinstance(browse, BrowseScreen)
        assert browse.query_one(DataTable).has_focus
        await pilot.click("#rows", offset=(4, 2))
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        assert app.screen.resource_name() == "two"
        assert not app.screen.query(DataTable)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is browse
        assert browse.selected_row_id() == "two"
        await pilot.click("#resource-selector")
        await pilot.pause()
        assert isinstance(app.screen, CommandBar)
        await pilot.click("#resource-options", offset=(2, 0))
        await settle(app, pilot)
        assert isinstance(app.screen, BrowseScreen)
        await pilot.press("slash", "o", "n", "e", "enter")
        await pilot.pause()
        assert app.screen.model.row_count == 1
        await pilot.press("escape")
        await pilot.resize_terminal(100, 32)
        await pilot.pause()
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.region.right <= 80
        assert table.size.height >= 10
        await pilot.click("#namespace-selector")
        await settle(app, pilot)
        assert isinstance(app.screen, BrowseScreen)
    run(app_for(), scenario)


def test_keyboard_child_navigation_help_switcher_and_unknown_kind():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        assert app.screen.scope["namespace_name"]
        await pilot.press("g")
        await settle(app, pilot)
        assert app.screen.spec.kind == "group"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#child-group")
        await settle(app, pilot)
        assert app.screen.spec.kind == "group"
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert app.screen is root
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.click("#close")
        await pilot.press("colon", "g", "r", "o", "u", "p", "enter")
        await settle(app, pilot)
        assert app.screen.spec.kind == "group"
        app._run_command("not-a-kind")
        assert "Unknown" in app.screen.query_one(FlashLine).text
        app.open_scoped_child(ChildRef("absent", "Absent"), {})
        assert "unavailable" in app.screen.query_one(FlashLine).text
        app._run_command(None)
        await pilot.press("colon", "escape")
    run(RadrApp(registry=build_synthetic_registry()), scenario)


@pytest.mark.parametrize("approve", [True, False])
def test_mouse_action_menu_typed_delete_review_and_cancel(approve):
    invoke = Mock(return_value=None)
    action = Action("delete", "Delete", destructive=True, command="iot adr ns device delete", invoke=invoke)

    async def scenario(app, pilot):
        await pilot.press("a")
        assert isinstance(app.screen, ActionMenu)
        await pilot.click("#action-options", offset=(2, 0))
        await pilot.pause()
        assert isinstance(app.screen, ReviewDialog)
        dialog = app.screen
        assert "--subscription sub" in dialog.command and "-g rg" in dialog.command
        assert dialog.query_one("#confirm", Button).disabled
        await pilot.click("#confirm-name")
        await pilot.press("o", "n", "e")
        assert not dialog.query_one("#confirm", Button).disabled
        await pilot.click("#confirm" if approve else "#cancel")
        await settle(app, pilot)
        assert invoke.call_count == int(approve)
        assert not app.operations_running
        if approve:
            await pilot.click("#operations")
            assert isinstance(app.screen, OperationsDialog)
            await pilot.click("#ack")
            assert not app.tracker.operations
    run(app_for(action), scenario)


def test_create_form_validation_submit_and_stale_context():
    invoke = Mock()
    action = Action(
        "create", "Create", invoke=invoke, collection=True, command="iot adr ns device create",
        fields=(Field("name", "-n", "Name"),),
    )

    async def scenario(app, pilot):
        spec = app.screen.spec
        app.perform_action(spec, action, {}, app.scope)
        await pilot.pause()
        assert isinstance(app.screen, ActionForm)
        await pilot.click("#review")
        assert "required" in str(app.screen.query_one("#form-error").render())
        await pilot.click("#field-name")
        await pilot.press("n", "e", "w", "enter")
        await pilot.pause()
        assert isinstance(app.screen, ReviewDialog)
        assert app.screen.target_name == "new"
        app._context_generation += 1
        await pilot.click("#confirm")
        await pilot.pause()
        invoke.assert_not_called()
        assert "invalidated" in app.screen.query_one(FlashLine).text
        app.perform_action(spec, action, {}, app.scope)
        await pilot.pause()
        app._context_generation += 1
        app.screen.query_one(Input).value = "another"
        await pilot.click("#review")
        assert "Context changed" in app.screen.query_one(FlashLine).text
    run(app_for(action), scenario)


def test_readonly_generic_menu_and_late_gate_never_invoke():
    invoke = Mock()
    action = Action("delete", "Delete", command="iot adr ns delete", invoke=invoke)

    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("a")
        options = app.screen.query_one(OptionList)
        assert options.get_option_at_index(0).disabled
        app.action_actions()
        await pilot.click("#cancel")
        app.perform_action(root.spec, action, make_payload("one"), app.scope)
        assert "Read-only" in root.query_one(FlashLine).text
        app._start_action(root.spec, action, make_payload("one"), app.scope, "az ...")
        invoke.assert_not_called()
        app.read_only = False
        app.perform_action(root.spec, replace(action, invoke=None), make_payload("one"), app.scope)
        assert "Not applicable" in root.query_one(FlashLine).text
        app.perform_action(root.spec, action, make_payload("one"), {})
        assert "parent scope" in root.query_one(FlashLine).text
        app._review_action(root.spec, action, make_payload("one"), {}, app._context_generation)
        assert "unresolved" in root.query_one(FlashLine).text
    run(app_for(action, read_only=True), scenario)


def test_busy_namespace_and_worker_limit_prevent_overlapping_operations():
    invoke = Mock()
    action = Action("update", "Update", invoke=invoke)

    async def scenario(app, _pilot):
        root = app.screen
        app._busy.add(("sub", "rg", "one"))
        assert app.operations_running
        app._start_action(root.spec, action, make_payload("one"), app.scope, "az ...")
        assert "already running" in root.query_one(FlashLine).text
        app._busy.update({("sub", "rg", str(i)) for i in range(4)})
        app._start_action(root.spec, action, make_payload("two"), app.scope, "az ...")
        invoke.assert_not_called()
        app._busy.clear()
    run(app_for(action), scenario)


def test_error_operation_and_stop_watching_never_replay():
    invoke = Mock(side_effect=SessionError("failed safely"))
    action = Action("update", "Update", invoke=invoke, command="iot adr ns update")

    async def scenario(app, pilot):
        root = app.screen
        app._start_action(root.spec, action, make_payload("one"), app.scope, "az ...")
        await settle(app, pilot)
        assert app.tracker.failed[0].error == "failed safely"
        pending = app.tracker.start("Pending", "two")
        await pilot.click("#operations")
        await pilot.pause()
        await pilot.click("#stop-watch")
        assert not pending.watching and "not watching" in pending.describe()
        await pilot.click("#re-read")
        await settle(app, pilot)
        assert app.screen is root
        invoke.assert_called_once()
        app.tracker.succeed(pending)
        await pilot.press("o", "escape")
    run(app_for(action), scenario)


def test_empty_actions_operations_and_no_root_back():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("escape")
        assert "quit" in root.query_one(FlashLine).text
        await pilot.press("a", "escape")
        await pilot.press("o", "x")
        await pilot.click("#close")
        await pilot.press("question_mark", "escape")
        assert app.screen is root
    run(app_for(), scenario)


def test_browse_missing_scopes_and_declared_navigation(mocker):
    from azext_iot.adr.ui.screens.base import ChromeScreen

    async def scenario(app, pilot):
        root = app.screen
        assert root.breadcrumb()
        assert root.guide() is root.spec.guide
        assert root.hint_bindings()
        assert ChromeScreen.filter_text(root) == ""
        assert ChromeScreen.breadcrumb(root) == "browse"
        assert ChromeScreen.guide(root) is None
        assert not list(ChromeScreen.compose_content(root))
        ChromeScreen().flash("unmounted")
        missing = BrowseScreen(
            replace(root.spec, requires=("namespace_name", "resource_group_name")),
            Mock(side_effect=AssertionError("missing scope must not query Azure")),
        )
        await app.push_screen(missing)
        await pilot.pause()
        assert "Open a namespace first" in missing.model.error
        assert "a group and a job" in missing._missing_scope_message(["group_name", "job_name"])
        assert "a certificate authority" in missing._missing_scope_message(["certificate_authority_name"])
        assert "unknown_scope" in missing._missing_scope_message(["unknown_scope"])
        app.pop_screen_safely()
        await pilot.pause()
        missing._on_loaded([])
        missing._on_load_failed("late result")
        root._refresh_visible()
        await settle(app, pilot)
        assert root.selected_payload()
        child = ChildRef("widget", "Widgets", "w")
        app.open_child(root.spec, child, root.selected_payload())
        await settle(app, pilot)
        assert app.screen.scope["widget_name"] == "one"
        await pilot.press("escape")
        root._open_child(child)
        await settle(app, pilot)
        app._active_scope()
        spec = replace(root.spec, actions=(Action("test", "Test", key="t"),), children=(child,))
        assert ("t", "test") in BrowseScreen(spec, Mock()).hint_bindings()
        fallback = RadrApp(registry=build_synthetic_registry())
        assert fallback._active_scope() == fallback.scope
        app.notify = mocker.Mock()
        await pilot.press("question_mark")
        app.flash("modal error", "error")
        app.notify.assert_called_once_with("modal error", severity="error")
    run(app_for(), scenario)


def test_form_cancel_optional_input_and_unavailable_menu():
    action = Action("new", "New", invoke=Mock(), collection=True, fields=(Field("name", "-n", "Name"),))

    async def scenario(app, pilot):
        root = app.screen
        app.perform_action(root.spec, action, {}, app.scope)
        await pilot.pause()
        await pilot.click("#cancel")
        assert app.screen is root
        app.perform_action(root.spec, action, {}, app.scope)
        await pilot.pause()
        await pilot.press("escape")
        assert app.screen is root
        unusable = replace(action, collection=False, applies_to=lambda _p: False)
        await app.push_screen(ActionMenu(replace(root.spec, actions=(unusable,)), {}, False))
        assert app.screen.query_one(OptionList).get_option_at_index(0).disabled
        await pilot.press("escape")
        await app.push_screen(ReviewDialog(Action("read", "Read", mutation=False), "one", "az test", app.scope))
        await pilot.press("escape")
        assert app.screen is root
    run(app_for(action), scenario)


@pytest.mark.parametrize("kind,payload,expected", [
    ("namespace", {"name": "one", "tags": {"keep": "value"}}, '{"keep": "value"}'),
    ("device", {"name": "one", "properties": {"enablementState": "Disabled"}}, "Disabled"),
    ("policy", {"name": "one", "properties": {"certificate": {"validityPeriodInDays": 7}}}, "7"),
    ("group", {"name": "one", "properties": {"displayName": "Current display"}}, "Current display"),
])
def test_update_forms_start_from_current_values_and_reject_unchanged(kind, payload, expected):
    from azext_iot.adr.ui.kinds import build_registry

    action = build_registry(None).get(kind).action("update")

    async def scenario(app, pilot):
        await app.push_screen(ActionForm(action, payload))
        assert app.screen.query_one(Input).value == expected
        await pilot.click("#review")
        assert isinstance(app.screen, ActionForm)
        assert "Nothing changed" in str(app.screen.query_one("#form-error").render())
        await pilot.press("escape")
        assert not app.tracker.operations
    run(app_for(), scenario)


def test_clearing_existing_tags_requires_typed_approval(mocker):
    from azext_iot.adr.ui.kinds import build_registry

    action = build_registry(None).get("namespace").action("update")

    async def scenario(app, pilot):
        root = app.screen
        app._review_action(root.spec, action, {"name": "one", "tags": {"keep": "old"}, "_inputs": {"tags": {}}},
                           app.scope, app._context_generation)
        await pilot.pause()
        assert app.screen.action.destructive
        assert app.screen.query_one("#confirm", Button).disabled
        start = mocker.patch.object(app, "_start_action")
        app.screen.on_button_pressed(Button.Pressed(app.screen.query_one("#confirm", Button)))
        start.assert_not_called()
        await pilot.press("escape")
    run(app_for(), scenario)


def test_detail_metadata_help_and_browse_child_shortcut():
    async def scenario(app, pilot):
        await pilot.press("g")
        await settle(app, pilot)
        assert app.screen.spec.kind == "group"
        await pilot.press("escape", "enter")
        await pilot.pause()
        detail = app.screen
        assert detail.breadcrumb()
        assert detail.guide().about
        assert detail.selected_payload()
        standalone = DetailScreen(None, {"name": "record"}, name="explicit")
        assert standalone.resource_name() == "explicit"
        detail.on_button_pressed(Button.Pressed(Button("unrelated")))
        await pilot.click("#resource-selector")
        await pilot.pause()
        assert isinstance(app.screen, CommandBar)
        await pilot.press("escape")
    run(RadrApp(registry=build_synthetic_registry()), scenario)


def test_quit_can_keep_pending_azure_operation_and_its_result_visible():
    started = threading.Event()
    release = threading.Event()

    def invoke(*_args):
        started.set()
        if not release.wait(5):
            raise SessionError("Test failed to release the operation")

    action = Action("update", "Update", invoke=invoke)

    async def scenario(app, pilot):
        root = app.screen
        app._start_action(root.spec, action, make_payload("one"), app.scope, "az reviewed")
        try:
            assert await asyncio.to_thread(started.wait, 3)
            await pilot.press("q")
            assert app.is_running
            assert isinstance(app.screen, QuitDialog)
            await pilot.click("#cancel")
            await pilot.press("ctrl+q", "escape")
            assert app.screen is root
            assert app.operations_running
        finally:
            release.set()
        await settle(app, pilot)
        assert not app.operations_running
        assert not app.tracker.failed
        assert not app.final_outcomes()
        await pilot.press("q")
    run(app_for(action), scenario)


def test_quit_anyway_returns_before_the_pending_operation_finishes():
    started, release, finished = (threading.Event() for _ in range(3))

    def invoke(*_args):
        started.set()
        release.wait(10)
        finished.set()

    action = Action("update", "Update", invoke=invoke)
    app = app_for(action)

    async def scenario(app, pilot):
        app._start_action(app.screen.spec, action, make_payload("one"), app.scope, "az reviewed")
        assert await asyncio.to_thread(started.wait, 3)
        await pilot.press("q")
        dialog = app.screen
        await pilot.press("q")
        assert app.screen is dialog
        await pilot.click("#quit-anyway")

    try:
        run(app, scenario)
        assert not finished.is_set()
        assert "Outcome unknown" in app.final_outcomes()[0]
        assert "Requested command: az reviewed" in app.final_outcomes()[0]
    finally:
        release.set()
        assert finished.wait(3)


def test_quit_does_not_wait_for_a_routine_table_read():
    started, release, finished = (threading.Event() for _ in range(3))

    def load(_scope):
        started.set()
        release.wait(10)
        finished.set()
        return []

    registry = Registry()
    registry.register(widget_spec(list=load))
    app = RadrApp(registry=registry, refresh_interval=900)

    async def runner():
        async with app.run_test() as pilot:
            assert await asyncio.to_thread(started.wait, 3)
            await pilot.press("q")

    try:
        asyncio.run(runner())
        assert not finished.is_set()
        assert not app.final_outcomes()
    finally:
        release.set()
        assert finished.wait(3)


def test_queued_refresh_is_visible_and_cancellation_clears_loading():
    async def scenario(app, pilot):
        root = app.screen
        for _ in range(4):
            await app.io_slots.acquire()
        try:
            root.refresh_rows()
            await pilot.pause()
            assert "available Azure request slot" in root.query_one(FlashLine).text
            for worker in app.workers:
                worker.cancel()
            await pilot.pause()
            assert not root._loading
        finally:
            for _ in range(4):
                app.io_slots.release()
    run(app_for(), scenario)


def test_operation_snapshot_is_unchanged_by_later_results():
    app = app_for()
    operation = app.tracker.start("Update", "one", "az reviewed")
    snapshot = app.tracker.snapshot()
    app.tracker.fail(operation, "late failure")
    assert not snapshot[0].state.is_terminal
    assert snapshot[0].error is None
    assert "late failure" in app.final_outcomes()[0]


@pytest.mark.parametrize("failed", [True, False])
def test_late_worker_result_is_retained_after_terminal_shutdown(failed):
    app = app_for()
    action = Action("update", "Update", invoke=Mock(
        side_effect=SessionError("late failure") if failed else None,
        return_value=None,
    ))
    operation = app.tracker.start("Update", "one", "az exact-command")
    app._invoke_action(action, make_payload("one"), app.scope, operation, ("sub", "rg", "one"))
    outcome = app.final_outcomes()
    assert len(outcome) == 1
    assert "az exact-command" in outcome[0]
    assert ("failed" if failed else "succeeded") in outcome[0]


@pytest.mark.parametrize("remains_running", [True, False])
def test_worker_completion_shutdown_race_is_not_silently_dropped(remains_running, mocker):
    app = app_for()
    mocker.patch.object(type(app), "is_running", mocker.PropertyMock(side_effect=[True, remains_running]))
    mocker.patch.object(app, "call_from_thread", side_effect=RuntimeError("race"))
    action = Action("update", "Update", invoke=Mock(return_value=None))
    operation = app.tracker.start("Update", "one")
    if remains_running:
        with pytest.raises(RuntimeError, match="race"):
            app._invoke_action(action, {}, app.scope, operation, ("sub", "rg", "one"))
    else:
        app._invoke_action(action, {}, app.scope, operation, ("sub", "rg", "one"))
        assert app._late_results == [operation]
