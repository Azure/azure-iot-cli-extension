# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Compact resource switcher and keyboard/mouse reference dialogs."""

from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from azext_iot.adr.ui.widgets.minimal import (
    ELLIPSIS, GUTTER, Key, PillButton, dialog_keys, fit_dialog_list, palette_of,
)

#: Everything can be done with these: Tab reaches every control a click reaches.
BASIC_KEYS = (
    ("Tab", "next control"), ("\u21e7Tab", "previous control"), ("\u2191\u2193", "move, choose"),
    ("Enter", "open, accept"), ("Space", "press control"), ("Esc", "back, close, clear"),
    ("q", "quit"), ("?", "this help"),
)
#: Optional accelerators; each also has a visible control or happens on its own.
SHORTCUTS = (
    ("/", "search; !word hides"), ("a", "actions"), (":", "go to a resource"), ("@", "resource group"),
    ("o", "operations"), ("y", "raw JSON (details)"), ("r", "refresh now"), ("s", "sort by\u2026"),
    ("ctrl+w", "wide columns"), ("ctrl+t", "light / dark"), ("ctrl+r", "reload picker list"),
)
GLOBAL_KEYS = BASIC_KEYS + SHORTCUTS

_SWITCH_KEYS = (
    Key("move", "\u2191\u2193", "choose"),
    Key("switch", "Enter", "switch", "screen.choose"),
    Key("close", "Esc", "close", "screen.cancel", essential=True),
)

_DIALOG_WIDTH = 64
_DIALOG_CHROME = 6  # round border and two-cell padding on each side


def dialog_inner_width(node) -> int:
    width = getattr(getattr(node, "app", None), "size", None)
    width = width.width if width else 80
    return max(20, min(_DIALOG_WIDTH, width - 4) - _DIALOG_CHROME)


def close_button(node, label="Close", button_id="close"):
    """A text-only button: label in the text colour, its key in the accent colour."""
    colors = palette_of(node)
    text = Text(label, style=colors["text"])
    text.append(" Esc", style=colors["accent"])
    return PillButton(text, id=button_id)


class HelpScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close"), ("question_mark", "close", "Close")]

    def __init__(self, aliases=(), page_keys=()):
        super().__init__()
        self._aliases = aliases
        #: ``(key, label)`` shortcuts that only exist on the page underneath (child lists).
        self._page_keys = tuple(page_keys)

    def compose(self):
        colors = palette_of(self)
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static("Keys", classes="dialog-title")
            yield Static(self._columns(BASIC_KEYS), classes="dialog-text help-rows", id="help-basics")
            yield Static("shortcuts", classes="dialog-note")
            yield Static(self._columns(SHORTCUTS), classes="help-rows", id="help-shortcuts")
            if self._page_keys:
                page = Text("this page  ", style=colors["dim"], no_wrap=True, overflow="ellipsis")
                for index, (key, label) in enumerate(self._page_keys):
                    page.append("  " if index else "")
                    page.append(key, style=colors["accent"])
                    page.append(f" {label}", style=colors["text"])
                yield Static(page, classes="dialog-text", id="help-page-keys")
            yield Static(
                "Every control is reachable with Tab and runs with Enter or a click; letters are "
                "optional. The \u276f radar prompt also lists help, view settings and quit. Search "
                "filters loaded rows locally. Radar does not create namespaces.",
                classes="dialog-note",
            )
            with Horizontal(classes="dialog-buttons"):
                yield close_button(self)

    def _columns(self, pairs):
        colors = palette_of(self)
        rows = Text(no_wrap=True, overflow="ellipsis")
        half = (len(pairs) + 1) // 2
        column = dialog_inner_width(self) // 2
        for index in range(half):
            if index:
                rows.append("\n")
            for key, description in [pairs[index]] + ([pairs[index + half]] if index + half < len(pairs) else []):
                rows.append(f"{key:<7}", style=colors["accent"])
                rows.append(f"{description:<{column - 7}}", style=colors["text"])
        return rows

    def on_button_pressed(self, _event):
        self.action_close()

    def action_close(self):
        self.dismiss(None)


