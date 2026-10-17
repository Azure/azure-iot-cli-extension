# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Operations are a full page shown on demand, never a persistent second pane."""

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from azext_iot.adr.ui.core.ops import OpState
from azext_iot.adr.ui.screens.base import FOCUS, HELP, ChromeScreen
from azext_iot.adr.ui.widgets.actions import scope_label
from azext_iot.adr.ui.widgets.minimal import ELLIPSIS, Clickable, Key, control_text, palette_of

_STATE_WIDTH = 14  # glyph, two spaces, state word: the label always starts in column 14


def _glyph_and_state(operation, colors):
    if operation.state is OpState.FAILED:
        return "\u2717", "failed", colors["error"]
    if operation.state is OpState.SUCCEEDED:
        return "\u2713", "succeeded", colors["dim"]
    if not operation.watching:
        return ELLIPSIS, "unwatched", colors["warning"]
    return ELLIPSIS, "running", colors["accent"]


class OperationRow(Horizontal):
    """``✗  failed     update one · message`` with the exact command underneath."""

    def __init__(self, index, **kwargs):
        super().__init__(**kwargs)
        self.index = index

    def compose(self):
        yield Static("", classes="op-mark")
        yield Static("", classes="op-body")

    def show(self, operation, selected):
        colors = palette_of(self)
        glyph, state, color = _glyph_and_state(operation, colors)
        mark = Text(no_wrap=True)
        mark.append(glyph, style=color)
        mark.append(f"  {state}", style=color)
        body = Text(f"{operation.label.lower()} {operation.target}", style=colors["text"])
        if operation.state is OpState.FAILED:
            body.append(f" \u00b7 {operation.error}", style=colors["error"])
        elif not operation.watching and not operation.state.is_terminal:
            body.append(" \u00b7 not watching; outcome unknown", style=colors["dim"])
        else:
            body.append(f" \u00b7 {operation.describe().split(' - ', 1)[-1]}", style=colors["dim"])
        # Only operations reviewed in another scope say where they run; the header names this one.
        if operation.context and operation.context != scope_label(getattr(self.app, "scope", {}) or {}):
            body.append(f"\nin {operation.context}", style=colors["warning"])
        if operation.command:
            body.append(f"\n{operation.command}", style=colors["dim"])
        if operation.detail:
            body.append(f"\n{operation.detail}", style=colors["dim"])
        self.query_one(".op-mark", Static).update(mark)
        self.query_one(".op-body", Static).update(body)
        self.set_class(selected, "-selected")

    def on_click(self, event):
        event.stop()
        self.screen.select(self.index)


class OperationsScreen(ChromeScreen):
    """This session's operations. Esc returns to the page underneath (``o`` toggles, app-wide).

    Re-read, stop watching and dismiss are title-row controls shown only when they apply; their
    letters are accelerators, never the only way in."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("x", "stop_watching", "Stop watching", show=False),
        Binding("r", "refresh_results", "Re-read", show=False),
        Binding("d", "dismiss_finished", "Dismiss finished", show=False),
        Binding("up", "move(-1)", "Up", show=False), Binding("down", "move(1)", "Down", show=False),
    ]

    _CONTROLS = (
        ("ops-reread", "Re-read", "screen.refresh_results"),
        ("ops-stop", "Stop watching", "screen.stop_watching"),
        ("ops-dismiss", "Dismiss finished", "screen.dismiss_finished"),
    )

    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker
        self._operations = tracker.operations
        running = [i for i, op in enumerate(self._operations) if op.state is OpState.RUNNING]
        self._selected = running[0] if running else 0

    def help_keys(self):
        return [("r", "re-read"), ("x", "stop watching"), ("d", "dismiss finished")]

    def compose_title_extras(self):
        for control_id, _label, action in self._CONTROLS:
            yield Clickable("", action=action, id=control_id, classes="page-control", focusable=True)

    def paint_controls(self):
        selected = self._operations[self._selected] if 0 <= self._selected < len(self._operations) else None
        applies = {
            "ops-reread": bool(self._operations),
            "ops-stop": bool(selected and selected.watching and not selected.state.is_terminal),
            "ops-dismiss": any(op.state.is_terminal for op in self._operations),
        }
        for control_id, label, _action in self._CONTROLS:
            self.show_control(control_id, applies[control_id], control_text(self, label))

    def compose_content(self):
        with Vertical(id="operation-rows"):
            for index, _operation in enumerate(self._operations):
                yield OperationRow(index)
        yield Static("No operations yet." if not self._operations else "", id="empty-line")
        yield Static(
            "This session only. Stop watching does not cancel Azure requests; results may still "
            "arrive. No automatic retry: re-read results before you review another action.",
            id="ops-note", classes="detail-label",
        )

    def on_mount(self):
        self.query_one("#empty-line", Static).display = not self._operations
        self._paint()
        self.focus_first_control()
        self.set_interval(1, self._paint)

    def _paint(self):
        for row in self.query(OperationRow).results():
            if row.index < len(self._operations):
                row.show(self._operations[row.index], row.index == self._selected)
        self.refresh_title()
        self.paint_controls()
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)

    def title_parts(self):
        return ("Operations", len(self._operations))

    def breadcrumb(self):
        return "operations"

    def keys(self):
        keys = [Key("move", "\u2191\u2193", "select")] if len(self._operations) > 1 else []
        return keys + [FOCUS, Key("close", "Esc", "back", "screen.close", essential=True), HELP]

    def select(self, index):
        if 0 <= index < len(self._operations):
            self._selected = index
            self._paint()

    def action_move(self, step):
        self.select(self._selected + step)

    def action_stop_watching(self):
        if 0 <= self._selected < len(self._operations):
            self._operations[self._selected].watching = False
        self._paint()

    def action_dismiss_finished(self):
        for operation in self.tracker.failed:
            self.tracker.acknowledge(operation.id)
        self.tracker.prune(keep_seconds=0)
        self.action_close()

    def action_refresh_results(self):
        self.app.store.clear()
        self.action_close()
        for screen in reversed(self.app.screen_stack):
            if hasattr(screen, "refresh_rows"):
                screen.refresh_rows(force=True)
                break

    def action_close(self):
        if self.app.screen is self:
            self.app.pop_screen()


#: Kept so callers written against the earlier modal name still resolve.
OperationsDialog = OperationsScreen
