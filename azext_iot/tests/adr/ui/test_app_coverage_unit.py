# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Application navigation and mutation boundaries driven without Azure or a terminal."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.widgets import Input

from azext_iot.adr.ui import app as app_module, entry
from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.ops import OpState
from azext_iot.adr.ui.core.session import Scope, Session
from azext_iot.adr.ui.core.spec import Action, ChildRef, Registry
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.screens.onboard.execution import ExecutionScreen, ExecutionState
from azext_iot.adr.ui.screens.onboard.flow import PlanItem
from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.adr.ui.widgets.chrome import ContextBar, FlashLine, InfoPanel
from azext_iot.adr.ui.widgets.dialogs import TypeNameConfirmDialog
from azext_iot.adr.ui.widgets.tray import CommandPreviewDialog, OperationsDialog, OperationsTray
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


async def settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def run_app(scenario, **kwargs):
    async def runner():
        app = RadrApp(**kwargs)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            await scenario(app, pilot)
    asyncio.run(runner())


def test_read_only_navigation_refresh_and_action_attempts_never_mutate():
    invoke = Mock()
    loader = Mock(return_value=[make_payload("one")])
    action = Action("delete", "Delete", destructive=True, invoke=invoke)
    spec = widget_spec(list=loader, actions=(action,), children=())
    registry = Registry()
    registry.register(spec)

    async def scenario(app, pilot):
        root = app.screen
        assert isinstance(root, BrowseScreen)
        assert "mode read-only" in root.query_one(InfoPanel).text
        assert "log test-ui.log" in root.query_one(InfoPanel).text
        app.perform_action(spec, action, root.selected_payload(), root.scope)
        assert app.screen is root
        assert "read-only session" in root.query_one(FlashLine).text
        await pilot.press("y")
        assert isinstance(app.screen, DetailScreen)
        assert app.screen.resource_name() == "one"
        await pilot.press("escape", "r")
        await settle(app, pilot)
        assert loader.call_count == 2
        await pilot.press("colon")
        assert isinstance(app.screen, CommandBar)
        app.screen.query_one(Input).value = "  wg  "
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, BrowseScreen)
        assert app.screen.spec is spec
        assert loader.call_count == 2  # alias navigation reuses the read cache
        app.perform_action(spec, action, make_payload("one"), app.screen.scope)
        await pilot.press("o")
        assert isinstance(app.screen, OperationsDialog)
        assert app.screen._format().plain == "no operations yet"
        await pilot.press("escape")
        invoke.assert_not_called()
        assert app.tracker.operations == []

    run_app(scenario, registry=registry, read_only=True, log_path="test-ui.log")


@pytest.mark.parametrize("destructive, cancel_at", [
    (False, "preview"), (True, "preview"), (True, "name"),
])
def test_cancelled_action_never_invokes_or_tracks_work(destructive, cancel_at):
    invoke = Mock()
    spec = widget_spec()
    action = Action("delete", "Delete", destructive=destructive, invoke=invoke)

    async def scenario(app, pilot):
        root = app.screen
        app.perform_action(spec, action, make_payload("one"), {})
        await pilot.pause()
        assert isinstance(app.screen, CommandPreviewDialog)
        assert app.screen._command == "az iot adr ns widget delete -n one"
        if cancel_at == "name":
            await pilot.click("#run")
            await pilot.pause()
            assert isinstance(app.screen, TypeNameConfirmDialog)
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.screen is root
        invoke.assert_not_called()
        assert app.tracker.operations == []

    run_app(scenario)


