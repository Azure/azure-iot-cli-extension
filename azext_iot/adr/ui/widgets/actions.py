# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Mouse and keyboard action menus, input forms, and a single approval surface."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option


class ActionMenu(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, spec, payload, read_only):
        super().__init__()
        self.spec, self.payload, self.read_only = spec, payload, read_only

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Label("Actions", classes="modal-title")
            options = []
            for action in self.spec.actions:
                reason = ""
                if self.read_only and action.mutation:
                    reason = "Read-only session"
                elif not action.collection and (not self.payload or not action.is_applicable(self.payload)):
                    reason = action.unavailable
                effect = "destructive" if action.destructive else "write" if action.mutation else "read"
                options.append(Option(
                    Text(f"{action.label} · {effect}\n{reason or action.note}"),
                    id=action.name, disabled=bool(reason) or action.invoke is None,
                ))
            if options:
                yield OptionList(*options, id="action-options")
            else:
                yield Static("No actions for this resource kind.")
            yield Button("Cancel", id="cancel")

    def on_option_list_option_selected(self, event):
        self.dismiss(self.spec.action(event.option.id))

    def on_button_pressed(self, _event):
        self.action_cancel()

    def action_cancel(self):
        self.dismiss(None)


class ActionForm(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, action, payload=None):
        super().__init__()
        self.action = action
        self.initial = {
            field.key: field.current(payload or {}) if action.name == "update" else field.default
            for field in action.fields
        }

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label(self.action.label, classes="modal-title")
            yield Static(Text(self.action.note))
            for field in self.action.fields:
                yield Label(field.label)
                yield Input(value=self.initial[field.key], placeholder=field.label, id=f"field-{field.key}")
            yield Static("", id="form-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Review", id="review", variant="primary")

    def on_input_submitted(self, _event):
        self.submit()

    def on_button_pressed(self, event):
        if event.button.id == "review":
            self.submit()
        else:
            self.action_cancel()

    def submit(self):
        try:
            values = {field.key: field.parse(self.query_one(f"#field-{field.key}", Input).value)
                      for field in self.action.fields}
            if self.action.name == "update" and all(
                self.query_one(f"#field-{field.key}", Input).value == self.initial[field.key]
                for field in self.action.fields
            ):
                raise ValueError("Nothing changed. Edit a value or cancel.")
        except ValueError as error:
            self.query_one("#form-error", Static).update(Text(str(error)))
            return
        self.dismiss(values)

    def action_cancel(self):
        self.dismiss(None)


class ReviewDialog(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, action, name, command, scope):
        super().__init__()
        self.action, self.target_name, self.command, self.scope = action, name, command, scope

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label(self.action.label, classes="modal-title")
            yield Static(Text(
                f"Subscription: {self.scope['subscription_id']}\n"
                f"Resource group: {self.scope.get('resource_group_name')}\n"
                f"Namespace: {self.scope.get('namespace_name') or self.target_name}"
            ))
            yield Static(Text(self.command), id="command-text")
            yield Static(Text(self.action.note))
            yield Static("Stopping watching does not cancel Azure requests. No automatic retries.")
            if self.action.destructive:
                yield Label(Text(f"Type {self.target_name} to confirm"))
                yield Input(id="confirm-name")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", id="confirm", variant="primary", disabled=self.action.destructive)

    def on_input_changed(self, event):
        self.query_one("#confirm", Button).disabled = event.value != self.target_name

    def on_button_pressed(self, event):
        if event.button.id != "confirm":
            self.action_cancel()
        elif not self.action.destructive or self.query_one("#confirm-name", Input).value == self.target_name:
            self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class QuitDialog(ModalScreen):
    BINDINGS = [("escape", "cancel", "Keep watching")]

    def __init__(self, operations):
        super().__init__()
        self.operations = operations

    def compose(self):
        with VerticalScroll(id="help-body"):
            yield Label("Quit radar?", classes="modal-title")
            yield Static(
                f"{len(self.operations)} operation(s) still running. Quitting stops watching, "
                "not requests already submitted to Azure. Unstarted steps may not run. "
                "Nothing is rolled back; verify current resource state before retrying."
            )
            yield Static(Text("\n\n".join(operation.command for operation in self.operations)))
            with Horizontal(classes="modal-buttons"):
                yield Button("Keep watching", id="cancel")
                yield Button("Quit anyway", id="quit-anyway", variant="primary")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "quit-anyway")

    def action_cancel(self):
        self.dismiss(False)
