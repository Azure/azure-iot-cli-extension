# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Minimal radar: one resource view, explicit context, and reviewed operations."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from functools import partial

from textual.app import App
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from azext_iot.adr.ui.core.commands import render
from azext_iot.adr.ui.core.io import run_io
from azext_iot.adr.ui.core.ops import OpState, OperationTracker, make_session_waiter
from azext_iot.adr.ui.core.session import Session, SessionError
from azext_iot.adr.ui.core.store import Store
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.theme import (
    APP_CSS, RADR_THEMES, base_theme_for, normalize_theme, resolve_palette, resolve_theme,
)
from azext_iot.adr.ui.widgets.actions import ActionMenu, ActionForm, QuitDialog, ReviewDialog
from azext_iot.adr.ui.widgets.tray import OperationsDialog


class RadrApp(App):
    """Browse ADR resources without creating namespaces or running onboarding."""

    CSS = APP_CSS
    TITLE = "radar"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("colon", "command_bar", "Resources", key_display=":"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("a", "actions", "Actions"),
        Binding("o", "operations", "Operations"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cmd=None, resource_group_name=None, namespace_name=None,
                 read_only=False, refresh_interval=5, theme_name=None, registry=None,
                 session=None, store=None, log_path=None, **kwargs):
        super().__init__(**kwargs)
        for ui_theme in RADR_THEMES:
            self.register_theme(ui_theme)
        self.cmd = cmd
        self.read_only = read_only
        self.refresh_interval = refresh_interval
        self._theme_name = normalize_theme(theme_name)
        self.theme_tokens = resolve_theme(self._theme_name)
        self.theme_palette = resolve_palette(self._theme_name)
        self.session = session or (
            Session(cmd, resource_group_name, namespace_name, read_only) if cmd else None
        )
        if registry is None and self.session is None:
            raise ValueError("Radar requires a CLI session or an explicitly injected test registry.")
        self.registry = registry if registry is not None else build_registry(self.session)
        self.store = store or Store(default_interval=refresh_interval)
        self.tracker = OperationTracker(make_session_waiter(self.session) if self.session else None)
        self.scope = self.session.scope.as_dict() if self.session else {
            "resource_group_name": resource_group_name, "namespace_name": namespace_name,
        }
        self.log_path = log_path
        self._context_generation = 0
        self._busy = set()
        self._late_results = []
        self.io_slots = asyncio.Semaphore(4)

    def on_mount(self):
        self.theme = base_theme_for(self._theme_name)
        if self.session:
            self.run_worker(run_io(self._resolve_scope, self.io_slots), name="resolve-scope")
        else:
            self.push_kind(self.registry.roots()[0], self.scope)

    def _resolve_scope(self):
        try:
            self.session.resolve_subscription()
        except SessionError as error:
            self.post_from_thread(self.notify, str(error), severity="error")
        self.post_from_thread(self._apply_resolved_scope)

    def post_from_thread(self, callback, *args, **kwargs):
        if not self.is_running:
            return False
        try:
            self.call_from_thread(callback, *args, **kwargs)
        except RuntimeError:
            if self.is_running:
                raise
            return False
        return True

    def _apply_resolved_scope(self):
        self.scope = self.session.scope.as_dict()
        self.push_kind(self.registry.roots()[0], self.scope)

    @property
    def operations_running(self):
        return bool(self._busy)

    async def action_quit(self):
        if isinstance(self.screen, QuitDialog):
            return
        if self.tracker.running:
            self.push_screen(QuitDialog(self.tracker.running), self._quit_confirmed)
            return
        self.exit()

    def _quit_confirmed(self, approved):
        if not approved:
            return
        for operation in self.tracker.running:
            operation.watching = False
        self.exit()

    def final_outcomes(self):
        late_ids = {operation.id for operation in self._late_results}
        operations = [
            operation for operation in self.tracker.snapshot()
            if operation.id in late_ids or operation.state in (OpState.FAILED, OpState.RUNNING)
        ]
        return [
            f"{operation.describe()}\n"
            + ("Outcome unknown. Verify the resource in Azure before retrying.\n"
               if not operation.state.is_terminal else "")
            + f"Requested command: {operation.command}"
            for operation in operations
        ]

    def _source_for(self, spec):
        def source(scope, force=False):
            return self.store.fetch_result(spec, scope, spec.list, force=force)
        return source

    def push_kind(self, spec, scope):
        self._context_generation += 1
        self.push_screen(BrowseScreen(
            spec, self._source_for(spec), scope, refresh_interval=self.store.interval_for(spec),
        ))

    def open_child(self, parent, child, payload):
        scope = dict(self._active_scope())
        scope.update(parent.child_scope(payload))
        self.open_scoped_child(child, scope)

    def open_scoped_child(self, child, scope):
        spec = self.registry.resolve(child.kind)
        if spec is None:
            self.flash(f"'{child.kind}' is unavailable", "warning")
            return
        self.push_kind(spec, scope)

    def open_detail(self, spec, payload):
        self._context_generation += 1
        scope = dict(self._active_scope())
        scope.update(spec.child_scope(payload))
        self.push_screen(DetailScreen(spec, payload, scope=scope))

    def pop_screen_safely(self):
        if len(self.screen_stack) <= 2:
            self.flash("press q to quit")
            return
        self._context_generation += 1
        self.pop_screen()

    def _active_scope(self):
        for screen in reversed(self.screen_stack):
            if hasattr(screen, "scope"):
                return screen.scope
        return self.scope

    def action_namespaces(self):
        self.push_kind(self.registry.roots()[0], dict(self.scope))

    def action_command_bar(self):
        self.push_screen(CommandBar([spec.kind for spec in self.registry.all()]), self._run_command)

    def _run_command(self, token):
        spec = self.registry.resolve(token or "")
        if spec:
            self.push_kind(spec, dict(self._active_scope()))
        elif token:
            self.flash(f"Unknown resource '{token}'", "warning")

    def action_help(self):
        self.push_screen(HelpScreen([
            (spec.kind, spec.title_plural) for spec in self.registry.all()
        ]))

    def action_operations(self):
        self.push_screen(OperationsDialog(self.tracker))

    def action_actions(self):
        if not isinstance(self.screen, ChromeScreen):
            return
        screen = self.screen
        payload = screen.selected_payload()
        spec = screen.spec
        scope = dict(self._active_scope())
        self.push_screen(
            ActionMenu(spec, payload, self.read_only),
            lambda action: self.perform_action(spec, action, payload or {}, scope) if action else None,
        )

    def perform_action(self, spec, action, payload, scope):
        if self.read_only and action.mutation:
            self.flash("Read-only session: writes are disabled.", "warning")
            return
        if not action.invoke or (not action.collection and not action.is_applicable(payload)):
            self.flash(action.unavailable, "warning")
            return
        generation = self._context_generation
        payload, scope = deepcopy(payload), dict(scope)
        if not action.collection:
            scope.update(spec.child_scope(payload))
        if spec.missing_scope(scope) or not scope.get("resource_group_name"):
            self.flash("Open the resource's parent scope before choosing an action.", "warning")
            return
        if action.fields:
            self.push_screen(ActionForm(action, payload), lambda values: self._review_action(
                spec, action, dict(payload, _inputs=values), scope, generation,
            ) if values is not None else None)
        else:
            self._review_action(spec, action, payload, scope, generation)

    def _review_action(self, spec, action, payload, scope, generation):
        if generation != self._context_generation:
            self.flash("Context changed. Open the action again.", "warning")
            return
        if not scope.get("subscription_id"):
            self.flash("Subscription is unresolved; no operation was sent.", "error")
            return
        if payload.get("tags") and payload.get("_inputs", {}).get("tags") == {}:
            action = replace(action, destructive=True)
        name = payload.get("_inputs", {}).get("name") or payload.get("name") or spec.row_id(payload)
        command = self._command_for(spec, action, str(name), scope, payload)
        if action.review_note:
            action = replace(action, note=action.review_note(scope, payload))
        self.push_screen(
            ReviewDialog(action, str(name), command, scope),
            lambda approved: self._start_action(
                spec, action, payload, scope, command, generation,
            ) if approved else None,
        )

    def _command_for(self, spec, action, name, scope, payload=None):
        if action.preview:
            return action.preview(scope, payload or {})
        return render(action.command, name=name, scope=scope,
                      flags=("--yes",) if action.destructive else ())

    def _start_action(self, spec, action, payload, scope, command, generation=None):
        if (generation is not None and generation != self._context_generation) or (
            self.read_only and action.mutation
        ):
            self.flash("Approval invalidated. Context or write mode changed.", "warning")
            return
        name = payload.get("_inputs", {}).get("name") or payload.get("name") or spec.row_id(payload)
        # Namespace writes share endpoints and can conflict even when names differ.
        key = (scope.get("subscription_id"), scope.get("resource_group_name"),
               scope.get("namespace_name") or name)
        if key in self._busy or len(self._busy) >= 4:
            self.flash("An operation is already running in this namespace, or the worker limit is reached.", "warning")
            return
        self._busy.add(key)
        operation = self.tracker.start(action.label, str(name), command, action.refreshes or (spec.kind,))
        self.run_worker(run_io(partial(self._invoke_action, action, payload, scope, operation, key), self.io_slots),
                        name=f"action-{operation.id}")
        self.sync_chrome(self.screen)

    def _invoke_action(self, action, payload, scope, operation, key):
        try:
            poller = action.invoke(self.session, scope, payload)
        except Exception as error:  # noqa: BLE001 - the operation is the write error boundary
            self.tracker.fail(operation, error)
        else:
            self.tracker.await_poller(operation, poller)
        finally:
            if not self.post_from_thread(self._action_finished, operation, key):
                self._late_results.append(operation)

    def _action_finished(self, operation, key):
        self._busy.discard(key)
        for kind in operation.refreshes:
            self.store.invalidate(kind)
        self.flash(operation.describe())
        self.sync_chrome(self.screen)

    def sync_chrome(self, screen):
        if not isinstance(screen, ChromeScreen) or not screen.is_mounted:
            return
        scope = self._active_scope()
        mode = "read-only" if self.read_only else "read/write"
        context = (
            f"{scope.get('resource_group_name') or 'all resource groups'} · "
            f"{scope.get('subscription') or scope.get('subscription_id') or 'subscription unresolved'} · {mode}"
        )
        screen.query_one("#context-bar", Static).update(context)
        screen.query_one("#namespace-selector", Button).label = scope.get("namespace_name") or "Namespaces"
        screen.query_one("#resource-selector", Button).label = screen.spec.title_plural
        state = f"{len(self.tracker.running)} running" if self.tracker.running else (
            f"{len(self.tracker.failed)} failed" if self.tracker.failed else "idle"
        )
        screen.query_one("#operations", Button).label = f"o ops {state}"

    def flash(self, message, level="info"):
        if isinstance(self.screen, ChromeScreen):
            self.screen.flash(message, level)
        elif isinstance(self.screen, ModalScreen):
            self.notify(message, severity="error" if level == "error" else "information")