@pytest.mark.parametrize("destructive, fails", [(False, False), (True, False), (False, True)])
def test_approved_action_worker_records_outcome_and_invalidates_declared_caches(monkeypatch, destructive, fails):
    payload = make_payload("one")
    loader = Mock(return_value=[payload])
    invoke = Mock(side_effect=RuntimeError("service denied") if fails else None, return_value=None)
    action = Action("delete", "Delete", destructive=destructive, invoke=invoke, refreshes=("widget", "gadget"))
    spec = widget_spec(list=loader, actions=(action,), children=())
    registry = Registry()
    registry.register(spec)

    async def scenario(app, pilot):
        invalidate = Mock(wraps=app.store.invalidate)
        monkeypatch.setattr(app.store, "invalidate", invalidate)
        root = app.screen
        app.perform_action(spec, action, payload, root.scope)
        await pilot.pause()
        invoke.assert_not_called()
        await pilot.click("#run")
        await pilot.pause()
        if destructive:
            assert isinstance(app.screen, TypeNameConfirmDialog)
            invoke.assert_not_called()
            app.screen.query_one(Input).value = "one"
            await pilot.pause()
            await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is root
        invoke.assert_called_once_with(None, root.scope, payload)
        operation, = app.tracker.operations
        assert operation.state is (OpState.FAILED if fails else OpState.SUCCEEDED)
        assert operation.refreshes == ("widget", "gadget")
        assert operation.command == "az iot adr ns widget delete -n one"
        assert [call.args for call in invalidate.call_args_list] == [("widget",), ("gadget",)]
        assert loader.call_count == 2
        assert ("failed: service denied" if fails else "succeeded") in root.query_one(FlashLine).text
        tray = root.query_one(OperationsTray)
        assert tray.tracker is app.tracker
        assert tray.display
        app._tick_operations()
        assert ("failed" if fails else "succeeded") in tray.text

    run_app(scenario, registry=registry)


def test_action_without_implementation_warns_and_command_metadata_is_quoted():
    async def scenario(app, pilot):
        spec = widget_spec()
        app.perform_action(spec, Action("disable", "Disable"), make_payload("one"), {})
        assert "'Disable' is not available yet" == app.screen.query_one(FlashLine).text
        action = SimpleNamespace(command="iot adr ns group delete", destructive=True)
        assert app._command_for(spec, action, "a b", {"namespace_name": "ns", "resource_group_name": "rg"}) == (
            "az iot adr ns group delete -n 'a b' --ns ns -g rg --yes"
        )
        assert app.tracker.operations == []
    run_app(scenario)


def test_command_bar_cancel_unknown_help_and_scoped_alias_navigation():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("g")
        await settle(app, pilot)
        group_scope = dict(app.screen.scope)
        assert group_scope["namespace_name"] == "factory-eastus2"
        await pilot.press("colon", "escape")
        assert app.screen.scope == group_scope
        await pilot.press("colon")
        app.screen.query_one(Input).value = "missing-kind"
        await pilot.press("enter")
        await pilot.pause()
        assert "unknown command 'missing-kind'" == app.screen.query_one(FlashLine).text
        await pilot.press("colon")
        app.screen.query_one(Input).value = "help"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        # Modal screens do not carry chrome or the tray; late completions remain safe.
        app.sync_chrome(app.screen)
        app._refresh_tray()
        app.flash("background message")
        operation = app.tracker.start("Read", "group", refreshes=("group",))
        app.tracker.succeed(operation)
        app._action_finished(operation)
        assert app.screen is not root
        await pilot.press("escape")
        await pilot.press("colon")
        app.screen.query_one(Input).value = "grp"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen.spec.kind == "group"
        assert app.screen.scope == group_scope
        app.sync_chrome(ChromeScreen())  # late worker callback before composition
        assert app.screen.scope == group_scope
    run_app(scenario)


@pytest.mark.parametrize("token, target, expected", [
    ("setup", "action_onboard", {}), ("onboard", "action_onboard", {}),
    ("new", "action_onboard", {"fresh": True}), ("fresh", "action_onboard", {"fresh": True}),
    ("q", "exit", {}), ("quit", "exit", {}), ("exit", "exit", {}),
    ("?", "action_help", {}), ("help", "action_help", {}),
])
def test_reserved_command_tokens_dispatch_to_the_public_action(monkeypatch, token, target, expected):
    app = RadrApp()
    action = Mock()
    monkeypatch.setattr(app, target, action)
    app._run_command(f"  {token}  ")
    action.assert_called_once_with(**expected)


def test_blank_commands_and_late_scope_resolution_are_safe_before_mount():
    session = SimpleNamespace(scope=Scope(subscription_id="sub"))
    app = RadrApp(session=session)
    app._run_command(None)
    app._run_command("  ")
    app._refresh_tray()
    app._apply_resolved_scope()
    assert app.scope["subscription"] == "sub"
    assert app._active_scope() is app.scope
    assert app.screen_stack == []


