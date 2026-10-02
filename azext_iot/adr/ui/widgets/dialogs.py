# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Modal dialogs: confirmation, type-the-name confirmation, and error display."""

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ModalBox(Vertical):
    """Bordered container shared by every dialog, so they look and behave alike."""


class ConfirmDialog(ModalScreen[bool]):
    """Yes/no confirmation. Returns True only on explicit confirmation."""

    BINDINGS = [("escape", "dismiss_false", "Cancel")]

    def __init__(self, title: str, message: str, confirm_label: str = "Confirm", danger: bool = False):
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._danger = danger

    def compose(self) -> ComposeResult:
        box = ModalBox(classes="danger" if self._danger else "")
        with box:
            yield Label(Text(self._title, style="bold"), classes="modal-title")
            yield Static(self._message)
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    self._confirm_label,
                    id="confirm",
                    variant="error" if self._danger else "primary",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)


class TypeNameConfirmDialog(ModalScreen[bool]):
    """Destructive confirmation requiring the resource name to be typed.

    A higher bar than yes/no, which is appropriate for irreversible fleet operations.
    """

    BINDINGS = [("escape", "dismiss_false", "Cancel")]

    def __init__(self, title: str, message: str, expected_name: str):
        super().__init__()
        self._title = title
        self._message = message
        self._expected = expected_name

    def compose(self) -> ComposeResult:
        with ModalBox(classes="danger"):
            yield Label(Text(self._title, style="bold"), classes="modal-title")
            yield Static(self._message)
            yield Static(
                Text.assemble(("Type ", "dim"), (self._expected, "bold"), (" to confirm:", "dim"))
            )
            yield Input(placeholder=self._expected, id="name-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Delete", id="confirm", variant="error", disabled=True)

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#confirm", Button).disabled = event.value.strip() != self._expected

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() == self._expected:
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "confirm":
            self.dismiss(False)
        elif self.query_one("#name-input", Input).value.strip() == self._expected:
            self.dismiss(True)

    def action_dismiss_false(self) -> None:
        self.dismiss(False)


class ErrorDialog(ModalScreen[None]):
    """Failure detail that the flash line is too small to carry."""

    BINDINGS = [("escape", "dismiss_none", "Close"), ("enter", "dismiss_none", "Close")]

    def __init__(self, title: str, message: str, detail: Optional[str] = None):
        super().__init__()
        self._title = title
        self._message = message
        self._detail = detail

    def compose(self) -> ComposeResult:
        with ModalBox(classes="danger"):
            yield Label(
                Text(self._title, style="bold"),
                classes="modal-title",
            )
            yield Static(self._message)
            if self._detail:
                yield Static(Text(self._detail, style="dim"))
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)
