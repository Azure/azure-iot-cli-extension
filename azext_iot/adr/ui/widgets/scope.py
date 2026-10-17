# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Scope picker: one dialog with a resource group tab and a subscription tab.

Typing filters the cached list locally; nothing is requested per keystroke. Choosing a
subscription only moves to its resource groups; the scope changes once, when a resource group (or
"all resource groups") is chosen, so a half-picked scope never reaches a provider. Esc changes
nothing.
"""

from functools import partial

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from azext_iot.adr.ui.core.io import run_io
from azext_iot.adr.ui.core.scope import (
    GROUP_LIMIT, SUBSCRIPTIONS, ListState, group_key, valid_group_name,
)
from azext_iot.adr.ui.screens.help import dialog_inner_width
from azext_iot.adr.ui.widgets.minimal import ELLIPSIS, GUTTER, Clickable, Key, dialog_keys, fit_dialog_list, palette_of

GROUP, SUBSCRIPTION = "group", "subscription"
ALL_GROUPS = "all resource groups"


def _keys(mode):
    other = "subscription" if mode == GROUP else "resource group"
    return (
        Key("move", "\u2191\u2193", "choose"),
        Key("select", "Enter", "select", "screen.choose"),
        Key("tab", "Tab", other, "screen.toggle_mode"),
        Key("close", "Esc", "close", "screen.cancel", essential=True),
    )


class ScopeDialog(ModalScreen):
    """Dismisses with ``{subscription_id, subscription, resource_group_name}`` or ``None``."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("tab", "toggle_mode", "Switch list", show=False),
        Binding("shift+tab", "toggle_mode", "Switch list", show=False),
        Binding("ctrl+r", "reload", "Reload", show=False),
    ]

    def __init__(self, catalog, scope, mode=GROUP):
        super().__init__()
        self.catalog = catalog
        self.current = dict(scope or {})
        self.mode = mode
        #: The subscription whose resource groups are listed: the current one until another is chosen.
        self.target = (self.current.get("subscription_id"),
                       self.current.get("subscription") or self.current.get("subscription_id"))
        self._loading = set()
        self._rows = []
        self._marked = None

    # -- composition -------------------------------------------------------

    def compose(self):
        with Vertical(classes="dialog-frame"), VerticalScroll(classes="dialog"):
            with Horizontal(id="scope-tabs"):
                yield Clickable("", action=f"screen.show_mode('{GROUP}')", id="tab-group", classes="scope-tab")
                yield Clickable("", action=f"screen.show_mode('{SUBSCRIPTION}')", id="tab-subscription",
                                classes="scope-tab")
            yield Static("", id="scope-context", classes="dialog-context")
            yield Input(id="scope-input")
            yield OptionList(id="scope-options")
            yield Clickable("", action="screen.reload", id="scope-status")
            with Horizontal(classes="dialog-buttons"):
                yield dialog_keys(*_keys(self.mode))

    def on_mount(self):
        self.query_one(Input).focus()
        self._enter_mode(self.mode)
        self.call_after_refresh(fit_dialog_list, self, "#scope-options")

    def on_resize(self, _event):
        self.call_after_refresh(fit_dialog_list, self, "#scope-options")

    # -- modes and loading ---------------------------------------------------

    def _key(self):
        return SUBSCRIPTIONS if self.mode == SUBSCRIPTION else group_key(self.target[0])

    def _enter_mode(self, mode):
        self.mode = mode
        field = self.query_one(Input)
        field.value = ""
        # Typing always reaches the filter, even after a click on a tab or a row.
        field.focus()
        field.placeholder = (
            "type to filter, or a resource group name" if mode == GROUP else "type to filter subscriptions"
        )
        self.query_one("#dialog-keys").set_keys(_keys(mode))
        self._paint_tabs()
        if mode == GROUP and not self.target[0]:
            self._show_rows(highlight_current=True)
            return
        if not self.catalog.is_fresh(self._key()):
            self._load(self._key())
        self._show_rows(highlight_current=True)

    def _load(self, key, force=False):
        if key in self._loading:
            return
        self._loading.add(key)
        self.run_worker(self._fetch(key, force), name=f"scope-{key[0]}")

    async def _fetch(self, key, force):
        try:
            await run_io(partial(self.catalog.fetch, key, force), self.app.io_slots)
        finally:
            self._loading.discard(key)
        # A listing for a subscription the picker has moved away from is cached, never shown.
        if self.is_attached and key == self._key():
            self._show_rows(highlight_current=True)

    def action_show_mode(self, mode):
        if mode != self.mode:
            self._enter_mode(mode)

    def action_toggle_mode(self):
        self._enter_mode(SUBSCRIPTION if self.mode == GROUP else GROUP)

    def action_reload(self):
        if self.mode == GROUP and not self.target[0]:
            return
        self._load(self._key(), force=True)
        self._show_rows()

    # -- rows ----------------------------------------------------------------

    def _matches(self, needle):
        """``(id, label, detail, current)`` rows; prefix matches lead while typing."""
        listing = None if self.mode == GROUP and not self.target[0] else self.catalog.peek(self._key())
        items = listing.items if listing is not None else ()
        needle = needle.strip().casefold()

        def rank(choice):
            name = choice.name.casefold()
            return (0 if name.startswith(needle) else 1, name)

        found = sorted((c for c in items if not needle or needle in c.name.casefold()
                        or needle in c.detail.casefold()), key=rank)
        if self.mode == SUBSCRIPTION:
            current = self.current.get("subscription_id")
            return [(f"sub:{c.id}", c.name, c.state if c.state.casefold() not in ("", "enabled") else c.id[:8]
                     + ELLIPSIS, c.id == current) for c in found] + self._retry_row(listing, needle)
        same = self.target[0] == self.current.get("subscription_id")
        current = self.current.get("resource_group_name") if same else object()
        rows = [(f"rg:{c.name}", c.name, c.detail, c.name == current) for c in found]
        if not needle or needle in ALL_GROUPS:
            rows.insert(0 if not needle else len(rows), (
                "all", ALL_GROUPS, "whole subscription", same and not self.current.get("resource_group_name"),
            ))
        # A typed name is offered when the list cannot be trusted to be complete (denied, failed,
        # truncated) or when nothing listed matches; otherwise it would only shadow real rows.
        complete = listing is not None and listing.usable and not listing.truncated
        typed = needle and not any(c.name.casefold() == needle for c in items) and not (complete and found)
        if typed and valid_group_name(needle):
            original = self.query_one(Input).value.strip()
            rows.append((f"use:{original}", f"use {original}", "typed name", False))
        return rows + self._retry_row(listing, needle)

    @staticmethod
    def _retry_row(listing, needle):
        """The last row reloads the list (``retry listing`` after a failure), so reloading needs only
        arrows and Enter; Ctrl+R and a click on the status stay optional."""
        if needle or listing is None:
            return []
        failed = listing.state in (ListState.DENIED, ListState.FAILED)
        return [("retry", "retry listing", "", False) if failed else ("reload", "reload list", "", False)]

    def _show_rows(self, highlight_current=False):
        options = self.query_one(OptionList)
        previous = self._highlighted_id()
        self._rows = self._matches(self.query_one(Input).value)
        index = None
        if not self.query_one(Input).value.strip():
            # Nothing typed: start on the current scope, else keep the row under the cursor.
            if highlight_current:
                index = next((i for i, row in enumerate(self._rows) if row[3]), None)
            if index is None:
                index = next((i for i, row in enumerate(self._rows) if row[0] == previous), None)
        if index is None and self._rows:
            index = 0
        options.clear_options()
        options.add_options(self._options(index))
        if index is not None:
            options.highlighted = index
        self._paint_context()
        self._paint_status()

    def _options(self, highlighted):
        self._marked = highlighted
        return [Option(self._prompt(index, index == highlighted), id=row[0]) for index, row in enumerate(self._rows)]

    def _prompt(self, index, marked):
        colors = palette_of(self)
        row_id, label, detail, current = self._rows[index]
        prompt = Text(no_wrap=True, overflow="ellipsis")
        prompt.append(GUTTER if marked else " ", style=colors["accent"])
        prompt.append(label, style=colors["dim" if row_id in ("all", "retry", "reload") else "text"])
        tag = "current" if current else detail
        room = dialog_inner_width(self) - len(prompt) - len(tag)
        if tag and room >= 1:
            prompt.append(" " * room)
            prompt.append(tag, style=colors["accent" if current else "dim"])
        return prompt

    def _highlighted_id(self):
        options = self.query_one(OptionList)
        if options.highlighted is None or not options.option_count:
            return None
        return options.get_option_at_index(options.highlighted).id

    def on_option_list_option_highlighted(self, event):
        """Move the gutter mark: only the two affected rows are redrawn, even for 1000 groups."""
        options = self.query_one(OptionList)
        for index, marked in ((self._marked, False), (event.option_index, True)):
            if index is not None and index < min(options.option_count, len(self._rows)):
                options.replace_option_prompt_at_index(index, self._prompt(index, marked))
        self._marked = event.option_index

    def _paint_tabs(self):
        colors = palette_of(self)
        for mode, label in ((GROUP, "Resource group"), (SUBSCRIPTION, "Subscription")):
            active = mode == self.mode
            text = Text(label, style=f"bold {colors['text']}" if active else colors["dim"])
            tab = self.query_one(f"#tab-{mode}", Clickable)
            tab.update(text)
            tab.set_class(active, "-active")

    def _paint_context(self):
        colors = palette_of(self)
        text = Text(no_wrap=True, overflow="ellipsis")
        if self.mode == GROUP:
            text.append("in ", style=colors["dim"])
            text.append(str(self.target[1] or "no subscription"), style=colors["text"])
            if self.target[0] != self.current.get("subscription_id"):
                text.append(" \u00b7 not applied yet", style=colors["dim"])
        else:
            text.append("from az login; az defaults stay unchanged", style=colors["dim"])
        self.query_one("#scope-context", Static).update(text)

    def _paint_status(self):
        colors = palette_of(self)
        text = Text(no_wrap=True, overflow="ellipsis")
        key = self._key()
        listing = None if self.mode == GROUP and not self.target[0] else self.catalog.peek(key)
        what = "resource groups" if self.mode == GROUP else "subscriptions"
        typed = self.query_one(Input).value.strip()
        if self.mode == GROUP and not self.target[0]:
            text.append("Choose a subscription first (Tab).", style=colors["warning"])
        elif self.mode == GROUP and typed and not self._rows and not valid_group_name(typed):
            text.append("Not a valid name: use letters, digits, - _ . ( )",
                        style=colors["warning"])
        elif key in self._loading and listing is None:
            waiting = self.app.io_slots.locked()
            text.append(f"{'Waiting for a request slot' if waiting else f'Listing {what}'}{ELLIPSIS} "
                        "type a name to skip", style=colors["dim"])
        elif listing is not None and listing.state in (ListState.DENIED, ListState.FAILED):
            color = colors["warning" if listing.state is ListState.DENIED else "error"]
            text.append(listing.message, style=color)
        elif listing is not None:
            needle = self.query_one(Input).value.strip()
            count = len(listing.items)
            shown = sum(1 for row in self._rows if row[0].startswith(("rg:", "sub:")))
            message = listing.message if listing.state is ListState.EMPTY else (
                f"{shown} of {count} {what}" if needle else f"{count} {what if count != 1 else what[:-1]}"
            )
            missing = self.mode == SUBSCRIPTION and needle and not shown
            if missing:
                message = "Not in your az login profile. Run az account list --refresh outside radar."
            text.append(message, style=colors["warning" if missing else "dim"])
            if listing.truncated:
                text.append(f" \u00b7 first {GROUP_LIMIT}; type a name for others", style=colors["warning"])
            if key in self._loading:
                text.append(f"  reloading{ELLIPSIS}", style=colors["dim"])
        self.query_one("#scope-status", Clickable).update(text)

    # -- input -----------------------------------------------------------------

    def on_input_changed(self, _event):
        self._show_rows()

    def on_input_submitted(self, _event):
        self.action_choose()

    def action_move(self, step):
        options = self.query_one(OptionList)
        if options.option_count:
            # Wraps like a focused OptionList: up from the first row reaches the reload row at the end.
            current = options.highlighted if options.highlighted is not None else -step
            options.highlighted = (current + step) % options.option_count

    def action_choose(self):
        row_id = self._highlighted_id()
        if row_id is not None:
            self._pick(row_id)
            return
        # Nothing to choose: the status line already says why; keep the text for correcting.
        self.app.bell()
        self.query_one(Input).focus()

    def on_option_list_option_selected(self, event):
        self._pick(event.option.id)

    def _pick(self, row_id):
        kind, _, value = row_id.partition(":")
        if kind in ("retry", "reload"):
            self.action_reload()
            return
        if kind == "sub":
            listing = self.catalog.peek(SUBSCRIPTIONS)
            choice = next(c for c in listing.items if c.id == value)
            self.target = (choice.id, choice.name)
            self._enter_mode(GROUP)
            return
        if not self.target[0]:
            return
        self.dismiss({
            "subscription_id": self.target[0],
            "subscription": self.target[1],
            "resource_group_name": None if kind == "all" else value,
        })

    def action_cancel(self):
        self.dismiss(None)