def test_navigation_omits_missing_optional_children_and_preserves_parent_scope():
    async def scenario(app, pilot):
        root = app.screen
        payload = root.selected_payload()
        absent = ChildRef("future", "Future")
        app.open_scoped_child(absent, {})
        assert "'future' is not available yet" == root.query_one(FlashLine).text
        app.open_overview(root.spec, payload, [absent])
        assert app.screen is root
        assert "no related resource collections" in root.query_one(FlashLine).text
        group = root.spec.children[0]
        app.open_overview(root.spec, payload, [absent, group])
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert len(app.screen.child_entries) == 1
        assert app.screen.child_entries[0][0] == group
        assert app.screen.scope["namespace_name"] == payload["name"]
        app.action_toggle_theme()
        await pilot.pause()
        assert app._theme_name == "light"
        await pilot.press("escape")
        assert app.screen is root
        await pilot.press("escape")
        assert app.screen is root
        assert root.query_one(FlashLine).text == "press q to quit"
    run_app(scenario)


def test_live_constructor_uses_session_registry_waiter_and_resolves_scope_off_thread(monkeypatch):
    session = SimpleNamespace(scope=Scope(), list_from=Mock(return_value=[]), provider=Mock())

    def resolve():
        session.scope.subscription_id = "sub"
        session.scope.subscription_name = "Test subscription"

    session.resolve_subscription = Mock(side_effect=resolve)
    factory = Mock(return_value=session)
    monkeypatch.setattr(app_module, "Session", factory)
    command = object()

    async def scenario(app, pilot):
        factory.assert_called_once_with(command, resource_group_name="rg", namespace_name="ns", read_only=True)
        session.resolve_subscription.assert_called_once_with()
        assert app.scope == {"subscription_id": "sub", "subscription": "Test subscription",
                             "resource_group_name": "rg", "namespace_name": "ns"}
        assert app.screen.scope == app.scope
        assert "Test subscription" in app.screen.query_one(ContextBar).text
        screen = app.screen
        app._apply_resolved_scope(session)
        assert app.screen is screen
        assert app.registry.resolve("device") is None
        assert app.registry.get("link").actions == ()
        session.provider.return_value._await_terminal.return_value = None
        operation = app.tracker.start("Update", "ns")
        poller = Mock()
        app.tracker.await_poller(operation, poller)
        session.provider.assert_called_once_with("namespace")
        session.provider.return_value._await_terminal.assert_called_once_with(poller)
        assert operation.state is OpState.SUCCEEDED
    run_app(scenario, cmd=command, resource_group_name="rg", namespace_name="ns", read_only=True)


def test_setup_entry_scope_projection_without_entering_onboarding_modules(monkeypatch):
    # The app owns routing; the setup screen's behavior is deliberately outside this test.
    factory = Mock(side_effect=lambda *args, **kwargs: ChromeScreen())
    catalog = Mock()
    monkeypatch.setattr(app_module, "OnboardScreen", factory)
    monkeypatch.setattr(app_module, "ResourceCatalog", catalog)
    session = SimpleNamespace(scope=Scope(subscription_id="sub", subscription_name="Subscription"),
                              resolve_subscription=Mock())

    async def scenario(app, pilot):
        root = app.screen
        app.action_onboard()
        await pilot.pause()
        args, kwargs = factory.call_args
        assert args[0] is session
        assert args[1]["namespace_name"] == root.selected_payload()["name"]
        assert args[1]["resource_group_name"] == "adr-prod-rg"
        assert args[1]["subscription_name"] == "Subscription"
        assert kwargs["catalog"] is catalog.return_value
        app.pop_screen_safely()
        await pilot.pause()
        app.action_new_setup()
        await pilot.pause()
        assert factory.call_args.args[1] == {"subscription_id": "sub", "subscription_name": "Subscription"}
        app.pop_screen_safely()
        await pilot.pause()
        await app.push_screen(ChromeScreen())
        app.action_onboard()
        await pilot.pause()
        assert factory.call_args.args[1]["namespace_name"] is None
        assert factory.call_count == 3
    run_app(scenario, session=session)


def test_setup_without_session_explains_unavailable_action():
    async def scenario(app, pilot):
        root = app.screen
        app.action_onboard()
        assert app.screen is root
        assert root.query_one(FlashLine).text == "guided setup needs a live session"
    run_app(scenario)


