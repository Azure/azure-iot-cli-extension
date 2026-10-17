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

from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import ModalScreen

from azext_iot.adr.ui.core.commands import render
from azext_iot.adr.ui.core.io import run_io
from azext_iot.adr.ui.core.ops import OpState, OperationTracker, make_session_waiter
from azext_iot.adr.ui.core.scope import ScopeCatalog
from azext_iot.adr.ui.core.session import Session, SessionError
from azext_iot.adr.ui.core.store import Store
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen, switcher_entries
from azext_iot.adr.ui.theme import (
    APP_CSS, HIGH_CONTRAST_THEME, RADR_THEMES, base_theme_for, css_variables,
    next_theme, normalize_theme, resolve_palette, resolve_theme,
)
from azext_iot.adr.ui.widgets.actions import (
    ActionForm, ActionMenu, QuitDialog, ReviewDialog, menu_entries, scope_context, scope_label,
)
from azext_iot.adr.ui.widgets.minimal import ELLIPSIS
from azext_iot.adr.ui.widgets.scope import GROUP, ScopeDialog
from azext_iot.adr.ui.widgets.tray import OperationsScreen


class RadrApp(App):
    """Browse ADR resources without creating namespaces or running onboarding."""

    CSS = APP_CSS
    TITLE = "radar"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("colon", "command_bar", "Resources", key_display=":"),
        Binding("at", "pick_scope('group')", "Scope", key_display="@"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("a", "actions", "Actions"),
        Binding("o", "operations", "Operations"),
        Binding("ctrl+t", "toggle_theme", "Theme"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cmd=None, resource_group_name=None, namespace_name=None,
                 read_only=False, refresh_interval=5, theme_name=None, registry=None,
                 session=None, store=None, log_path=None, catalog=None, **kwargs):
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
        # An injected registry (tests, captures) is kept across scope changes; a live one is rebuilt
        # against each scope's own session.
        self._registry_injected = registry is not None
        self.registry = registry if registry is not None else build_registry(self.session)
        if catalog is None and self.session is not None and self.session.cmd is not None:
            catalog = ScopeCatalog.for_cli(self.session.cmd.cli_ctx)
        self.catalog = catalog
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

    def get_css_variables(self):
        """Radar tokens resolve under every base theme, including the ANSI high-contrast one."""
        variables = super().get_css_variables()
        palette = getattr(self, "theme_palette", None) or resolve_palette()
        for name, value in css_variables(palette).items():
            variables.setdefault(name, value)
        return variables

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
        model = getattr(self.screen, "model", None)
        count = model.total_count if model is not None else None
        self.push_screen(DetailScreen(spec, payload, scope=scope, count=count))

    def pop_screen_safely(self):
        if len(self.screen_stack) <= 2:
            self.flash("This is the first page. To leave: \u276f radar (Tab, Enter), Quit radar.")
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

    # -- scope ---------------------------------------------------------------

    def action_pick_scope(self, mode=GROUP):
        if not isinstance(self.screen, ChromeScreen):
            return
        if self.catalog is None:
            self.flash("Scope discovery is unavailable in this session.", "warning")
            return
        self.push_screen(ScopeDialog(self.catalog, dict(self.scope), mode), self.switch_scope)

    def switch_scope(self, choice):
        """Retarget browsing to another subscription and resource group.

        Everything scope-bound is replaced at once: a new session (its own CLI context copy, so the
        profile default never changes), a registry built against it, and a fresh screen stack.
        Screens of the previous scope are discarded, so their late results land on detached screens
        and are dropped; a review opened before the switch is rejected by the generation check.
        Operations already submitted keep their own session, scope and command.
        """
        if not choice:
            return
        subscription_id = choice["subscription_id"]
        group = choice.get("resource_group_name") or None
        if (subscription_id, group) == (self.scope.get("subscription_id"), self.scope.get("resource_group_name")):
            self.flash(f"Already viewing {scope_label(self.scope)}.")
            return
        base = next((screen for screen in reversed(self.screen_stack)
                     if isinstance(screen, BrowseScreen) and not screen.spec.parent), None)
        if self.session is not None:
            self.session = self.session.for_scope(subscription_id, choice.get("subscription"), group)
            if not self._registry_injected:
                self.registry = build_registry(self.session)
            self.scope = self.session.scope.as_dict()
        else:
            self.scope = {"subscription": choice.get("subscription") or subscription_id,
                          "subscription_id": subscription_id, "resource_group_name": group,
                          "namespace_name": None}
        self._context_generation += 1
        while len(self.screen_stack) > 1:
            self.pop_screen()
        # Stay on a top-level list (namespaces, update instances, schema registries) when possible.
        root = self.registry.resolve(base.spec.kind) if base is not None else None
        self.push_kind(root or self.registry.roots()[0], dict(self.scope))
        running = len(self.tracker.running)
        self.call_after_refresh(self.flash, f"Now viewing {scope_label(self.scope)}." + (
            f" {running} running operation(s) keep their original scope (o)." if running else ""
        ))

    def action_command_bar(self):
        current = getattr(getattr(self.screen, "spec", None), "kind", None)
        # Resource kinds only: scope has its own header controls (and ``@``), not a second path here.
        self.push_screen(CommandBar(switcher_entries(self.registry.all()), current=current,
                                    commands=self._radar_commands()), self._run_command)

    def _radar_commands(self):
        """Help, view settings and quit, offered only where they do something on this page."""
        commands = [("cmd:help", "Help and shortcuts")]
        screen = self.screen
        if isinstance(screen, BrowseScreen):
            commands += [("cmd:refresh", "Refresh now"), ("cmd:sort", f"Sort by{ELLIPSIS}")]
        if isinstance(screen, BrowseScreen) and screen.spec.visible_columns(True) != screen.spec.visible_columns(False):
            commands.append(("cmd:wide", "Show fewer columns" if screen.model.show_wide else "Show all columns"))
        if self._theme_name != HIGH_CONTRAST_THEME:
            commands.append(("cmd:theme", f"{next_theme(self._theme_name).capitalize()} theme"))
        return commands + [("cmd:quit", "Quit radar")]

    def _run_command(self, token):
        if str(token).startswith("cmd:sort:") and isinstance(self.screen, BrowseScreen):
            self.screen.sort_by(token[len("cmd:sort:"):])
            return
        command = dict((
            ("cmd:refresh", lambda: self.screen.action_refresh()),
            ("cmd:sort", self.action_sort_menu),
            ("cmd:help", self.action_help),
            ("cmd:wide", lambda: self.screen.action_toggle_wide()),
            ("cmd:theme", self.action_toggle_theme),
            ("cmd:quit", lambda: self.call_later(self.action_quit)),
        )).get(token)
        if command is not None:
            command()
            return
        spec = self.registry.resolve(token or "")
        if spec:
            self.push_kind(spec, dict(self._active_scope()))
        elif token:
            self.flash(f"Unknown resource '{token}'", "warning")

    def action_sort_menu(self):
        """``Sort by``: the displayed columns, chosen with arrows and Enter (``s`` opens it too)."""
        if isinstance(self.screen, BrowseScreen):
            choices = [(f"cmd:sort:{key}", label) for key, label in self.screen.sort_choices()]
            self.push_screen(CommandBar(commands=choices, heading="Sort by", accept="sort"), self._run_command)

    def action_help(self):
        page_keys = self.screen.help_keys() if isinstance(self.screen, ChromeScreen) else []
        self.push_screen(HelpScreen([
            (spec.kind, spec.title_plural) for spec in self.registry.all()
        ], page_keys=page_keys))

    def action_operations(self):
        if isinstance(self.screen, OperationsScreen):
            self.screen.action_close()
            return
        self.push_screen(OperationsScreen(self.tracker))

    def action_actions(self):
        if not isinstance(self.screen, ChromeScreen) or getattr(self.screen, "spec", None) is None:
            return
        screen = self.screen
        payload = screen.selected_payload()
        spec = screen.spec
        scope = dict(self._active_scope())
        if not menu_entries(spec, payload, self.read_only)[0]:
            self.flash(self.no_actions_reason(spec, payload), "warning")
            return
        self.push_screen(
            ActionMenu(spec, payload, self.read_only, scope=scope),
            lambda action: self.perform_action(spec, action, payload or {}, scope) if action else None,
        )

    def has_actions(self, spec, payload):
        return bool(spec is not None and menu_entries(spec, payload, self.read_only)[0])

    def no_actions_reason(self, spec, payload):
        if self.read_only and any(action.mutation for action in spec.actions):
            return "Read-only session: write actions are hidden."
        if not payload and spec.actions:
            return f"Select a {spec.title.lower()} first."
        return f"No actions for {spec.title_plural.lower()}."

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
            context = scope_context(scope, None if action.collection else str(payload.get("name") or spec.row_id(payload)))
            title = action.label if " " in action.label else f"{action.label} {spec.title.lower()}"
            self.push_screen(ActionForm(action, payload, context=context, title=title), lambda values: self._review_action(
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
        operation = self.tracker.start(action.label, str(name), command, action.refreshes or (spec.kind,),
                                       context=scope_label(scope))
        # The session is bound now: a scope switch while this waits for a slot must not retarget it.
        session = self.session
        self.run_worker(run_io(partial(self._invoke_action, action, payload, scope, operation, key, session),
                               self.io_slots), name=f"action-{operation.id}")
        self.sync_chrome(self.screen)

    def _invoke_action(self, action, payload, scope, operation, key, session=None):
        try:
            # The reviewed command names one subscription; the session's clients must target it.
            bound = getattr(getattr(session, "scope", None), "subscription_id", None)
            if bound and scope.get("subscription_id") and bound != scope["subscription_id"]:
                raise SessionError("The reviewed subscription is not the session's subscription; nothing was sent.")
            poller = action.invoke(session, scope, payload)
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
        elsewhere = operation.context and operation.context != scope_label(self.scope)
        self.flash(operation.describe() + (f" (in {operation.context})" if elsewhere else ""))
        self.sync_chrome(self.screen)

    def sync_chrome(self, screen):
        """Prompt header: context on the left; operations state (and read-only) on the right."""
        if not isinstance(screen, ChromeScreen) or not screen.is_mounted:
            return
        try:
            namespace = screen.query_one("#namespace-selector")
            group = screen.query_one("#group-selector")
            subscription = screen.query_one("#subscription-selector")
            operations = screen.query_one("#operations")
        except NoMatches:
            return
        colors = self.theme_palette
        scope = self._active_scope()
        if scope.get("namespace_name"):
            namespace.update(Text(str(scope["namespace_name"]), style=f"bold {colors['text']}"))
        else:
            namespace.update(Text("all namespaces", style=colors["dim"]))
        # Resource group and subscription open the scope picker; the faint mark says so.
        for widget, value in (
            (group, scope.get("resource_group_name") or "all resource groups"),
            (subscription, scope.get("subscription") or scope.get("subscription_id") or "subscription unresolved"),
        ):
            text = Text(no_wrap=True, overflow="ellipsis")
            text.append(" \u00b7 ", style=colors["dim"])
            text.append(str(value), style=colors["dim"])
            text.append(" \u25be", style=colors["placeholder"])
            widget.update(text)
        state = Text(no_wrap=True)
        if self.read_only:
            state.append("read-only", style=colors["warning"])
            state.append("  ")
        if self.tracker.running:
            state.append(f"{ELLIPSIS} {len(self.tracker.running)} running", style=colors["accent"])
        elif self.tracker.failed:
            state.append(f"\u2717 {len(self.tracker.failed)} failed", style=colors["error"])
        else:
            state.append("ops idle", style=colors["dim"])
        operations.update(state)

    def action_toggle_theme(self):
        """Cycle terminal, dark and light; high contrast stays fixed for the session."""
        if self._theme_name == HIGH_CONTRAST_THEME:
            self.flash("High contrast stays on. Restart with --theme terminal, dark or light to toggle.")
            return
        self._theme_name = next_theme(self._theme_name)
        self.theme_tokens = resolve_theme(self._theme_name)
        self.theme_palette = resolve_palette(self._theme_name)
        self.theme = base_theme_for(self._theme_name)
        for screen in self.screen_stack:
            if isinstance(screen, ChromeScreen) and screen.is_mounted:
                screen.repaint_theme()

    def flash(self, message, level="info"):
        if isinstance(self.screen, ChromeScreen):
            self.screen.flash(message, level)
        elif isinstance(self.screen, ModalScreen):
            self.notify(message, severity="error" if level == "error" else "information")
