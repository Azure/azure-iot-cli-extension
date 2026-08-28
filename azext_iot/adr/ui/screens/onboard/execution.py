# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the repo root for license information.
# --------------------------------------------------------------------------------------------

"""Dedicated execution workspace for a guided namespace-linking plan."""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from azext_iot.adr.ui.core import diagnostics
from azext_iot.adr.ui.core.spec import (
    STYLE_ACTIVE,
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_OK,
    STYLE_WARN,
    Guide,
)
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.theme import style_for


class ExecutionState(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    POLLING = "Polling"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    SKIPPED = "Skipped"

    @property
    def terminal(self) -> bool:
        return self in (
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.SKIPPED,
        )


@dataclass
class ExecutionRecord:
    item: Any
    state: ExecutionState = ExecutionState.PENDING
    detail: str = ""
    error: str = ""
    error_detail: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def elapsed(self) -> str:
        if self.started_at is None:
            return "--:--"
        end = self.finished_at or time.monotonic()
        seconds = max(0, int(end - self.started_at))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"


def execute_records(
    records: List[ExecutionRecord],
    session,
    context,
    waiter,
    update=lambda _record: None,
) -> bool:
    """Execute records sequentially; fail once and skip everything dependent."""
    failed = False
    for record in records:
        if failed:
            record.state = ExecutionState.SKIPPED
            record.detail = "Skipped because an earlier critical operation failed."
            update(record)
            continue
        record.state = ExecutionState.RUNNING
        record.started_at = time.monotonic()
        update(record)
        try:
            diagnostics.log(
                "execution: %s | %s",
                record.item.key,
                record.item.command,
            )
            poller = record.item.invoke(session, context)
            if poller is not None and hasattr(poller, "result"):
                waiter(poller)
            if record.item.verify is not None:
                record.state = ExecutionState.POLLING
                update(record)

                def notify(detail: str, _record=record):
                    _record.detail = detail
                    update(_record)

                record.item.verify(session, context, notify)
            record.state = ExecutionState.SUCCEEDED
        except Exception as error:  # noqa: BLE001 - execution boundary
            diagnostics.exception(
                "execution failed at '%s': %s",
                record.item.description,
                error,
            )
            record.state = ExecutionState.FAILED
            record.error = str(error) or error.__class__.__name__
            record.error_detail = str(getattr(error, "detail", "") or "")
            failed = True
        finally:
            record.finished_at = time.monotonic()
            update(record)
    return not failed


_STATE_STYLE = {
    ExecutionState.PENDING: STYLE_MUTED,
    ExecutionState.RUNNING: STYLE_ACTIVE,
    ExecutionState.POLLING: STYLE_WARN,
    ExecutionState.SUCCEEDED: STYLE_OK,
    ExecutionState.FAILED: STYLE_ERROR,
    ExecutionState.SKIPPED: STYLE_MUTED,
}


class ExecutionScreen(ChromeScreen):
    """Run a frozen plan sequentially and retain every operation result."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("j", "details", "Details", show=True),
    ]

    def __init__(self, session, context, items, on_complete=None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.context = context
        self.records: List[ExecutionRecord] = [
            ExecutionRecord(item=item) for item in items
        ]
        self.on_complete = on_complete
        self._running = False
        self._completed = False

    def compose_content(self) -> ComposeResult:
        with Vertical(id="execution-layout"):
            yield Static(id="execution-heading")
            yield Static(id="execution-summary")
            yield DataTable(id="execution-table", cursor_type="row")
            yield Static(id="execution-detail")

    def on_mount(self) -> None:
        table = self.query_one("#execution-table", DataTable)
        table.add_columns("#", "STATUS", "OPERATION", "TARGET", "DURATION")
        table.border_title = "linking plan"
        self._paint()
        table.focus()
        self._running = True
        self.run_worker(self._execute, thread=True, name="onboard-execution")

    def _style(self, token: str) -> str:
        return style_for(token, getattr(self.app, "theme_tokens", None))

    def _paint(self) -> None:
        table = self.query_one("#execution-table", DataTable)
        selected = table.cursor_coordinate.row if table.row_count else 0
        table.clear()
        for index, record in enumerate(self.records, start=1):
            table.add_row(
                str(index),
                Text(
                    record.state.value,
                    style=f"bold {self._style(_STATE_STYLE[record.state])}",
                ),
                record.item.description,
                record.item.target or "-",
                record.elapsed(),
                key=str(index - 1),
            )
        if self.records:
            table.move_cursor(row=min(selected, len(self.records) - 1))
        succeeded = sum(
            record.state is ExecutionState.SUCCEEDED for record in self.records
        )
        failed = next(
            (record for record in self.records if record.state is ExecutionState.FAILED),
            None,
        )
        if failed is not None:
            title = "LINKING FAILED"
            token = STYLE_ERROR
            summary = (
                f"{succeeded} succeeded · 1 failed · "
                f"{sum(r.state is ExecutionState.SKIPPED for r in self.records)} skipped"
            )
        elif self._completed:
            title = "LINKING COMPLETE"
            token = STYLE_OK
            summary = f"{succeeded} operations succeeded · namespace is ready"
        else:
            active = next(
                (
                    record
                    for record in self.records
                    if record.state in (ExecutionState.RUNNING, ExecutionState.POLLING)
                ),
                None,
            )
            title = "EXECUTING LINKING PLAN"
            token = STYLE_ACTIVE
            summary = (
                f"{succeeded} of {len(self.records)} complete"
                + (f" · {active.item.description}" if active else "")
            )
        self.query_one("#execution-heading", Static).update(
            Text(title, style=f"bold {self._style(token)}")
        )
        self.query_one("#execution-summary", Static).update(Text(summary, style="dim"))
        self._paint_detail()
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)

    def _paint_detail(self) -> None:
        table = self.query_one("#execution-table", DataTable)
        index = table.cursor_coordinate.row if table.row_count else 0
        if not (0 <= index < len(self.records)):
            self.query_one("#execution-detail", Static).update("")
            return
        record = self.records[index]
        text = Text()
        text.append(f"{record.item.category.upper()} · ", style="dim")
        text.append(record.item.description, style="bold")
        text.append("\n")
        if record.item.command:
            text.append(f"{record.item.command}\n", style=self._style(STYLE_ACTIVE))
        if record.detail:
            text.append(f"{record.detail}\n", style=self._style(STYLE_WARN))
        if record.error:
            text.append(f"{record.error}\n", style=f"bold {self._style(STYLE_ERROR)}")
        if record.error_detail:
            text.append(record.error_detail, style="dim")
        self.query_one("#execution-detail", Static).update(text)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "execution-table":
            self._paint_detail()

    def _execute(self) -> None:
        succeeded = execute_records(
            self.records,
            self.session,
            self.context,
            self.app.tracker._waiter,
            lambda _record: self.app.call_from_thread(self._paint),
        )
        self._running = False
        self._completed = succeeded
        self.app.call_from_thread(self._finished)

    def _finished(self) -> None:
        self._paint()
        if self.on_complete is not None:
            self.on_complete(self._completed)

    def action_details(self) -> None:
        self._paint_detail()

    def action_back(self) -> None:
        if self._running:
            self.notify(
                "Linking is still running. The execution page stays open until it finishes.",
                severity="warning",
            )
            return
        self.app.pop_screen_safely()

    def breadcrumb(self) -> str:
        return "guided setup / execution"

    def guide(self) -> Guide:
        return Guide(
            about=(
                "Every resource call, identity change, role grant, wait, link poll, "
                "and verification in this linking run."
            ),
            action="↑/↓ inspect operation · j details · Escape returns after completion",
            runs="Operations run in dependency order and stop at the first critical failure.",
            note="Successful Azure changes are preserved; remaining operations are skipped on failure.",
        )
