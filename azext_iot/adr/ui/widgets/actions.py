# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Compact action menu, input form, typed review and quit dialogs.

Presentation only: which actions are offered, how inputs parse, and when approval is possible
are decided exactly as before; these dialogs just draw them as the minimal design does.
"""

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from azext_iot.adr.ui.core.commands import render
from azext_iot.adr.ui.core.spec import Action
from azext_iot.adr.ui.screens.help import close_button, dialog_inner_width
from azext_iot.adr.ui.widgets.minimal import GUTTER, Key, PillButton, dialog_keys, fit_dialog_list, palette_of

_MENU_KEYS = (
    Key("move", "\u2191\u2193", "choose"),
    Key("select", "Enter", "select", "screen.choose"),
    Key("close", "Esc", "close", "screen.cancel", essential=True),
)


def _title(node, title, detail=""):
    colors = palette_of(node)
    text = Text(title, style=f"bold {colors['text']}", no_wrap=True, overflow="ellipsis")
    if detail:
        text.append(f" \u00b7 {detail}", style=f"bold {colors['dim']}")
    return text


def scope_label(scope):
    """``resource group · subscription``: where a list, review or operation is pinned."""
    return " \u00b7 ".join(str(part) for part in (
        scope.get("resource_group_name") or "all resource groups",
        scope.get("subscription") or scope.get("subscription_id") or "subscription unresolved",
    ))


def scope_context(scope, target=None):
    parts = [target] if target else []
    namespace = scope.get("namespace_name")
    if namespace and namespace != target:
        parts.append(namespace)
    parts.append(scope.get("resource_group_name") or "resource group unresolved")
    parts.append(scope.get("subscription") or scope.get("subscription_id") or "subscription unresolved")
    return " \u00b7 ".join(str(part) for part in parts)


def action_label(spec, action):
    """Collection actions name what they create (``Create device``); row actions act on the title row."""
    if action.collection and " " not in action.label:
        return f"{action.label} {spec.title.lower()}"
    return action.label


def menu_entries(spec, payload, read_only):
    """``(actions, notes)``: only actions that can run on this row in this session.

    Row actions need a selected row they apply to; collection actions need none. Nothing is listed
    disabled. A hidden action is explained in ``notes`` only when its rule teaches something (a
    state it waits for, a read-only session); the generic "not applicable" is not repeated.
    """
    actions, notes = [], []
    for action in spec.actions:
        if action.invoke is None or not action.is_relevant(payload):
            continue
        if read_only and action.mutation:
            notes.append("Read-only session: write actions are hidden.")
            continue
        if not action.collection:
            if not payload:
                continue
            if not action.is_applicable(payload):
                if action.unavailable != Action.unavailable:
                    notes.append(f"{action.label}: {action.unavailable[0].lower()}{action.unavailable[1:]}")
                continue
        actions.append(action)
    # The selected row's actions lead; collection actions follow in registry order.
    actions.sort(key=lambda action: action.collection)
    return actions, list(dict.fromkeys(notes))


def _primary(label, button_id, disabled=False):
    return PillButton(label, id=button_id, variant="primary", disabled=disabled)


class ActionMenu(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, spec, payload, read_only, scope=None):
        super().__init__()
        self.spec, self.payload, self.read_only = spec, payload, read_only
        self.scope = dict(scope or {})
        self._actions, self._notes = menu_entries(spec, payload, read_only)

    def compose(self) -> ComposeResult:
        name = (self.payload or {}).get("name") or ""
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static(_title(self, "Actions", name), classes="dialog-title")
            yield Static(scope_label(self.scope), classes="dialog-context")
            if self._actions:
                yield OptionList(*self._options(0), id="action-options")
                yield Static("", id="action-note", classes="dialog-note")
                yield Static("", id="action-command", classes="dialog-command")
            if self._notes or not self._actions:
                yield Static(Text("\n".join(self._notes) or "No actions for this resource."),
                             id="action-hidden", classes="dialog-note")
            with Horizontal(classes="dialog-buttons"):
                yield dialog_keys(*_MENU_KEYS)

    def _options(self, highlighted=None):
        colors = palette_of(self)
        width = dialog_inner_width(self)
        options = []
        for index, action in enumerate(self._actions):
            tag = "destructive" if action.destructive else "write" if action.mutation else "read"
            prompt = Text(no_wrap=True, overflow="ellipsis")
            prompt.append(GUTTER if index == highlighted else " ", style=colors["accent"])
            prompt.append(action_label(self.spec, action), style=colors["text"])
            prompt.append(" " * max(1, width - len(prompt) - len(tag)))
            prompt.append(tag, style=colors["error" if action.destructive else "dim"])
            options.append(Option(prompt, id=action.name))
        return options

    def on_mount(self):
        if self._actions:
            options = self.query_one(OptionList)
            options.focus()
            options.highlighted = 0
            self._describe(0)
            self.call_after_refresh(fit_dialog_list, self, "#action-options")

    def on_resize(self, _event):
        self.call_after_refresh(fit_dialog_list, self, "#action-options")

    def on_option_list_option_highlighted(self, event):
        options = self.query_one(OptionList)
        for index, option in enumerate(self._options(event.option_index)):
            options.replace_option_prompt_at_index(index, option.prompt)
        self._describe(event.option_index)

    def _describe(self, index):
        colors = palette_of(self)
        action = self._actions[index]
        note = self.query_one("#action-note", Static)
        note.update(Text(action.note))
        note.display = bool(action.note)
        command = self._preview(action)
        self.query_one("#action-command", Static).update(Text(command, style=colors["text"]))
        self.query_one("#action-command", Static).display = bool(command)

    def _preview(self, action):
        """The command Review will show, built the same way, for row actions whose arguments are
        all known. Adds and forms collect input first, so they show no (placeholder) command."""
        if action.collection or action.fields or not self.payload or not (action.command or action.preview):
            return ""
        scope = dict(self.scope)
        try:
            scope.update(self.spec.child_scope(self.payload))
            if action.preview is not None:
                return action.preview(scope, dict(self.payload))
            name = str(self.payload.get("name") or self.spec.row_id(self.payload))
            return render(action.command, name=name, scope=scope, flags=("--yes",) if action.destructive else ())
        except Exception:  # noqa: BLE001 - previews never block the menu
            return ""

    def on_option_list_option_selected(self, event):
        self.dismiss(self.spec.action(event.option.id))

    def action_choose(self):
        """Enter, or a click on ``Enter select``: the highlighted action."""
        if not self._actions:
            return
        index = self.query_one(OptionList).highlighted
        if index is not None:
            self.dismiss(self._actions[index])

    def action_cancel(self):
        self.dismiss(None)


class ActionForm(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, action, payload=None, context="", title=None):
        super().__init__()
        self.action = action
        self.context = context
        self.form_title = title or action.label
        self.initial = {
            field.key: field.current(payload or {}) if action.name == "update" else field.default
            for field in action.fields
        }

    def compose(self):
        colors = palette_of(self)
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static(_title(self, self.form_title), classes="dialog-title")
            if self.context:
                yield Static(self.context, classes="dialog-context")
            if self.action.note:
                yield Static(Text(self.action.note), classes="dialog-note")
            for field in self.action.fields:
                with Horizontal(classes="field-row"):
                    yield Static(Text(field.label, style=colors["text"]), classes="field-label")
                    yield Input(value=self.initial[field.key], placeholder="optional" if field.optional else "",
                                id=f"field-{field.key}")
                if field.choices:
                    yield Static(f"choose {', '.join(field.choices)}", classes="field-hint")
            yield Static("", id="form-error")
            with Horizontal(classes="dialog-buttons"):
                yield _primary("Review \u21b5", "review")
                yield close_button(self, "Cancel", "cancel")

    def on_mount(self):
        self.query_one("#form-error", Static).display = False
        fields = self.query(Input)
        if fields:
            fields.first().focus()

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
            line = self.query_one("#form-error", Static)
            line.update(Text(str(error)))
            line.display = True
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
        colors = palette_of(self)
        destructive = self.action.destructive
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static(_title(self, f"{self.action.label}?"), classes="dialog-title")
            yield Static(scope_context(self.scope, self.target_name), classes="dialog-context")
            yield Static(Text(self.command, style=colors["text"]), id="command-text", classes="dialog-command")
            note = " ".join(part for part in (
                self.action.note,
                "Stopping watching does not cancel Azure requests. No automatic retries.",
            ) if part)
            yield Static(Text(note), classes="dialog-note")
            if destructive:
                prompt = Text("Type ", style=colors["dim"])
                prompt.append(self.target_name, style=f"bold {colors['text']}")
                yield Static(prompt, classes="dialog-text")
                yield Input(id="confirm-name")
                yield Static("", id="confirm-error", classes="dialog-note")
            with Horizontal(classes="dialog-buttons"):
                yield _primary(f"{self.action.label} \u21b5" if destructive else self.action.label,
                               "confirm", disabled=destructive)
                yield close_button(self, "Cancel", "cancel")
                yield Static(
                    "Cannot be undone." if destructive
                    else "Writes to Azure." if self.action.mutation else "Read only."
                )

    def on_mount(self):
        """Destructive reviews start in the typed-name field; others on the primary button, so Enter runs it."""
        if self.action.destructive:
            self.query_one("#confirm-error", Static).display = False
        self.query_one("#confirm-name" if self.action.destructive else "#confirm").focus()

    def on_input_changed(self, event):
        self.query_one("#confirm", Button).disabled = event.value != self.target_name
        self.query_one("#confirm-error", Static).display = False

    def on_input_submitted(self, event):
        """Enter in the typed-name field approves only once the exact name was typed."""
        if event.value == self.target_name:
            self.dismiss(True)
            return
        error = self.query_one("#confirm-error", Static)
        # The exact name is on the line above; the note stays short enough for 80 columns.
        error.update(Text("Name does not match; nothing was sent.", style=Style.parse(palette_of(self)["warning"])))
        error.display = True

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
        colors = palette_of(self)
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static(_title(self, "Quit radar?"), classes="dialog-title")
            yield Static(
                f"{len(self.operations)} operation(s) still running. Quitting stops watching, "
                "not requests already submitted to Azure. Unstarted steps may not run. "
                "Nothing is rolled back; verify current resource state before retrying.",
                classes="dialog-note",
            )
            yield Static(Text("\n".join(operation.command for operation in self.operations), style=colors["text"]),
                         classes="dialog-command")
            with Horizontal(classes="dialog-buttons"):
                # The safe choice is the filled, focused default; leaving is one Tab away.
                yield _primary("Keep watching", "cancel")
                yield PillButton("Quit anyway", id="quit-anyway")

    def on_mount(self):
        """Start on the safe choice: Enter keeps watching; Tab then Enter quits anyway."""
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "quit-anyway")

    def action_cancel(self):
        self.dismiss(False)
