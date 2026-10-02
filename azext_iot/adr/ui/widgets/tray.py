# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Operations tray widget and the command-preview dialog."""

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from azext_iot.adr.ui.core.commands import wrap
from azext_iot.adr.ui.core.ops import OperationTracker, OpState
from azext_iot.adr.ui.core.spec import (
    STYLE_ACTIVE,
    STYLE_ERROR,
    STYLE_OK,
    STYLE_WARN,
)
from azext_iot.adr.ui.theme import style_for

_STATE_TOKENS = {
    OpState.RUNNING: STYLE_WARN,
    OpState.SUCCEEDED: STYLE_OK,
    OpState.FAILED: STYLE_ERROR,
}


def _state_style(widget, state: OpState) -> str:
    style = style_for(
        _STATE_TOKENS.get(state, ""),
        getattr(widget.app, "theme_tokens", None),
    )
    return f"bold {style}" if state is OpState.FAILED and style else style


class OperationsTray(Static):
    """One line describing in-flight and recently finished operations.

    Hidden entirely when nothing is tracked, so it costs no rows on a small terminal.
    """

    def __init__(self, tracker: Optional[OperationTracker] = None, **kwargs):
        super().__init__("", **kwargs)
        self.tracker = tracker
        self.text = ""

    def refresh_display(self) -> None:
        if self.tracker is None or not self.tracker.operations:
            self.text = ""
            self.display = False
            self.update("")
            return

        self.display = True
        operations = self.tracker.operations
        running = [op for op in operations if op.state is OpState.RUNNING]
        failed = [op for op in operations if op.state is OpState.FAILED]

        text = Text()
        if running:
            text.append(
                f"{len(running)} running  ",
                style=_state_style(self, OpState.RUNNING),
            )
        if failed:
            text.append(
                f"{len(failed)} failed  ",
                style=_state_style(self, OpState.FAILED),
            )
        head = operations[0]
        text.append(head.describe(), style=_state_style(self, head.state))
        if failed:
            text.append("   <o> details", style="dim")
        self.text = text.plain
        self.update(text)


class OperationsDialog(ModalScreen[None]):
    """Full list of tracked operations, with failure detail."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("o", "close", "Close", show=False),
    ]

    def __init__(self, tracker: OperationTracker):
        super().__init__()
        self.tracker = tracker

    def compose(self) -> ComposeResult:
        with Vertical(id="help-body"):
            yield Label(Text("operations", style="bold"), classes="modal-title")
            yield Static(self._format())
            with Horizontal(classes="modal-buttons"):
                yield Button("Dismiss finished", id="ack")
                yield Button("Close", id="close", variant="primary")

    def _format(self) -> Text:
        text = Text()
        operations = self.tracker.operations
        if not operations:
            return Text("no operations yet", style="dim")
        for operation in operations:
            text.append(
                f"{operation.describe()}\n",
                style=_state_style(self, operation.state),
            )
            if operation.command:
                text.append(
                    f"    {operation.command}\n",
                    style=style_for(
                        STYLE_ACTIVE,
                        getattr(self.app, "theme_tokens", None),
                    ),
                )
            if operation.detail:
                text.append(f"    {operation.detail}\n", style="dim")
        return text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ack":
            for operation in self.tracker.failed:
                self.tracker.acknowledge(operation.id)
            self.tracker.prune(keep_seconds=0)
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class CommandPreviewDialog(ModalScreen[bool]):
    """Show the equivalent `az` command and ask for confirmation.

    This is the trust anchor for every mutation: nothing runs until the user has seen the
    command that will run.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+y", "copy", "Copy", show=True),
    ]

    def __init__(self, title: str, command: str, note: str = "", danger: bool = False):
        super().__init__()
        self._title = title
        self._command = command
        self._note = note
        self._danger = danger

    def compose(self) -> ComposeResult:
        palette = getattr(self.app, "theme_palette", {})
        accent = palette.get("accent", "cyan")
        warning = palette.get("warning", "yellow")
        with Vertical(id="help-body"):
            yield Label(Text(self._title, style="bold"), classes="modal-title")
            yield Static(Text("this will run:", style="dim"))
            yield Static(
                Text(wrap(self._command), style=f"bold {accent}"),
                id="command-text",
            )
            if self._note:
                yield Static(Text(self._note, style=warning))
            yield Static(Text("ctrl+y copies the command", style="dim"))
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    "Run",
                    id="run",
                    variant="error" if self._danger else "primary",
                )

    def action_copy(self) -> None:
        try:
            self.app.copy_to_clipboard(self._command)
            self.notify("command copied")
        except Exception:  # noqa: BLE001 - clipboard is unavailable over plain SSH
            self.notify("clipboard unavailable", severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "run")

    def action_cancel(self) -> None:
        self.dismiss(False)
