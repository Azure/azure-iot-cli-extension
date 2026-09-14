# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Generic table model: rows, diffing, sorting, filtering and load state.

The model owns what a table *is*; the screen owns how it looks. Refreshes are applied as
diffs so unchanged rows are not repainted and the user's cursor and marks survive an
update. This module is deliberately free of any UI framework import.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from azext_iot.adr.ui.core.spec import Column, Payload, ResourceSpec, state_style


class LoadState(Enum):
    """Distinguishing "not loaded yet" from "empty" is the point of this enum.

    Reporting an unloaded collection as empty is the worst failure mode of a live table.
    """

    NEVER_LOADED = "never_loaded"
    LOADING = "loading"
    READY = "ready"
    EMPTY = "empty"
    FAILED = "failed"
    STALE = "stale"

    @property
    def has_rows(self) -> bool:
        return self in (LoadState.READY, LoadState.STALE)


@dataclass(frozen=True)
class Row:
    """One rendered row: cell text plus the payload it came from."""

    id: str
    cells: Tuple[str, ...]
    styles: Tuple[Optional[str], ...]
    payload: Payload
    status_style: Optional[str] = None

    def cell(self, index: int) -> str:
        return self.cells[index] if 0 <= index < len(self.cells) else ""


@dataclass
class Diff:
    """What changed between two renders."""

    added: List[Row] = field(default_factory=list)
    updated: List[Row] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    reordered: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.updated or self.removed or self.reordered)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"Diff(added={len(self.added)}, updated={len(self.updated)}, "
            f"removed={len(self.removed)}, reordered={self.reordered})"
        )


