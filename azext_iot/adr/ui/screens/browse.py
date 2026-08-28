# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""The generic, spec-driven table screen.

One screen serves every resource kind. Columns, sorting, drill-down targets and actions all
come from the kind's :class:`ResourceSpec`, so this module contains no per-kind branching —
that property is asserted by the tests and is what makes adding a kind a one-file change.
"""

from functools import partial
from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import RowDoesNotExist

from azext_iot.adr.ui.core.spec import STYLE_ACTIVE, STYLE_ERROR, ResourceSpec
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.core.table import TableModel
from azext_iot.adr.ui.theme import style_for

_LOADING_ROW_ID = "__loading__"
_LOADING_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class BrowseScreen(ChromeScreen):
    """A sortable, filterable table of one resource kind."""

    BINDINGS = [
        Binding("enter", "drill_down", "Open", show=True),
        Binding("slash", "start_filter", "Filter", show=True, key_display="/"),
        Binding("escape", "back", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("s", "sort", "Sort", show=True),
        Binding("ctrl+w", "toggle_wide", "Wide", show=True),
        Binding("y", "show_json", "JSON", show=True),
    ]

    def __init__(self, spec: ResourceSpec, source, scope: Optional[Dict[str, Any]] = None,
                 refresh_interval: Optional[int] = None, **kwargs):
        """``source`` supplies rows.

        Contract: ``source(scope, force=False) -> payloads``. ``force`` asks the caller's
        cache to bypass its interval; it never bypasses backoff.
        """
        super().__init__(**kwargs)
        self.spec = spec
        self.source = source
        self.scope = dict(scope or {})
        self.refresh_interval = refresh_interval
        self.model = TableModel(spec)
        self._filtering = False
        self._loading = False
        self._loading_frame = 0

    # -- composition -------------------------------------------------------

    def compose_content(self) -> ComposeResult:
        with Vertical(id="browse-body"):
            with Vertical(id="rows-pane"):
                yield DataTable(id="rows", cursor_type="row")
            yield Input(placeholder="filter...", id="filter-input")
            yield Static("", id="status-line")

    def on_mount(self) -> None:
        self.query_one("#rows-pane", Vertical).border_title = (
            self.spec.title_plural.lower()
        )
        self.query_one("#filter-input", Input).display = False
        self._build_columns()
        self.set_interval(0.1, self._animate_loading_row)
        self.refresh_rows()
        if self.refresh_interval:
            # Polling keeps the table current; the cache decides whether a tick costs a
            # request. Only the visible screen is mounted, so background screens are quiet.
            self.set_interval(self.refresh_interval, self.refresh_rows)

    # -- data --------------------------------------------------------------

    def refresh_rows(self, force: bool = False) -> None:
        """Load rows off the UI thread.

        The source is synchronous and, from M1, performs network I/O, so it must never run
        on the UI thread (design rule C1). ``exclusive`` gives rule C2 for free: a refresh
        scheduled while one is in flight replaces it rather than queueing behind it.
        """
        missing = self.spec.missing_scope(self.scope)
        if missing:
            self.model.fail(self._missing_scope_message(missing))
            self._repaint()
            return
        if self._loading:
            # Rule C2: drop the overlapping refresh rather than cancelling the request
            # already in flight, which on a slow collection could starve it forever.
            return
        self._loading = True
        self._loading_frame = 0
        self.model.begin_load()
        self._repaint()
        self.run_worker(
            partial(self._load, force),
            name=f"load-{self.spec.kind}",
            thread=True,
        )

    def _missing_scope_message(self, missing) -> str:
        readable = {
            "namespace_name": "a namespace",
            "resource_group_name": "a resource group",
            "registry_device_name": "a device",
            "group_name": "a group",
            "job_name": "a job",
            "certificate_authority_name": "a certificate authority",
        }
        # A resource group is implied by opening a namespace, so naming both is noise.
        if "namespace_name" in missing:
            missing = [key for key in missing if key != "resource_group_name"]
        names = [readable.get(key, key) for key in missing]
        if len(names) > 1:
            needed = f"{', '.join(names[:-1])} and {names[-1]}"
        else:
            needed = names[0]
        return f"Open {needed} first - {self.spec.title_plural.lower()} are listed within it."

    def _load(self, force: bool = False) -> None:
        """Worker body. Runs on a thread; touches the UI only via the app."""
        try:
            result = self.source(self.scope, force=force)
            payloads = list(result)
        except Exception as error:  # noqa: BLE001 - this worker is the error boundary
            self.app.call_from_thread(self._on_load_failed, str(error))
        else:
            self.app.call_from_thread(
                self._on_loaded,
                payloads,
                getattr(result, "error", None),
                getattr(result, "loaded_at", None),
            )

    def _on_loaded(self, payloads, error=None, loaded_at=None) -> None:
        self._loading = False
        self.model.apply(payloads, loaded_at=loaded_at)
        if error:
            self.model.fail(error)
            message = (
                f"refresh failed; showing cached data: {error}"
                if loaded_at is not None
                else f"refresh failed: {error}"
            )
            self.flash(message, "warning")
        self._repaint()

    def _on_load_failed(self, message: str) -> None:
        self._loading = False
        if self.spec.parent and "not found" in message.lower():
            message = (
                f"Could not open {self.spec.title_plural.lower()}: the parent resource "
                "is no longer available. Return and refresh the parent list."
            )
        self.model.fail(message)
        self._repaint()
        self.flash(message, "error")

    def _build_columns(self) -> None:
        table = self.query_one("#rows", DataTable)
        table.clear(columns=True)
        for column in self.model.columns:
            table.add_column(column.label, key=column.key, width=column.width)

    def _repaint(self) -> None:
        """Rebuild visible rows, preserving the cursor by row identity."""
        table = self.query_one("#rows", DataTable)
        selected = self.selected_row_id()

        table.clear()
        theme = getattr(self.app, "theme_tokens", None)
        loading_offset = 0
        if self._loading and self.model.columns:
            loading_cells = [self._loading_text(theme)]
            loading_cells.extend("" for _ in self.model.columns[1:])
            table.add_row(*loading_cells, key=_LOADING_ROW_ID)
            loading_offset = 1
        for row in self.model.rows:
            cells = []
            for index, value in enumerate(row.cells):
                token = row.styles[index]
                if row.status_style == STYLE_ERROR and index == 0:
                    token = STYLE_ERROR
                style = style_for(token, theme)
                if row.status_style == STYLE_ERROR and index == 0 and style:
                    style = f"bold {style}"
                cells.append(
                    Text(value, style=style)
                    if style else Text(value)
                )
            table.add_row(*cells, key=row.id)

        if selected is not None:
            index = self.model.index_of(selected)
            if index is not None:
                table.move_cursor(row=index + loading_offset)

        self.query_one("#status-line", Static).update(self.model.status_text())
        self._sync_chrome()

    def _loading_text(self, theme=None) -> Text:
        frame = _LOADING_FRAMES[self._loading_frame]
        return Text(
            f"{frame} Loading resources...",
            style=f"bold {style_for(STYLE_ACTIVE, theme)}",
        )

    def _animate_loading_row(self) -> None:
        if not self._loading or not self.model.columns:
            return
        self._loading_frame = (self._loading_frame + 1) % len(_LOADING_FRAMES)
        table = self.query_one("#rows", DataTable)
        try:
            table.get_row(_LOADING_ROW_ID)
        except RowDoesNotExist:
            return
        table.update_cell(
            _LOADING_ROW_ID,
            self.model.columns[0].key,
            self._loading_text(getattr(self.app, "theme_tokens", None)),
        )

    def _sync_chrome(self) -> None:
        app = self.app
        if hasattr(app, "sync_chrome"):
            app.sync_chrome(self)

    # -- selection ---------------------------------------------------------

    def selected_row_id(self) -> Optional[str]:
        table = self.query_one("#rows", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return (
                None
                if row_key.value == _LOADING_ROW_ID
                else row_key.value
            )
        except Exception:  # noqa: BLE001 - cursor can be transiently invalid mid-repaint
            return None

    def selected_payload(self) -> Optional[Dict[str, Any]]:
        row_id = self.selected_row_id()
        if row_id is None:
            return None
        row = next((r for r in self.model.rows if r.id == row_id), None)
        return row.payload if row else None

    # -- breadcrumbs -------------------------------------------------------

    def breadcrumb(self) -> str:
        return f"{self.spec.title_plural.lower()} ({self.model.total_count})"

    def guide(self):
        """Declared on the spec, so a new kind arrives already able to explain itself."""
        return self.spec.guide

    def hint_bindings(self) -> List[tuple]:
        """Hints derived from real bindings plus the spec's own children and actions."""
        hints = super().hint_bindings()
        hints.extend(
            (binding.key_display or binding.key, binding.description)
            for binding in self.app.BINDINGS
            if binding.action in ("new_setup", "onboard")
        )
        for child in self.spec.children:
            if child.key:
                hints.append((child.key, child.label.lower()))
        for action in self.spec.actions:
            if action.key:
                hints.append((action.key, action.label.lower()))
        return hints

    # -- actions -----------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_rows(force=True)

    def action_toggle_wide(self) -> None:
        self.model.toggle_wide()
        self._build_columns()
        self._repaint()

    def action_sort(self) -> None:
        """Sort by the column under the cursor; repeating reverses direction."""
        table = self.query_one("#rows", DataTable)
        columns = self.model.columns
        index = table.cursor_coordinate.column if table.row_count else 0
        if 0 <= index < len(columns):
            self.model.set_sort(columns[index].key)
            self._repaint()

    def action_start_filter(self) -> None:
        self._filtering = True
        field = self.query_one("#filter-input", Input)
        field.display = True
        field.value = self.model.filter_text
        field.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self.model.set_filter(event.value)
            self._repaint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            self._end_filter(keep=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """DataTable consumes Enter itself, so drill-down hangs off its message."""
        self.action_drill_down()

    def _end_filter(self, keep: bool) -> None:
        self._filtering = False
        field = self.query_one("#filter-input", Input)
        if not keep:
            self.model.clear_filter()
            field.value = ""
        field.display = False
        self.query_one("#rows", DataTable).focus()
        self._repaint()

    def action_back(self) -> None:
        """Escape precedence: leave the filter field, then clear a filter, then pop."""
        if self._filtering:
            self._end_filter(keep=True)
            return
        if self.model.filter_text:
            self._end_filter(keep=False)
            return
        self.app.pop_screen_safely()

    def action_drill_down(self) -> None:
        """Enter shows the hierarchy when there is a choice, else opens the only child."""
        if len(self.spec.children) > 1:
            payload = self.selected_payload()
            if payload is not None:
                self.app.open_overview(self.spec, payload, list(self.spec.children))
        elif self.spec.children:
            self._open_child(self.spec.children[0])

    def _open_child(self, child) -> None:
        payload = self.selected_payload()
        if payload is not None:
            self.app.open_child(self.spec, child, payload)

    def on_key(self, event) -> None:
        """Route a declared child key to that child collection."""
        if self._filtering:
            return
        for child in self.spec.children:
            if child.key and event.key == child.key:
                event.stop()
                event.prevent_default()
                self._open_child(child)
                return

    def action_show_json(self) -> None:
        payload = self.selected_payload()
        if payload is not None:
            self.app.open_detail(self.spec, payload)
