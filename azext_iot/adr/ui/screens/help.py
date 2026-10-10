# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Discoverable resource switcher and keyboard/mouse reference."""

from rich.text import Text
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static

GLOBAL_KEYS = (
    (":", "resource switcher"), ("/", "search; prefix ! to invert"), ("enter", "details"),
    ("esc", "back / cancel"), ("a", "contextual actions"), ("o", "operations"),
    ("r", "refresh table"), ("s", "sort"), ("ctrl+w", "wide columns"), ("q", "quit"),
)


class HelpScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close"), ("question_mark", "close", "Close")]

    def __init__(self, aliases=()):
        super().__init__()
        self._aliases = aliases

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label("radar · help", classes="modal-title")
            yield Static(self._format(GLOBAL_KEYS))
            yield Static("Click a row to select and open details. Arrow keys select without opening.")
            yield Static("Selectors, footer shortcuts, child links and dialogs are clickable.")
            yield Static("Use az iot adr ns setup for onboarding (when installed). Radar does not run setup.")
            yield Static(self._format(self._aliases))
            yield Button("Close", id="close")

    @staticmethod
    def _format(rows):
        return Text("\n".join(f"{key:10} {description}" for key, description in rows))

    def on_button_pressed(self, _event):
        self.action_close()

    def action_close(self):
        self.dismiss(None)


class CommandBar(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, known=()):
        super().__init__()
        self._known = sorted(set(known))

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label("Resources", classes="modal-title")
            yield Input(placeholder="Type a resource kind", id="command-input")
            yield OptionList(*self._known, id="resource-options")
            yield Button("Cancel", id="cancel")

    def on_mount(self):
        self.query_one(Input).focus()

    def on_input_changed(self, event):
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options([kind for kind in self._known if event.value.casefold() in kind.casefold()])

    def on_input_submitted(self, event):
        matches = [kind for kind in self._known if event.value.casefold() in kind.casefold()]
        self.dismiss(matches[0] if len(matches) == 1 else event.value.strip())

    def on_option_list_option_selected(self, event):
        self.dismiss(str(event.option.prompt))

    def on_button_pressed(self, _event):
        self.action_cancel()

    def action_cancel(self):
        self.dismiss("")
