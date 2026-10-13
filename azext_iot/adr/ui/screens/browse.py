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

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import RowDoesNotExist, CellDoesNotExist

from azext_iot.adr.ui.core.io import run_io
from azext_iot.adr.ui.core.spec import ResourceSpec
from azext_iot.adr.ui.screens.base import FOCUS, HELP, QUIT, ChromeScreen
from azext_iot.adr.ui.core.table import LoadState, TableModel
from azext_iot.adr.ui.theme import FRAME_WIDTH, style_for
from azext_iot.adr.ui.widgets.minimal import ELLIPSIS, GUTTER, Clickable, Key, control_text, palette_of

_LOADING_ROW_ID = "__loading__"
_GUTTER_KEY = "gutter"
#: Only state-like cells carry colour; names, types and targets stay in the text colour.
_STATUS_COLUMNS = frozenset((
    "state", "status", "linking", "readiness", "membership", "enablement", "provisioning", "health",
))
#: Cells between columns. The cell padding is zero so the gutter can sit in column 0.
_COLUMN_GAP = 2


class BrowseScreen(ChromeScreen):
    """A sortable, filterable table of one resource kind."""

    BINDINGS = [
        Binding("enter", "drill_down", "Open", show=True),
        Binding("slash", "start_filter", "Search", show=True, key_display="/"),
        Binding("escape", "back", "Back", show=True),
        # Accelerators listed in help only: the table refreshes itself and a header click sorts.
        Binding("r", "refresh", "Refresh", show=False),
        Binding("s", "sort", "Sort", show=False),
        Binding("ctrl+w", "toggle_wide", "Wide", show=False),
        # While typing in the search field the arrows still move the table's selection; when the
        # table has focus it handles them itself before these are consulted.
        Binding("up", "move_match(-1)", "Previous match", show=False),
        Binding("down", "move_match(1)", "Next match", show=False),
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
        self._column_indices = []
        self._column_widths = {}

    # -- composition -------------------------------------------------------

    def compose_title_extras(self) -> ComposeResult:
        # Page controls sit beside the title and name their accelerator; Tab reaches them.
        yield Clickable("", action="app.actions", id="actions-control", classes="page-control", focusable=True)
        # Always visible: the search field is its own hint, so the key line does not repeat it.
        yield Static("", id="title-tail")
        yield Clickable("/", action="screen.start_filter", id="search-mark")
        yield Input(placeholder=f"search {self.spec.title_plural.lower()}", id="filter-input", compact=True)

    def compose_content(self) -> ComposeResult:
        yield DataTable(
            id="rows", cursor_type="row", cell_padding=0, zebra_stripes=False,
            cursor_foreground_priority="renderable",
        )
        yield Static("", id="empty-line")

    def on_mount(self) -> None:
        self._gutter_key = None
        self.query_one("#empty-line", Static).display = False
        self._build_columns()
        self.refresh_rows()
        self.query_one("#rows", DataTable).focus()
        if self.refresh_interval:
            # Polling keeps the table current; the cache decides whether a tick costs a
            # request. Only the visible screen is mounted, so background screens are quiet.
            self.set_interval(self.refresh_interval, self._refresh_visible)

    def _refresh_visible(self):
        if self.app.screen is self:
            self.refresh_rows()

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
        self.model.begin_load()
        self._repaint()
        if self.app.io_slots.locked():
            self.flash("Waiting for an available Azure request slot.", "warning")
        self.run_worker(
            self._load_rows(force),
            name=f"load-{self.spec.kind}",
        )

    async def _load_rows(self, force):
        try:
            await run_io(partial(self._load, force), self.app.io_slots)
        finally:
            self._loading = False

    def _missing_scope_message(self, missing) -> str:
        readable = {
            "namespace_name": "a namespace",
            "resource_group_name": "a resource group",
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
        app = self.app
        try:
            result = self.source(self.scope, force=force)
            payloads = list(result)
        except Exception as error:  # noqa: BLE001 - this worker is the error boundary
            app.post_from_thread(self._on_load_failed, str(error))
        else:
            app.post_from_thread(
                self._on_loaded,
                payloads,
                getattr(result, "error", None),
                getattr(result, "loaded_at", None),
            )

    def _on_loaded(self, payloads, error=None, loaded_at=None) -> None:
        if not self.is_attached:
            return
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
        if not self.is_attached:
            return
        self._loading = False
        if self.spec.parent and "not found" in message.lower():
            message = (
                f"Could not open {self.spec.title_plural.lower()}: the parent resource "
                "is no longer available. Return and refresh the parent list."
            )
        self.model.fail(message)
        self._repaint()
        self.flash(message, "error")

    def _frame_width(self) -> int:
        width = self.size.width or self.app.size.width
        return max(20, min(FRAME_WIDTH, width - 4))

    def _build_columns(self) -> None:
        """Fit declared columns in order; the name column takes whatever width is left.

        One cell is the selection gutter and one is kept for the scrollbar, so a long table
        never shifts its columns when it starts to scroll.
        """
        table = self.query_one("#rows", DataTable)
        table.clear(columns=True)
        self._gutter_key = None
        budget = self._frame_width() - 2
        columns = self.model.columns
        self._uniform = self._uniform_columns()
        # The name first, then state-like columns, then the rest in declared order; the
        # chosen columns are still displayed in declared order.
        order = sorted(
            (i for i in range(len(columns)) if i not in self._uniform),
            key=lambda i: (i != 0, columns[i].key not in _STATUS_COLUMNS, i),
        )
        widths = {}
        for index in order:
            wanted = columns[index].width or 20
            if index == 0:
                width = max(4, min(wanted, budget - _COLUMN_GAP))
            elif wanted + _COLUMN_GAP > budget:
                continue
            else:
                width = wanted
            widths[index] = width
            budget -= width + _COLUMN_GAP
        self._column_indices = sorted(widths)
        if 0 in widths:
            widths[0] += max(0, budget)
        self._column_widths = widths
        table.add_column("", key=_GUTTER_KEY, width=1)
        for index in self._column_indices:
            column = columns[index]
            table.add_column(column.label, key=column.key, width=widths[index] + _COLUMN_GAP)

    def _uniform_columns(self) -> frozenset:
        """``disambiguates`` columns that no two same-named rows need; details still show them."""
        if self.model.show_wide:
            return frozenset()
        return frozenset(
            index for index, column in enumerate(self.model.columns)
            if column.disambiguates and not self.model.distinguishes(index)
        )

    def on_resize(self, _event=None):
        if self.is_mounted:
            selected = self.selected_row_id()
            self._build_columns()
            self._repaint(selected)

    def fit_layout(self) -> None:
        super().fit_layout()
        try:
            self.query_one("#rows", DataTable).styles.max_height = self.content_rows()
        except Exception:  # noqa: BLE001 - not composed yet
            return

    def _repaint(self, selected: Optional[str] = None) -> None:
        """Rebuild visible rows, preserving the cursor by row identity."""
        table = self.query_one("#rows", DataTable)
        if selected is None:
            selected = self.selected_row_id()
        if self._uniform_columns() != getattr(self, "_uniform", None):
            self._build_columns()

        table.clear()
        self._gutter_key = None
        theme = getattr(self.app, "theme_tokens", None)
        loading_offset = 0
        if self._loading and self.model.columns:
            loading_cells = ["", self._loading_text()]
            loading_cells.extend("" for _ in self._column_indices[1:])
            table.add_row(*loading_cells, key=_LOADING_ROW_ID)
            loading_offset = 1
        for row in self.model.rows:
            cells = [""]
            for index, value in enumerate(row.cells):
                if index not in self._column_indices:
                    continue
                column = self.model.columns[index]
                style = style_for(row.styles[index], theme) if column.key in _STATUS_COLUMNS else ""
                cells.append(self._cell_text(value, style, self._column_widths.get(index)))
            table.add_row(*cells, key=row.id)

        if selected is not None:
            index = self.model.index_of(selected)
            if index is not None:
                table.move_cursor(row=index + loading_offset)
        self._paint_gutter()
        self._show_empty_state(table)
        self.refresh_title()
        self.refresh_keys()
        self._sync_chrome()

    def _cell_text(self, value, style: str, width: Optional[int] = None) -> Text:
        value = str(value)
        if width and len(value) > width:
            value = value[:max(0, width - 1)] + ELLIPSIS
        text = Text(value, style=Style.parse(style or ""), no_wrap=True)
        words = [term for term, negated in self.model.filter_terms() if not negated]
        if words:
            text.highlight_words(words, style=palette_of(self)["accent"], case_sensitive=False)
        return text

    def _show_empty_state(self, table: DataTable) -> None:
        """An empty table is one dim sentence, not a header over nothing."""
        line = self.query_one("#empty-line", Static)
        empty = table.row_count == 0 and self.model.state is not LoadState.LOADING
        colors = palette_of(self)
        if empty:
            if self.model.total_count and self.model.filter_text:
                message, color = (
                    f"No {self.spec.title_plural.lower()} match \u201c{self.model.filter_text}\u201d. Esc clears the search.",
                    colors["dim"],
                )
            else:
                failed = self.model.state is LoadState.FAILED
                message, color = self.model.status_text(), colors["error" if failed else "dim"]
            line.update(Text(message, style=Style.parse(color)))
        line.display = empty
        was_hidden = not table.display
        table.display = not empty
        if was_hidden and not empty and not self._filtering:
            table.focus()

    def _paint_gutter(self) -> None:
        """Move the accent bar to the cursor row; the row text keeps its own colour."""
        table = self.query_one("#rows", DataTable)
        current = None
        if table.row_count:
            try:
                current = table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
            except (RowDoesNotExist, CellDoesNotExist):
                current = None
        if current == self._gutter_key:
            return
        bar = Text(GUTTER, style=Style.parse(palette_of(self)["accent"]))
        for key, value in ((self._gutter_key, ""), (current, bar)):
            if key is None:
                continue
            try:
                table.update_cell(key, _GUTTER_KEY, value)
            except (RowDoesNotExist, CellDoesNotExist, KeyError):
                continue
        self._gutter_key = current

    def on_data_table_row_highlighted(self, _event) -> None:
        self._paint_gutter()
        # Actions and child keys depend on the selected row.
        self.refresh_keys()

    def _loading_text(self) -> Text:
        return Text(
            f"Loading resources{ELLIPSIS}",
            style=palette_of(self)["dim"],
        )

    # -- title and keys ----------------------------------------------------

    def title_parts(self):
        loaded = self.model.state in (LoadState.READY, LoadState.EMPTY) or self.model.total_count
        if not loaded:
            return (self.spec.title_plural, "")
        if self.model.filter_text:
            return (self.spec.title_plural, f"{self.model.row_count} of {self.model.total_count}")
        return (self.spec.title_plural, self.model.total_count)

    def refresh_title(self) -> None:
        super().refresh_title()
        try:
            mark = self.query_one("#search-mark", Clickable)
        except Exception:  # noqa: BLE001 - not composed yet
            return
        colors = palette_of(self)
        active = self._filtering or bool(self.model.filter_text)
        mark.update(Text("/ ", style=Style.parse(colors["accent" if active else "placeholder"])))

    def keys(self):
        if self._filtering:
            return [
                Key("move", "\u2191\u2193", "select match", essential=True),
                Key("keep", "Enter", "done", "screen.submit_filter", essential=True),
                Key("clear", "Esc", "clear", "screen.back", essential=True),
            ]
        # Only the standard keys: actions, search, scope and child lists are visible controls
        # (title row, header, details) that name their own accelerators.
        keys = []
        if self.selected_payload() is not None:
            keys.append(Key("open", "Enter", "open", "screen.drill_down"))
        keys.append(FOCUS)
        keys.append(Key("switch", ":", "go to", "app.command_bar"))
        if self.model.filter_text:
            keys.append(Key("clear", "Esc", "clear search", "screen.back", essential=True))
            if self.is_root():
                keys.append(QUIT)
        else:
            keys.append(self.back_key())
        return keys + [HELP]

    def paint_controls(self) -> None:
        has_actions = getattr(self.app, "has_actions", None)
        visible = bool(has_actions is not None and has_actions(self.spec, self.selected_payload()))
        self.show_control("actions-control", visible, control_text(self, "Actions"))

    def _sync_chrome(self) -> None:
        app = self.app
        if hasattr(app, "sync_chrome"):
            app.sync_chrome(self)

    # -- selection ---------------------------------------------------------

    def selected_row_id(self) -> Optional[str]:
        try:
            table = self.query_one("#rows", DataTable)
        except NoMatches:  # the key line is built before the table is composed
            return None
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return (
                None
                if row_key.value == _LOADING_ROW_ID
                else row_key.value
            )
        except (RowDoesNotExist, CellDoesNotExist):
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
        # Rebuilding the columns clears the table, so capture identity before that.
        selected = self.selected_row_id()
        self.model.toggle_wide()
        self._build_columns()
        self._repaint(selected)

    def sort_choices(self):
        """``(key, label)`` per displayed column, for the go-to list; the current one reverses."""
        choices = []
        for index in self._column_indices:
            column = self.model.columns[index]
            name = column.label.capitalize()
            choices.append((column.key, f"{name}, reverse order" if column.key == self.model.sort_key else name))
        return choices

    def sort_by(self, key: str) -> None:
        self.model.set_sort(key)
        self._repaint()

    def action_sort(self) -> None:
        """Optional ``s``: the ``Sort by`` list (also Go to, Sort by)."""
        self.app.action_sort_menu()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.column_key.value != _GUTTER_KEY:
            self.model.set_sort(event.column_key.value)
            self._repaint()

    def action_start_filter(self) -> None:
        field = self.query_one("#filter-input", Input)
        field.focus()
        field.cursor_position = len(field.value)
        self._set_filtering(True)

    def on_descendant_focus(self, event) -> None:
        if getattr(event.widget, "id", None) == "filter-input":
            self._set_filtering(True)

    def on_descendant_blur(self, event) -> None:
        # Clicking the table (or anywhere else) leaves the field; the search stays applied.
        if getattr(event.widget, "id", None) == "filter-input" and self._filtering:
            self._set_filtering(False)

    def _set_filtering(self, filtering: bool) -> None:
        if filtering != self._filtering:
            self._filtering = filtering
            self.refresh_title()
            self.refresh_keys()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Local only: typing narrows the loaded rows and never calls Azure."""
        if event.input.id == "filter-input":
            self.model.set_filter(event.value)
            self._repaint()

    def action_move_match(self, step: int) -> None:
        table = self.query_one("#rows", DataTable)
        if self._filtering and table.row_count:
            table.move_cursor(row=max(0, min(table.row_count - 1, table.cursor_row + step)))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            self._end_filter(keep=True)

    def action_submit_filter(self) -> None:
        if self._filtering:
            self._end_filter(keep=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """DataTable consumes Enter itself, so drill-down hangs off its message."""
        self.action_drill_down()

    def _end_filter(self, keep: bool) -> None:
        field = self.query_one("#filter-input", Input)
        if not keep:
            self.model.clear_filter()
            field.value = ""
        self._set_filtering(False)
        self._repaint()
        table = self.query_one("#rows", DataTable)
        if table.display:
            table.focus()
        else:
            self.set_focus(None)

    def action_back(self) -> None:
        """Escape clears the search (typing or not), and otherwise goes back."""
        if self._filtering or self.model.filter_text:
            self._end_filter(keep=False)
            return
        self.app.pop_screen_safely()

    def action_drill_down(self) -> None:
        """Enter or a row click opens details, replacing the table."""
        self.action_show_json()

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

    def repaint_theme(self) -> None:
        super().repaint_theme()
        self._gutter_key = None
        self._repaint()
