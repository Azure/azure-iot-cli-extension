# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Base screen that carries the persistent chrome.

Textual's screen stack replaces the whole visible screen, so the chrome is composed by each
screen through this base class rather than owned by the application. Screens override
:meth:`compose_content` and never re-declare the chrome.
"""

from typing import Iterable, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches

from azext_iot.adr.ui.core.spec import Guide
from azext_iot.adr.ui.widgets.chrome import FlashLine
from azext_iot.adr.ui.widgets.minimal import (
    CARET, PROMPT, Clickable, Key, KeysLine, palette_of, title_text,
)

#: Rows that are always present around the content: header, blank, title, blank above it and
#: blank, key line below it. The flash line adds one row while it shows a message.
_FIXED_ROWS = 7
#: Terminals at least this tall get one row of breathing space above the header.
_TOP_PADDING_FROM = 30

#: The one navigation hint every page shows: Tab walks the header and page controls.
FOCUS = Key("focus", "Tab", "controls", "app.focus_next")
BACK = Key("back", "Esc", "back", "screen.back", essential=True)
#: Shown instead of ``Esc back`` on the first page, where Esc has nowhere to go.
QUIT = Key("quit", "q", "quit", "app.quit", essential=True)
HELP = Key("help", "?", "help", "app.help", essential=True)


class ChromeScreen(Screen):
    """Prompt header, title row, content, flash line and a state-specific key line.

    Everything sits in one centred column (``FRAME_WIDTH`` = 92 cells, or the full width minus 2-cell margins on
    narrower terminals) and flows top to bottom like the approved minimal preview.
    """

    #: Whether the content area scrolls as a whole (detail pages) or sizes its own widget.
    CONTENT_SCROLLS = False
    #: Each page chooses its starting focus (the table, its first page control). ``None`` would
    #: inherit the app's ``*`` and land on the first header control, where Enter is unexpected.
    AUTO_FOCUS = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            with Horizontal(id="header"):
                # Every header segment is a control: click it, or Tab to it and press Enter.
                yield Clickable(self._prompt_text(), action="app.command_bar", id="resource-selector",
                                focusable=True)
                # Namespace, resource group and subscription are separate targets: the first opens
                # the namespace list, the other two open the scope picker on their own tab.
                with Horizontal(id="context"):
                    yield Clickable("", action="app.namespaces", id="namespace-selector", classes="ctx",
                                    focusable=True)
                    yield Clickable("", action="app.pick_scope('group')", id="group-selector", classes="ctx",
                                    focusable=True)
                    yield Clickable("", action="app.pick_scope('subscription')", id="subscription-selector",
                                    classes="ctx", focusable=True)
                yield Clickable("", action="app.operations", id="operations", focusable=True)
            with Horizontal(id="title-row"):
                yield Clickable("", id="title-line")
                yield from self.compose_title_extras()
            container = VerticalScroll if self.CONTENT_SCROLLS else Vertical
            with container(id="content"):
                yield from self.compose_content()
            yield FlashLine(id="flash-line")
            yield KeysLine(self.keys(), id="keys-line")

    def _prompt_text(self) -> Text:
        colors = palette_of(self)
        text = Text(no_wrap=True)
        text.append(PROMPT, style=colors["accent"])
        text.append(" radar", style=colors["text"])
        text.append(CARET, style=colors["accent"])
        text.append("  ")
        return text

    def on_mount(self) -> None:
        self.query_one("#resource-selector", Clickable).update(self._prompt_text())
        self.query_one("#flash-line", FlashLine).display = False
        self.refresh_title()
        self.paint_controls()
        self.fit_layout()

    def repaint_theme(self) -> None:
        """Re-render inline-styled text after the palette changes (Ctrl+T)."""
        self.query_one("#resource-selector", Clickable).update(self._prompt_text())
        self.refresh_title()
        self.query_one("#keys-line", KeysLine).refresh()
        self.paint_controls()
        self.app.sync_chrome(self)

    def on_screen_resume(self):
        self.app.sync_chrome(self)
        self.refresh_keys()

    def on_resize(self, _event=None) -> None:
        self.fit_layout()

    # -- layout ------------------------------------------------------------

    def content_rows(self) -> int:
        """Rows available to the content between the title row and the key line."""
        height = self.size.height or self.app.size.height
        top = 1 if height >= _TOP_PADDING_FROM else 0
        try:
            flash = 1 if self.query_one("#flash-line", FlashLine).display else 0
        except NoMatches:
            flash = 0
        return max(3, height - top - _FIXED_ROWS - flash)

    def fit_layout(self) -> None:
        """Top padding on tall terminals; the content never pushes the key line off screen."""
        try:
            frame = self.query_one("#frame")
            content = self.query_one("#content")
        except NoMatches:
            return
        height = self.size.height or self.app.size.height
        frame.styles.padding = (1 if height >= _TOP_PADDING_FROM else 0, 0, 0, 0)
        content.styles.max_height = self.content_rows()
        # Sibling margins collapse, so two blank rows above the key line come from the content
        # alone; with a flash line showing it is blank, flash, blank, keys.
        flash = self.query_one("#flash-line", FlashLine).display
        content.styles.margin = (0, 0, 1 if flash else 2, 0)

    # -- chrome ------------------------------------------------------------

    def compose_title_extras(self) -> Iterable[ComposeResult]:
        return iter(())

    def compose_content(self) -> Iterable[ComposeResult]:
        """Yield the screen's own widgets. Overridden by every concrete screen."""
        return iter(())

    def title_parts(self) -> Tuple[str, object]:
        """``(title, dim count)`` for the title row."""
        return (self.breadcrumb(), None)

    def refresh_title(self) -> None:
        try:
            line = self.query_one("#title-line", Clickable)
        except NoMatches:
            return
        line.update(title_text(self, *self.title_parts()))

    def keys(self) -> List[Key]:
        """The key line for the current state. Overridden by concrete screens."""
        return [FOCUS, self.back_key(), HELP]

    def is_root(self) -> bool:
        """The first page of the session: nothing underneath it to go back to."""
        stack = self.app.screen_stack
        return stack.index(self) <= 1 if self in stack else len(stack) <= 1

    def back_key(self) -> Key:
        return QUIT if self.is_root() else BACK

    def refresh_keys(self) -> None:
        try:
            self.query_one("#keys-line", KeysLine).set_keys(self.keys())
        except NoMatches:
            return
        self.paint_controls()

    def paint_controls(self) -> None:
        """Repaint the page controls in the title row; they follow the selection like the keys."""

    def help_keys(self) -> List[Tuple[str, str]]:
        """Optional letter accelerators for this page, listed in help and never on the controls."""
        children = getattr(getattr(self, "spec", None), "children", ())
        return [(child.key, child.label) for child in children if child.key]

    def focus_first_control(self) -> None:
        """Start on the page's first visible control (never a header control), if it has one."""
        for control in self.query("#title-row Clickable, #content Clickable"):
            if control.can_focus and control.display:
                control.focus()
                return

    def show_control(self, control_id: str, visible: bool, face=None) -> None:
        """Show or hide one page control. A hidden control never keeps the keyboard focus."""
        control = self.query_one(f"#{control_id}", Clickable)
        if face is not None:
            control.update(face)
        if not visible and self.focused is control:
            self.focus_next()
        control.display = visible

    def guide(self) -> Optional[Guide]:
        """Orientation for this page. Screens without one simply show nothing."""
        return None

    def breadcrumb(self) -> str:
        """Label for this screen in the breadcrumb trail."""
        return self.__class__.__name__.replace("Screen", "").lower()

    def hint_bindings(self) -> List[Tuple[str, str]]:
        """Key hints, always derived from real bindings so help cannot drift."""
        return [
            (binding.key_display or binding.key, binding.description)
            for binding in self.BINDINGS
            if getattr(binding, "show", True)
        ]

    def filter_text(self) -> str:
        return ""

    def action_back(self) -> None:
        self.app.pop_screen_safely()

    def flash(self, message: str, level: str = "info") -> None:
        """Show a transient message. Safe before mount and after teardown."""
        try:
            line = self.query_one("#flash-line", FlashLine)
        except NoMatches:
            return
        line.flash(message, level)
        line.display = bool(message)
        self.fit_layout()