@pytest.mark.parametrize("hook", ["refresh_view", "_repaint", "_paint", "repaint_theme", None])
def test_theme_toggle_repaints_supported_screen_contracts(monkeypatch, hook):
    async def scenario(app, pilot):
        screen = ChromeScreen()
        repaint = Mock()
        if hook:
            monkeypatch.setattr(screen, hook, repaint, raising=False)
        await app.push_screen(screen)
        app.action_toggle_theme()
        await pilot.pause()
        assert app._theme_name == "light"
        app.action_toggle_theme()
        await pilot.pause()
        assert app._theme_name == "dark"
        assert repaint.call_count == (2 if hook else 0)
        assert screen.query_one(FlashLine).text == "night theme"
    run_app(scenario)


def test_unknown_base_theme_does_not_prevent_initial_load():
    async def scenario():
        app = RadrApp()
        app._base_theme = "unregistered-theme"
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            assert isinstance(app.screen, BrowseScreen)
            assert app.screen.model.total_count == 3
    asyncio.run(scenario())


def test_debug_entry_requests_default_log_and_passes_active_path(monkeypatch, tmp_path):
    app_factory = Mock()
    configure = Mock(return_value=str(tmp_path / "active.log"))
    default_path = Mock(return_value=str(tmp_path / "default.log"))
    monkeypatch.setattr(app_module, "RadrApp", app_factory)
    monkeypatch.setattr(entry, "_silence_provider_console", Mock())
    monkeypatch.setattr("azext_iot.adr.ui.core.diagnostics.configure", configure)
    monkeypatch.setattr("azext_iot.adr.ui.core.diagnostics.default_log_path", default_path)
    command = SimpleNamespace(cli_ctx=SimpleNamespace(verbosity=1))
    entry.adr_ui_launch(command, read_only=True, theme="light", refresh_interval=1)
    default_path.assert_called_once_with()
    configure.assert_called_once_with(str(tmp_path / "default.log"))
    app_factory.assert_called_once_with(cmd=command, resource_group_name=None, namespace_name=None,
                                        read_only=True, refresh_interval=5, theme_name="light",
                                        log_path=str(tmp_path / "active.log"))
    app_factory.return_value.run.assert_called_once_with()


def test_subscription_switch_without_session_preserves_current_screen():
    async def scenario(app, pilot):
        root = app.screen
        scope = dict(app.scope)
        await app.switch_subscription("sub-b", "Subscription B")
        assert app.screen is root
        assert app.scope == scope
        assert root.query_one(FlashLine).text == "switching subscription needs a live session"
    run_app(scenario)


@pytest.mark.parametrize("busy", ["operation", "setup"])
def test_subscription_switch_does_not_cancel_or_retarget_running_mutations(busy):
    session = SimpleNamespace(scope=Scope(subscription_id="sub-a"),
                              resolve_subscription=Mock(),
                              cmd=SimpleNamespace(cli_ctx=SimpleNamespace(data={"subscription_id": "sub-a"})))

    async def scenario(app, pilot):
        root = app.screen
        scope = dict(app.scope)
        release = asyncio.Event()
        if busy == "operation":
            operation = app.tracker.start("Update", "namespace-a")
        else:
            worker = app.run_worker(release.wait(), name="onboard-execution")
        try:
            await pilot.pause()
            await app.switch_subscription("sub-b", "Subscription B")
            assert app.screen is root
            assert app.session is session
            assert app.scope == scope
            assert session.cmd.cli_ctx.data["subscription_id"] == "sub-a"
            assert root.query_one(FlashLine).text == "wait for running operations before switching subscription"
            if busy == "operation":
                assert operation.state is OpState.RUNNING
            else:
                assert not worker.is_cancelled
        finally:
            release.set()
            await settle(app, pilot)
    run_app(scenario, session=session)


