# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""A resource map for a selected parent.

Enter on a namespace should not make an arbitrary choice on the customer's behalf. This
screen shows every declared child collection together, loads a useful count and preview
for each, and keeps the direct child hotkeys as fast paths.
"""

from functools import partial
from typing import Dict, List, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

from azext_iot.adr.ui.core.spec import ChildRef, Guide, ResourceSpec
from azext_iot.adr.ui.screens.base import ChromeScreen


class OverviewScreen(ChromeScreen):
    """All child collections reachable from one selected resource."""

    BINDINGS = [
        Binding("enter", "open", "Open", show=True),
        Binding("escape", "back", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(
        self,
        parent: ResourceSpec,
        payload: dict,
        scope: dict,
        children: List[Tuple[ChildRef, ResourceSpec, object]],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.parent_spec = parent
        self.payload = payload
        self.scope = dict(scope)
        self.child_entries = list(children)
        self._results: Dict[str, Tuple[str, str]] = {}
        self._stale_parent_invalidated = False

    def compose_content(self) -> ComposeResult:
        yield DataTable(id="resource-map", cursor_type="row")
        yield Static("", id="status-line")

    def on_mount(self) -> None:
        table = self.query_one("#resource-map", DataTable)
        table.border_title = f"{self.parent_spec.title.lower()} resources"
        table.add_column("RESOURCE", key="resource", width=25)
        table.add_column("COUNT", key="count", width=8)
        table.add_column("DETAILS", key="details", width=58)
        table.add_column("OPEN", key="key", width=7)
        table.focus()
        # First entry may reuse rows already loaded elsewhere in the UI. Explicit `r`
        # below is the only path that bypasses the cache interval.
        self._start_load(force=False)

    def action_refresh(self) -> None:
        self._start_load(force=True)

    def _start_load(self, force: bool) -> None:
        self._results.clear()
        self._paint()
        for child, spec, source in self.child_entries:
            self.run_worker(
                partial(self._load_child, child, spec, source, force),
                thread=True,
                name=f"overview-{spec.kind}",
            )

    def _load_child(
        self, child: ChildRef, spec: ResourceSpec, source, force: bool
    ) -> None:
        try:
            result = source(self.scope, force=force)
            payloads = list(result)
        except Exception as error:  # noqa: BLE001 - one unavailable collection should not hide the rest
            self.app.call_from_thread(self._child_failed, child.kind, str(error))
        else:
            details = spec.summarize_rows(payloads)
            error = getattr(result, "error", None)
            if error:
                if not getattr(result, "stale", False):
                    self.app.call_from_thread(
                        self._child_failed,
                        child.kind,
                        error,
                    )
                    return
                details = f"Stale data: {error}"
            self.app.call_from_thread(
                self._child_loaded,
                child.kind,
                str(len(payloads)),
                details,
            )

    def _child_loaded(self, kind: str, count: str, details: str) -> None:
        if not self.is_mounted:
            return
        self._results[kind] = (count, details)
        self._paint()

    def _child_failed(self, kind: str, message: str) -> None:
        if not self.is_mounted:
            return
        self._results[kind] = ("!", message)
        self._paint()

    def _paint(self) -> None:
        table = self.query_one("#resource-map", DataTable)
        selected = self._selected_index()
        table.clear()
        loaded = 0
        for child, _spec, _source in self.child_entries:
            result = self._results.get(child.kind)
            count, details = result if result is not None else ("...", child.description)
            if result is not None:
                loaded += 1
            table.add_row(
                Text(child.label, style="bold"),
                Text(count, style="bold" if count not in ("...", "0") else "dim"),
                Text(details or child.description, style="dim"),
                Text(child.key or "enter", style="bold"),
                key=child.kind,
            )
        if selected is not None and table.row_count:
            table.move_cursor(row=min(selected, table.row_count - 1))
        self.query_one("#status-line", Static).update(
            self._status_text(loaded)
        )
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)

    def _status_text(self, loaded: int) -> str:
        if loaded < len(self.child_entries):
            return f"{loaded} of {len(self.child_entries)} collections loaded"
        failures = [
            detail
            for count, detail in self._results.values()
            if count == "!"
        ]
        if failures and len(failures) == len(self.child_entries) and all(
            "not found" in detail.lower() for detail in failures
        ):
            if not self._stale_parent_invalidated:
                self.app.store.invalidate(self.parent_spec.kind)
                self._stale_parent_invalidated = True
            return (
                "Namespace is unavailable. Azure returned a stale list entry; "
                "press Esc, then r to refresh namespaces."
            )
        return (
            f"{len(self.child_entries)} collections  \u00b7  "
            "0 means none are configured in this namespace"
        )

    def _selected_index(self) -> int:
        table = self.query_one("#resource-map", DataTable)
        return table.cursor_coordinate.row if table.row_count else 0

    def _selected_child(self):
        index = self._selected_index()
        return (
            self.child_entries[index][0]
            if 0 <= index < len(self.child_entries)
            else None
        )

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        self.action_open()

    def action_open(self) -> None:
        child = self._selected_child()
        if child is not None:
            self.app.open_scoped_child(child, self.scope)

    def on_key(self, event) -> None:
        for child, _spec, _source in self.child_entries:
            if child.key and event.key == child.key:
                event.stop()
                event.prevent_default()
                self.app.open_scoped_child(child, self.scope)
                return

    def action_back(self) -> None:
        self.app.pop_screen_safely()

    def breadcrumb(self) -> str:
        return (
            f"{self.parent_spec.title.lower()} "
            f"{self.parent_spec.row_id(self.payload)}"
        )

    def hint_bindings(self):
        hints = super().hint_bindings()
        hints.extend(
            (binding.key_display or binding.key, binding.description)
            for binding in self.app.BINDINGS
            if binding.action in ("new_setup", "onboard")
        )
        hints.extend(
            (child.key, child.label.lower())
            for child, _spec, _source in self.child_entries
            if child.key
        )
        return hints

    def guide(self) -> Guide:
        return Guide(
            about=(
                f"Resources inside '{self.parent_spec.row_id(self.payload)}'."
            ),
            action="\u2191/\u2193 choose  \u00b7  Enter open  \u00b7  or use the letter shortcut",
            runs="Read-only; collections load independently in the background.",
            note="Linked resources contains DPS, IoT Hubs and Software Updates.",
        )
