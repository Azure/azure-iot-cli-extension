# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Operations are disclosed on demand, never a persistent second pane."""

from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option


class OperationsDialog(ModalScreen):
    BINDINGS = [
        ("escape", "close", "Close"), ("o", "close", "Close"),
        ("x", "stop_watching", "Stop watching"), ("r", "refresh_results", "Re-read"),
        ("R", "refresh_results", "Re-read"),
    ]

    def __init__(self, tracker):
        super().__init__()
        self.tracker = tracker
        self._operations = tracker.operations

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label("Operations", classes="modal-title")
            yield OptionList(*(Option(Text(op.describe()), id=str(op.id)) for op in self._operations),
                             id="operation-list")
            yield Static(self._format(), id="operation-details")
            yield Static(
                "x stops foreground watching, not Azure requests. Background results may still arrive. "
                "No automatic retry; re-read results before reviewing another action."
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Stop watching", id="stop-watch")
                yield Button("Re-read", id="re-read")
                yield Button("Dismiss finished", id="ack")
                yield Button("Close", id="close", variant="primary")

    def _format(self):
        return Text("\n\n".join(
            f"{op.describe()}\n{op.command}\n{op.detail or ''}" for op in self._operations
        ) or "No operations yet.")

    def on_button_pressed(self, event):
        if event.button.id == "stop-watch":
            self.action_stop_watching()
        elif event.button.id == "re-read":
            self.action_refresh_results()
        else:
            if event.button.id == "ack":
                for operation in self.tracker.failed:
                    self.tracker.acknowledge(operation.id)
                self.tracker.prune(keep_seconds=0)
            self.action_close()

    def action_stop_watching(self):
        index = self.query_one("#operation-list", OptionList).highlighted
        if index is not None:
            self._operations[index].watching = False
        self.query_one("#operation-details", Static).update(self._format())

    def action_refresh_results(self):
        self.app.store.clear()
        self.dismiss(None)
        for screen in reversed(self.app.screen_stack):
            if hasattr(screen, "refresh_rows"):
                screen.refresh_rows(force=True)
                break

    def action_close(self):
        self.dismiss(None)