def switcher_entries(specs):
    """``(kind, alias, title, more)`` in switcher order, derived from registry metadata only.

    Each top-level kind that has children leads, followed by the children it declares; every
    other registered kind is listed afterwards under "more kinds"."""
    specs = list(specs)
    known = {spec.kind: spec for spec in specs}
    primary = []
    for spec in specs:
        if not spec.parent and spec.children:
            primary.extend(kind for kind in (spec.kind, *(child.kind for child in spec.children)) if kind in known)
    primary = list(dict.fromkeys(primary))
    ordered = [known[kind] for kind in primary] + [spec for spec in specs if spec.kind not in primary]
    return [
        (spec.kind, (spec.aliases or (spec.kind,))[0], spec.title_plural.lower(), spec.kind not in primary)
        for spec in ordered
    ]


class CommandBar(ModalScreen):
    """``Go to``: type to filter, Enter switches, Esc closes.

    Entries are ``(kind, alias, title[, group])``; grouped entries are listed after the primary
    kinds under a dim heading (``True`` means "more kinds") while nothing is typed. ``commands``
    are ``(id, label)`` pairs listed last under "radar" (help, view settings, quit), so those are
    reachable with Tab, arrows and Enter; their letter shortcuts stay optional."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("up", "move(-1)", "Up"), ("down", "move(1)", "Down")]

    def __init__(self, known=(), current=None, commands=(), heading="Go to", accept="switch"):
        super().__init__()
        entries = []
        for entry in known:
            entry = entry if isinstance(entry, tuple) else (entry, entry, entry)
            kind, alias, title = entry[:3]
            group = entry[3] if len(entry) > 3 else ""
            # ``True`` is the historical spelling of the "more kinds" group.
            entries.append((kind, alias, title, "more kinds" if group is True else (group or "")))
        # Given order (primary kinds first), duplicates dropped; groups keep first-seen order.
        entries = list(dict.fromkeys(entries))
        groups = list(dict.fromkeys(entry[3] for entry in entries if entry[3]))
        self._entries = [entry for entry in entries if not entry[3]] + [
            entry for group in groups for entry in entries if entry[3] == group
        ]
        self._known = [entry[0] for entry in self._entries]
        self._commands = set(command_id for command_id, _label in commands)
        self._entries += [(command_id, "", label, "radar") for command_id, label in commands]
        self._current = current
        self._heading = heading
        #: The Enter label: ``switch`` for kinds, the command's verb (``sort``) for a command-only list.
        self._accept_keys = _SWITCH_KEYS if accept == "switch" else (
            _SWITCH_KEYS[0], Key("switch", "Enter", accept, "screen.choose"), _SWITCH_KEYS[2])

    def compose(self):
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            yield Static(self._heading, classes="dialog-title")
            examples = f": {', '.join(self._known[:3])}{ELLIPSIS}" if self._known else ""
            yield Input(placeholder=f"type to filter{examples}", id="command-input")
            yield OptionList(*self._options(""), id="resource-options")
            # The row above the key line says when kinds are scrolled out of view.
            yield Static("", id="list-more")
            with Horizontal(classes="dialog-buttons"):
                yield dialog_keys(*self._accept_keys)

    def _matches(self, value):
        needle = value.strip().casefold()
        return [
            entry for entry in self._entries
            if not needle or any(needle in part.casefold() for part in (
                entry[2:3] if entry[0] in self._commands else entry[:3]
            ))
        ]

    def _rows(self, value):
        """Matching entries, with a heading string before each later group while nothing is typed."""
        rows, group = [], ""
        for entry in self._matches(value):
            if entry[3] != group and not value.strip() and rows:
                rows.append(entry[3])
            group = entry[3]
            rows.append(entry)
        return rows

    def _options(self, value, highlighted=0):
        colors = palette_of(self)
        width = dialog_inner_width(self)
        options = []
        for index, entry in enumerate(self._rows(value)):
            if isinstance(entry, str):
                options.append(Option(Text(entry, style=colors["dim"]), disabled=True))
                continue
            kind, alias, title, _more = entry
            prompt = Text(no_wrap=True, overflow="ellipsis")
            prompt.append(GUTTER if index == highlighted else " ", style=colors["accent"])
            if kind in self._commands:
                prompt.append(title, style=colors["text"])
                options.append(Option(prompt, id=kind))
                continue
            prompt.append(f":{alias}", style=colors["accent"])
            prompt.append(f" {title}", style=colors["text"])
            if kind == self._current:
                prompt.append(" " * max(1, width - len(prompt) - len("current")))
                prompt.append("current", style=colors["dim"])
            options.append(Option(prompt, id=kind))
        return options

    def on_mount(self):
        self.query_one(Input).focus()
        options = self.query_one(OptionList)
        if options.option_count:
            options.highlighted = 0
        self.watch(options, "scroll_y", lambda _value: self._sync_more(), init=False)
        self.call_after_refresh(self._fit)

    def on_resize(self, _event):
        self.call_after_refresh(self._fit)

    def _fit(self):
        fit_dialog_list(self, "#resource-options")
        self.call_after_refresh(self._sync_more)

    def _sync_more(self):
        """``↑ 2 more · ↓ 3 more``: entries scrolled out of view on either side."""
        options = self.query_one(OptionList)
        # From the fitted height rather than the region, which may lag a layout pass behind.
        fitted = options.styles.max_height
        visible = int(fitted.value) if fitted is not None else options.option_count
        above = round(options.scroll_y)
        below = max(0, options.option_count - above - visible)  # one line per kind
        text = " \u00b7 ".join(part for part in (
            f"\u2191 {above} more" if above else "", f"\u2193 {below} more" if below else "",
        ) if part)
        self.query_one("#list-more", Static).update(Text(text, style=palette_of(self)["dim"]))

    def action_move(self, step):
        """Move the highlight, stepping over the "more kinds" heading."""
        options = self.query_one(OptionList)
        if not options.option_count:
            return
        current = options.highlighted if options.highlighted is not None else -step
        target = max(0, min(options.option_count - 1, current + step))
        if options.get_option_at_index(target).disabled:
            beyond = target + step
            target = beyond if 0 <= beyond < options.option_count else current
        options.highlighted = target

    def on_input_changed(self, event):
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options(self._options(event.value))
        if options.option_count:
            options.highlighted = 0
        self.call_after_refresh(self._sync_more)

    def on_option_list_option_highlighted(self, event):
        options = self.query_one(OptionList)
        value = self.query_one(Input).value
        for index, option in enumerate(self._options(value, event.option_index)):
            if index < options.option_count:
                options.replace_option_prompt_at_index(index, option.prompt)

    def on_input_submitted(self, event):
        self._submit(event.value)

    def action_choose(self):
        """A click on ``Enter switch`` behaves exactly like Enter in the filter."""
        self._submit(self.query_one(Input).value)

    def _submit(self, value):
        """An exact kind or alias wins, then a single match, then the highlighted row."""
        value = value.strip()
        exact = [entry[0] for entry in self._entries if entry[0] not in self._commands
                 and value.casefold() in (entry[0].casefold(), entry[1].casefold())]
        matches = [entry[0] for entry in self._matches(value)]
        options = self.query_one(OptionList)
        if exact:
            self.dismiss(exact[0])
        elif len(matches) == 1:
            self.dismiss(matches[0])
        elif options.highlighted is not None and options.option_count:
            self.dismiss(str(options.get_option_at_index(options.highlighted).id))
        else:
            self.dismiss(value)

    def on_option_list_option_selected(self, event):
        self.dismiss(str(event.option.id))

    def action_cancel(self):
        self.dismiss("")