class TableModel:
    """Holds the current rows for one resource kind and applies updates as diffs."""

    def __init__(self, spec: ResourceSpec, show_wide: bool = False):
        self.spec = spec
        self.show_wide = show_wide
        self.state = LoadState.NEVER_LOADED
        self.error: Optional[str] = None
        self.last_loaded_at: Optional[float] = None
        self.filter_text: str = ""
        self.marks: Set[str] = set()

        sort_key, descending = spec.default_sort()
        self.sort_key = sort_key
        self.sort_descending = descending

        self._payloads: Dict[str, Payload] = {}
        self._order: List[str] = []
        self._rows: Dict[str, Row] = {}

    # -- shape -------------------------------------------------------------

    @property
    def columns(self) -> List[Column]:
        return self.spec.visible_columns(self.show_wide)

    @property
    def headers(self) -> List[str]:
        return [column.label for column in self.columns]

    def toggle_wide(self) -> bool:
        self.show_wide = not self.show_wide
        self._rebuild_rows()
        return self.show_wide

    # -- content -----------------------------------------------------------

    @property
    def rows(self) -> List[Row]:
        """Visible rows, in sort order, after filtering."""
        return [self._rows[row_id] for row_id in self._visible_order()]

    @property
    def row_count(self) -> int:
        return len(self._visible_order())

    @property
    def total_count(self) -> int:
        return len(self._order)

    def row_at(self, index: int) -> Optional[Row]:
        order = self._visible_order()
        if 0 <= index < len(order):
            return self._rows[order[index]]
        return None

    def index_of(self, row_id: str) -> Optional[int]:
        order = self._visible_order()
        return order.index(row_id) if row_id in order else None

    # -- updates -----------------------------------------------------------

    def begin_load(self) -> None:
        """Mark a refresh as in flight without discarding what is already shown."""
        if self.state is LoadState.NEVER_LOADED:
            self.state = LoadState.LOADING

    def apply(self, payloads: Sequence[Payload], *, loaded_at: Optional[float] = None) -> Diff:
        """Replace contents with ``payloads``, returning only what changed."""
        previous_rows = dict(self._rows)
        previous_order = list(self._order)

        self._payloads = {}
        for payload in payloads:
            row_id = str(self.spec.row_id(payload))
            self._payloads[row_id] = payload

        self._rebuild_rows()
        self._resort()

        diff = Diff()
        for row_id, row in self._rows.items():
            if row_id not in previous_rows:
                diff.added.append(row)
            elif (
                previous_rows[row_id].cells != row.cells
                or previous_rows[row_id].styles != row.styles
                or previous_rows[row_id].status_style != row.status_style
            ):
                diff.updated.append(row)
        diff.removed = [row_id for row_id in previous_rows if row_id not in self._rows]
        diff.reordered = previous_order != self._order and not (diff.added or diff.removed)

        # Marks on rows that no longer exist would silently act on nothing later.
        self.marks &= set(self._rows)

        self.error = None
        self.last_loaded_at = loaded_at
        self.state = LoadState.READY if self._rows else LoadState.EMPTY
        return diff

    def fail(self, message: str) -> None:
        """Record a failed refresh, keeping any rows already on screen.

        Staleness is about having data, not about which state preceded the failure: a
        collection that has never produced rows is failed, not stale.
        """
        self.error = message
        self.state = LoadState.STALE if self._rows else LoadState.FAILED

    # -- sort and filter ---------------------------------------------------

    def set_sort(self, key: str, descending: Optional[bool] = None) -> None:
        if self.spec.column(key) is None:
            return
        if descending is None:
            descending = not self.sort_descending if key == self.sort_key else False
        self.sort_key, self.sort_descending = key, descending
        self._resort()

    def cycle_sort(self, key: str) -> None:
        self.set_sort(key)

    def set_filter(self, text: str) -> None:
        self.filter_text = (text or "").strip().lower()

    def clear_filter(self) -> None:
        self.filter_text = ""

    # -- marks -------------------------------------------------------------

    def toggle_mark(self, row_id: str) -> bool:
        if row_id in self.marks:
            self.marks.discard(row_id)
            return False
        if row_id in self._rows:
            self.marks.add(row_id)
            return True
        return False

    def clear_marks(self) -> None:
        self.marks.clear()

    def marked_payloads(self) -> List[Payload]:
        return [self._payloads[row_id] for row_id in self._order if row_id in self.marks]

    # -- internals ---------------------------------------------------------

    def _rebuild_rows(self) -> None:
        columns = self.columns
        self._rows = {
            row_id: Row(
                id=row_id,
                cells=tuple(column.text(payload) for column in columns),
                styles=tuple(
                    column.style(payload) if column.style else None for column in columns
                ),
                payload=payload,
                status_style=state_style(
                    payload,
                    "provisioningState",
                    "status",
                    "linkingState",
                ),
            )
            for row_id, payload in self._payloads.items()
        }
        self._order = [row_id for row_id in self._order if row_id in self._rows]
        self._order.extend(row_id for row_id in self._rows if row_id not in self._order)

    def _resort(self) -> None:
        column = self.spec.column(self.sort_key)
        if column is None:
            return

        def key(row_id: str) -> Tuple[int, Any]:
            value = column.sort_value(self._payloads[row_id])
            # None sorts last regardless of direction, so blanks never lead the table.
            return (1, "") if value is None else (0, value)

        try:
            self._order.sort(key=key, reverse=self.sort_descending)
        except TypeError:
            # Mixed types in a column: fall back to text ordering rather than crash.
            self._order.sort(
                key=lambda row_id: str(column.sort_value(self._payloads[row_id]) or ""),
                reverse=self.sort_descending,
            )

    def _visible_order(self) -> List[str]:
        if not self.filter_text:
            return self._order
        needle = self.filter_text
        return [
            row_id
            for row_id in self._order
            if any(needle in cell.lower() for cell in self._rows[row_id].cells)
        ]

    # -- presentation helpers ---------------------------------------------

    def status_text(self) -> str:
        """One line describing the current load state, for the screen to display."""
        if self.state is LoadState.NEVER_LOADED:
            return f"Loading {self.spec.title_plural.lower()}..."
        if self.state is LoadState.LOADING:
            return f"Loading {self.spec.title_plural.lower()}..."
        if self.state is LoadState.FAILED:
            return f"Could not load {self.spec.title_plural.lower()}: {self.error}"
        if self.state is LoadState.EMPTY:
            if "namespace_name" in self.spec.requires:
                return f"This namespace has no {self.spec.title_plural.lower()}."
            return f"No {self.spec.title_plural.lower()} in the current scope."
        if self.state is LoadState.STALE:
            return f"Showing last known data. Refresh failed: {self.error}"
        if self.filter_text and self.row_count != self.total_count:
            return f"{self.row_count} of {self.total_count} {self.spec.title_plural.lower()}"
        return f"{self.total_count} {self.spec.title_plural.lower()}"