def test_command_subscription_is_authoritative_before_browse_and_selected_setup(monkeypatch):
    from azure.cli.core import get_default_cli
    from azure.cli.core._profile import Profile

    cli_ctx = get_default_cli()
    monkeypatch.setitem(cli_ctx.data, "subscription_id", "sub-b")
    monkeypatch.setattr(Profile, "load_cached_subscriptions", lambda self: [
        {"id": "sub-a", "name": "Default A", "isDefault": True},
        {"id": "sub-b", "name": "Override B", "isDefault": False},
    ])
    provider = Mock()
    provider.list.return_value = [{
        "name": "namespace-b", "resourceGroup": "rg-b",
        "id": "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.DeviceRegistry/namespaces/namespace-b",
    }]
    monkeypatch.setattr("azext_iot.adr.providers.namespace.NamespaceProvider", Mock(return_value=provider))
    setup = Mock(side_effect=lambda *args, **kwargs: ChromeScreen())
    monkeypatch.setattr(app_module, "OnboardScreen", setup)
    monkeypatch.setattr(app_module, "ResourceCatalog", Mock())

    async def scenario(app, pilot):
        assert app.scope["subscription_id"] == "sub-b"
        assert app.scope["subscription"] == "Override B"
        assert app.screen.scope["subscription_id"] == "sub-b"
        assert app.screen.selected_payload()["name"] == "namespace-b"
        app.action_onboard()
        await pilot.pause()
        selected = setup.call_args.args[1]
        assert selected["subscription_id"] == "sub-b"
        assert selected["subscription_name"] == "Override B"
        assert selected["namespace_name"] == "namespace-b"
        assert selected["resource_group_name"] == "rg-b"
        assert Profile(cli_ctx=cli_ctx).get_subscription()["id"] == "sub-a"
        provider.create.assert_not_called()

    run_app(scenario, cmd=SimpleNamespace(cli_ctx=cli_ctx))


@pytest.mark.parametrize("kind", ["action", "setup"])
def test_queued_and_running_reviewed_writes_cannot_be_retargeted_by_subscription_switch(monkeypatch, kind):
    from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry

    session = Session(SimpleNamespace(cli_ctx=SimpleNamespace(data={"subscription_id": "sub-a"})))
    session.scope.subscription_id = "sub-a"
    started, release = threading.Event(), threading.Event()
    observed_subscriptions = []

    def write(active_session, _context, _payload=None):
        started.set()
        if not release.wait(10):
            raise RuntimeError("test did not release reviewed write")
        observed_subscriptions.append(active_session.cmd.cli_ctx.data["subscription_id"])

    invoke = Mock(side_effect=write)
    registry_factory = Mock(return_value=build_synthetic_registry())
    monkeypatch.setattr(app_module, "build_registry", registry_factory)
    monkeypatch.setattr(app_module, "ResourceCatalog", Mock(return_value=None))

    async def scenario(app, pilot):
        before = dict(app.scope)
        completed = Mock()
        try:
            if kind == "action":
                action = Action("update", "Update", invoke=invoke)
                app._start_action(widget_spec(), action, make_payload("reviewed-a"),
                                  {"subscription_id": "sub-a"}, "az update --subscription sub-a")
                operation, = app.tracker.operations
                assert operation.state is OpState.RUNNING
            else:
                setup = OnboardScreen(session, {"subscription_id": "sub-a"})
                monkeypatch.setattr(setup, "_execution_finished", completed)
                await app.push_screen(setup)
                await settle(app, pilot)
                setup._start_apply([PlanItem("write", "Reviewed write", invoke=invoke)])
                execution = app.screen
                assert isinstance(execution, ExecutionScreen)
                assert execution.records[0].state is ExecutionState.PENDING
                assert not any(worker.name == "onboard-execution" for worker in app.workers)

            # No yield since scheduling: this covers the window before the write worker starts.
            assert not started.is_set()
            reviewed_screen = app.screen
            await app.switch_subscription("sub-b", "Subscription B")
            assert app.session is session
            assert app.scope == before
            assert app.screen is reviewed_screen
            assert session.cmd.cli_ctx.data["subscription_id"] == "sub-a"
            registry_factory.assert_not_called()

            assert await asyncio.to_thread(started.wait, 5)
            # A global action may open another screen above the executing plan.
            await app.push_screen(ChromeScreen())
            overlay = app.screen
            await app.switch_subscription("sub-b", "Subscription B")
            assert app.screen is overlay
            assert app.session is session
            assert app.scope == before
            assert session.cmd.cli_ctx.data["subscription_id"] == "sub-a"
            assert overlay.query_one(FlashLine).text == "wait for running operations before switching subscription"
            assert not observed_subscriptions
            registry_factory.assert_not_called()
        finally:
            release.set()
            await settle(app, pilot)

        assert observed_subscriptions == ["sub-a"]
        invoke.assert_called_once()
        if kind == "action":
            assert operation.state is OpState.SUCCEEDED
        else:
            assert execution.records[0].state is ExecutionState.SUCCEEDED
            completed.assert_called_once_with(True)

    run_app(scenario, session=session, registry=build_synthetic_registry())
