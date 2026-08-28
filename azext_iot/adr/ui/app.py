# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""The radr application: page stack, command bar, chrome synchronisation.

M0 runs against the synthetic registry. M1 swaps in real kinds without changing this module
or the screens: only the registry passed in changes.
"""

from functools import partial
from typing import Any, Dict, List, Optional

from textual.app import App
from textual.binding import Binding

from azext_iot.adr.ui.core.commands import render as render_command
from azext_iot.adr.ui.core.ops import OperationTracker, make_session_waiter
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.core.spec import ChildRef, Registry, ResourceSpec
from azext_iot.adr.ui.core.store import Store
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.screens.onboard.pickers import ResourceCatalog
from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.adr.ui.theme import (
    APP_CSS,
    DEFAULT_THEME,
    HIGH_CONTRAST_THEME,
    LIGHT_THEME,
    RADR_THEMES,
    base_theme_for,
    normalize_theme,
    resolve_palette,
    resolve_theme,
)
from azext_iot.adr.ui.widgets.chrome import (
    Breadcrumbs,
    ContextBar,
    HintBar,
    InfoPanel,
    PageGuide,
)
from azext_iot.adr.ui.widgets.dialogs import TypeNameConfirmDialog
from azext_iot.adr.ui.widgets.tray import CommandPreviewDialog, OperationsDialog, OperationsTray


class RadrApp(App):
    """Terminal UI for Azure Device Registry namespaces."""

    CSS = APP_CSS
    TITLE = "radr"

    BINDINGS = [
        Binding("colon", "command_bar", "Command", show=True, key_display=":"),
        Binding("question_mark", "help", "Help", show=True, key_display="?"),
        Binding("w", "onboard", "Connect selected", show=True),
        Binding("n", "new_setup", "New setup", show=True),
        Binding("o", "operations", "Operations", show=True),
        # Single letters are claimed by drill-down children (d devices, g groups, ...),
        # so the guide toggle takes a modifier rather than shadowing one of them.
        Binding("ctrl+g", "toggle_guide", "Guide", show=True),
        Binding("ctrl+t", "toggle_theme", "Theme", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        cmd=None,
        resource_group_name: Optional[str] = None,
        namespace_name: Optional[str] = None,
        read_only: bool = False,
        refresh_interval: int = 5,
        theme_name: Optional[str] = None,
        registry: Optional[Registry] = None,
        session=None,
        store=None,
        log_path: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        for ui_theme in RADR_THEMES:
            self.register_theme(ui_theme)
        self.cmd = cmd
        self.read_only = read_only
        self.refresh_interval = refresh_interval
        self._theme_name = normalize_theme(theme_name)
        self.theme_tokens = resolve_theme(self._theme_name)
        self.theme_palette = resolve_palette(self._theme_name)
        self._base_theme = base_theme_for(self._theme_name)
        self.session = session
        self.store = store or Store(default_interval=refresh_interval)
        self.tracker = OperationTracker()
        self.last_key_pressed = ""
        self.log_path = log_path
        #: Whether page guides are hidden. Held on the application, not the screen, so a
        #: customer who dismisses it once is not shown it again on every drill-down.
        self.guides_collapsed = False

        if registry is not None:
            # Injected registry: used by tests and by the synthetic M0 walkthrough.
            self.registry = registry
        elif cmd is not None:
            self.session = self.session or Session(
                cmd,
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                read_only=read_only,
            )
            self.registry = build_registry(self.session)
            self.tracker = OperationTracker(make_session_waiter(self.session))
        else:
            self.registry = build_synthetic_registry()

        if self.session is not None:
            # The session owns scope; the app reads a snapshot rather than duplicating it.
            self.session.scope.resource_group_name = resource_group_name
            self.session.scope.namespace_name = namespace_name
            self.scope: Dict[str, Any] = self.session.scope.as_dict()
        else:
            self.scope = {
                "resource_group_name": resource_group_name,
                "namespace_name": namespace_name,
                "subscription": None,
            }

    # -- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        # Chrome colours come from the base theme so they agree with the status tokens.
        try:
            self.theme = self._base_theme
        except Exception:  # noqa: BLE001 - an unknown theme must not stop the UI
            pass
        self.set_interval(1.0, self._tick_operations)
        if self.session is not None:
            # Reading the profile touches disk, so it happens once, off the render path.
            self.run_worker(self._resolve_scope, thread=True, name="resolve-scope")
        root = self.registry.roots()[0]
        self.push_kind(root, self.scope)

    def _resolve_scope(self) -> None:
        self.session.resolve_subscription()
        self.call_from_thread(self._apply_resolved_scope)

    def _apply_resolved_scope(self) -> None:
        self.scope.update(self.session.scope.as_dict())
        # This arrives from a worker and may land before the first screen is mounted or
        # after the last one is popped during shutdown.
        if self.screen_stack:
            self.sync_chrome(self.screen)

    # -- navigation --------------------------------------------------------

    def push_kind(self, spec: ResourceSpec, scope: Dict[str, Any]) -> None:
        """Push a browse screen for ``spec``, reading through the cache."""
        self.push_screen(
            BrowseScreen(
                spec,
                self._source_for(spec),
                scope,
                refresh_interval=self.store.interval_for(spec),
            )
        )

    def _source_for(self, spec: ResourceSpec):
        """Bind a spec's lister to the cache, honouring the screen's source contract."""
        lister = spec.list or (lambda _scope: [])

        def source(scope: Dict[str, Any], force: bool = False):
            return self.store.fetch_result(spec, scope, lister, force=force)

        return source

    def open_child(self, parent: ResourceSpec, child: ChildRef, payload: Dict[str, Any]) -> None:
        """Drill from a parent row into one of its declared child kinds."""
        scope = dict(self._active_scope())
        # The parent spec declares what it contributes; the app needs no kind knowledge.
        scope.update(parent.child_scope(payload))
        self.open_scoped_child(child, scope)

    def open_scoped_child(self, child: ChildRef, scope: Dict[str, Any]) -> None:
        """Open a declared child when its parent scope has already been established."""
        try:
            child_spec = self.registry.get(child.kind)
        except Exception:  # noqa: BLE001 - a child pointing at an unregistered kind
            self.flash(f"'{child.kind}' is not available yet", "warning")
            return
        self.push_kind(child_spec, scope)

    def open_overview(
        self, parent: ResourceSpec, payload: Dict[str, Any], children: List[ChildRef]
    ) -> None:
        """Show every related child collection before choosing one."""
        scope = dict(self._active_scope())
        scope.update(parent.child_scope(payload))
        available = []
        for child in children:
            try:
                spec = self.registry.get(child.kind)
            except Exception:  # noqa: BLE001 - omit an unavailable optional child
                continue
            available.append((child, spec, self._source_for(spec)))
        if not available:
            self.flash("no related resource collections are available", "warning")
            return
        self.push_screen(OverviewScreen(parent, payload, scope, available))

    def open_detail(self, spec: ResourceSpec, payload: Dict[str, Any]) -> None:
        self.push_screen(DetailScreen(spec, payload))

    def pop_screen_safely(self) -> None:
        """Pop unless this is the last screen, where popping would leave nothing."""
        if len(self.screen_stack) <= 2:
            self.flash("press q to quit", "info")
            return
        self.pop_screen()
        self.sync_chrome(self.screen)

    # -- actions -----------------------------------------------------------

    def perform_action(self, spec: ResourceSpec, action, payload: Dict[str, Any],
                       scope: Dict[str, Any]) -> None:
        """Preview, confirm, then start an action, tracking it in the tray."""
        if self.read_only:
            self.flash("read-only session: state-changing actions are disabled", "warning")
            return
        if action.invoke is None:
            self.flash(f"'{action.label}' is not available yet", "warning")
            return

        name = str(spec.row_id(payload))
        command = self._command_for(spec, action, name, scope)

        def confirmed(approved: Optional[bool]) -> None:
            if not approved:
                return
            if action.destructive:
                self.push_screen(
                    TypeNameConfirmDialog(
                        f"{action.label} {spec.title.lower()}",
                        f"This cannot be undone. {spec.title} '{name}' will be {action.label.lower()}d.",
                        name,
                    ),
                    lambda ok: self._start_action(spec, action, payload, scope, command) if ok else None,
                )
            else:
                self._start_action(spec, action, payload, scope, command)

        self.push_screen(
            CommandPreviewDialog(
                f"{action.label} {spec.title.lower()} '{name}'",
                command,
                note="This is a long-running operation; progress appears in the tray."
                if not action.destructive else "This is destructive.",
                danger=action.destructive,
            ),
            confirmed,
        )

    def _command_for(self, spec: ResourceSpec, action, name: str, scope: Dict[str, Any]) -> str:
        """Render the equivalent command from the same scope the action will use."""
        if getattr(action, "command", None):
            return render_command(action.command, name=name, scope=scope,
                                  flags=("--yes",) if action.destructive else ())
        return f"az iot adr ns {spec.kind} {action.name} -n {name}"

    def _start_action(self, spec: ResourceSpec, action, payload: Dict[str, Any],
                      scope: Dict[str, Any], command: str) -> None:
        name = str(spec.row_id(payload))
        operation = self.tracker.start(
            label=action.label,
            target=name,
            command=command,
            refreshes=action.refreshes or (spec.kind,),
        )
        self.run_worker(
            partial(self._invoke_action, action, payload, scope, operation),
            name=f"action-{action.name}-{name}",
            thread=True,
        )
        self._refresh_tray()

    def _invoke_action(self, action, payload, scope, operation) -> None:
        """Worker body: start the mutation and drive its poller to a terminal state."""
        try:
            poller = action.invoke(self.session, scope, payload)
        except Exception as error:  # noqa: BLE001 - reported through the tray
            self.tracker.fail(operation, error)
        else:
            self.tracker.await_poller(operation, poller)
        self.call_from_thread(self._action_finished, operation)

    def _action_finished(self, operation) -> None:
        for kind in operation.refreshes:
            self.store.invalidate(kind)
        screen = self.screen
        if hasattr(screen, "refresh_rows"):
            screen.refresh_rows(force=True)
        level = "success" if operation.state.value == "succeeded" else "error"
        self.flash(operation.describe(), level)
        self._refresh_tray()

    def _tick_operations(self) -> None:
        self.tracker.prune()
        self._refresh_tray()

    def _refresh_tray(self) -> None:
        if not self.screen_stack:
            return
        try:
            tray = self.screen.query_one("#ops-tray", OperationsTray)
        except Exception:  # noqa: BLE001 - modal screens carry no tray
            return
        tray.tracker = self.tracker
        tray.refresh_display()

    def action_onboard(self, fresh: bool = False) -> None:
        """Open guided setup.

        By default it adopts whatever namespace is on screen. ``fresh`` starts with no
        namespace at all, so the flow begins by creating one.
        """
        if self.session is None:
            self.flash("guided setup needs a live session", "warning")
            return
        if fresh:
            self.push_screen(
                OnboardScreen(
                    self.session,
                    {
                        "subscription_id": self.scope.get("subscription_id"),
                        "subscription_name": self.scope.get("subscription"),
                    },
                    catalog=ResourceCatalog(self.cmd),
                )
            )
            return
        scope = dict(self._active_scope())
        # If the highlighted row names a namespace, set that one up. The spec declares
        # what a row contributes, so this needs no knowledge of any particular kind.
        scope.setdefault("subscription_id", self.scope.get("subscription_id"))
        scope.setdefault("subscription_name", self.scope.get("subscription"))
        screen = self.screen
        spec = getattr(screen, "spec", None)
        payload = screen.selected_payload() if hasattr(screen, "selected_payload") else None
        if spec is not None and payload is not None:
            scope.update(spec.child_scope(payload))
        # No namespace is a legitimate starting point: the flow can create one.
        self.push_screen(
            OnboardScreen(self.session, scope, catalog=ResourceCatalog(self.cmd))
        )

    def action_new_setup(self) -> None:
        """Start guided setup without inheriting the highlighted namespace."""
        self.action_onboard(fresh=True)

    def action_operations(self) -> None:
        self.push_screen(OperationsDialog(self.tracker))

    def _breadcrumbs(self) -> List[str]:
        """Trail derived from the live screen stack, so it can never desynchronise."""
        return [
            screen.breadcrumb()
            for screen in self.screen_stack
            if isinstance(screen, ChromeScreen)
        ]

    # -- chrome ------------------------------------------------------------

    def action_toggle_guide(self) -> None:
        """Hide or restore the page guide everywhere at once."""
        self.guides_collapsed = not self.guides_collapsed
        self.sync_chrome(self.screen)
        self.flash(
            "page guide hidden - press ctrl+g to bring it back" if self.guides_collapsed
            else "page guide shown",
            "info",
        )

    def action_toggle_theme(self) -> None:
        """Switch between the daylight and night palettes."""
        if self._theme_name == HIGH_CONTRAST_THEME:
            self.flash(
                "high-contrast theme remains enabled; restart with --theme dark or light "
                "to use the palette toggle",
                "info",
            )
            return
        self._theme_name = (
            DEFAULT_THEME if self._theme_name == LIGHT_THEME else LIGHT_THEME
        )
        self.theme_tokens = resolve_theme(self._theme_name)
        self.theme_palette = resolve_palette(self._theme_name)
        self._base_theme = base_theme_for(self._theme_name)
        self.theme = self._base_theme
        screen = self.screen
        if hasattr(screen, "refresh_view"):
            screen.refresh_view()
        elif hasattr(screen, "_repaint"):
            screen._repaint()
        elif hasattr(screen, "_paint"):
            screen._paint()
        elif hasattr(screen, "repaint_theme"):
            screen.repaint_theme()
        self.sync_chrome(screen)
        screen.refresh(layout=True)
        self.flash(
            "daylight theme" if self._theme_name == LIGHT_THEME else "night theme",
            "info",
        )

    def sync_chrome(self, screen) -> None:
        """Refresh chrome from the active screen. Called by screens after they repaint."""
        if not isinstance(screen, ChromeScreen):
            return
        scope = self._active_scope()
        try:
            screen.query_one("#context-bar", ContextBar).set_scope(
                subscription=scope.get("subscription") or self.scope.get("subscription"),
                resource_group=scope.get("resource_group_name"),
                namespace=scope.get("namespace_name"),
            )
            screen.query_one("#hint-bar", HintBar).set_bindings(screen.hint_bindings())
            screen.query_one("#breadcrumbs", Breadcrumbs).set_path(
                self._breadcrumbs() or [screen.breadcrumb()], screen.filter_text()
            )
            info = screen.query_one("#info-panel", InfoPanel)
            info.set_facts(self._facts(screen))
            guide = screen.query_one("#page-guide", PageGuide)
            page = screen.guide()
            guide.set_guide(page.rows() if page is not None else ())
            # The preference belongs to the person, not the page: dismissing it once
            # should not bring it back on the next drill-down.
            guide.set_collapsed(self.guides_collapsed)
        except Exception:  # noqa: BLE001 - chrome must never break the screen
            return

    def _active_scope(self) -> Dict[str, Any]:
        """Scope of the nearest screen that has one.

        The chrome describes what is on screen, so drilling in must widen it and popping
        must narrow it again. Walking the stack gives both for free.
        """
        for screen in reversed(self.screen_stack):
            scope = getattr(screen, "scope", None)
            if scope:
                return scope
        return self.scope

    def _facts(self, screen) -> List:
        facts = []
        spec = getattr(screen, "spec", None)
        if spec is not None:
            facts.append(("kind", spec.title_plural))
        model = getattr(screen, "model", None)
        if model is not None:
            facts.append(("rows", str(model.total_count)))
        if self.read_only:
            facts.append(("mode", "read-only"))
        if self.log_path:
            facts.append(("log", self.log_path))
        return facts

    def on_key(self, event) -> None:
        """Remember the last key so numeric bindings can tell 1 from 9."""
        self.last_key_pressed = event.key

    def flash(self, message: str, level: str = "info") -> None:
        screen = self.screen
        if isinstance(screen, ChromeScreen):
            screen.flash(message, level)

    # -- actions -----------------------------------------------------------

    def action_help(self) -> None:
        aliases = [
            (", ".join((spec.kind,) + tuple(spec.aliases)), spec.title_plural)
            for spec in self.registry.all()
        ]
        self.push_screen(HelpScreen(aliases))

    def action_command_bar(self) -> None:
        known = sorted(set(self.registry.aliases()))
        self.push_screen(CommandBar(known), self._run_command)

    def _run_command(self, token: Optional[str]) -> None:
        token = (token or "").strip()
        if not token:
            return
        if token in ("setup", "onboard"):
            self.action_onboard()
            return
        if token in ("new", "fresh"):
            # Start from nothing: the flow will create the namespace too.
            self.action_onboard(fresh=True)
            return
        if token in ("q", "quit", "exit"):
            self.exit()
            return
        if token in ("?", "help"):
            self.action_help()
            return
        spec = self.registry.resolve(token)
        if spec is None:
            self.flash(f"unknown command '{token}'", "warning")
            return
        # Jump from wherever the user is: a kind reached by alias must inherit the scope
        # currently on screen, or it would query with an empty namespace.
        self.push_kind(spec, dict(self._active_scope()))
