# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Single-row building blocks for the minimal radar layout.

Each piece is one terminal row of styled text. Everything clickable is a plain text run that
maps a click back to the same action its key runs, so mouse and keyboard can never disagree.
"""

from typing import Iterable, List, NamedTuple, Optional, Tuple

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Button, Static

from azext_iot.adr.ui.theme import resolve_palette

GUTTER = "\u258e"  # ▎ the selected-row accent bar
PROMPT = "\u276f"  # ❯
CARET = "\u258c"  # ▌
ELLIPSIS = "\u2026"


class PillButton(Button):
    """A one-row button whose width is exactly its label plus the CSS padding (``0 1``).

    Textual 6 Button carries a default ``line-pad: 1`` and adds 2 cells in
    ``get_content_width``; the CSS parser rejects ``line-pad: 0``, so both are reset here.
    Space presses it as well as Enter, like every other focusable control."""

    BINDINGS = [Binding("space", "press", "Press", show=False)]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("compact", True)
        super().__init__(*args, **kwargs)
        self.styles.line_pad = 0

    def get_content_width(self, container, viewport) -> int:
        lines = self.label.plain.splitlines() if self.label is not None else []
        return max((cell_len(line) for line in lines), default=0)


def palette_of(node) -> dict:
    """The active palette, safe before the node is attached to an app."""
    try:
        app = node.app
    except Exception:  # noqa: BLE001 - detached widgets have no app yet
        app = None
    return getattr(app, "theme_palette", None) or resolve_palette()


class Key(NamedTuple):
    """One key hint: ``key`` in accent, ``label`` dim; clicking runs ``action``."""

    name: str
    key: str
    label: str
    action: Optional[str] = None
    essential: bool = False


class Clickable(Static):
    """A text run that runs one action when clicked.

    With ``focusable=True`` it is also a keyboard control: Tab reaches it and Enter or Space runs
    the same action, so nothing that can be clicked needs a special key."""

    BINDINGS = [
        Binding("enter", "activate", "Open", show=False),
        Binding("space", "activate", "Open", show=False),
    ]

    def __init__(self, content="", action: Optional[str] = None, focusable: bool = False, **kwargs):
        super().__init__(content, **kwargs)
        self.action = action
        self.can_focus = focusable

    async def action_activate(self) -> None:
        if self.action:
            await self.run_action(self.action)

    async def on_click(self, event) -> None:
        if self.action:
            event.stop()
            await self.run_action(self.action)


class KeysLine(Widget):
    """The state-specific key line: ``key label`` groups separated by two spaces.

    Groups that do not fit are dropped from the end, except essential ones (back and help),
    so narrow terminals never show a clipped control.
    """

    DEFAULT_CSS = "KeysLine { height: 1; }"

    def __init__(self, keys: Iterable[Key] = (), separator: str = "  ", **kwargs):
        super().__init__(**kwargs)
        self.separator = separator
        self._keys: List[Key] = list(keys)
        self._spans: List[Tuple[int, int, Key]] = []

    @property
    def keys(self) -> List[Key]:
        return list(self._keys)

    def set_keys(self, keys: Iterable[Key]) -> None:
        keys = list(keys)
        if keys != self._keys:
            self._keys = keys
            self.refresh()

    def visible_keys(self, width: Optional[int] = None) -> List[Key]:
        width = self.size.width if width is None else width
        if not width:
            return list(self._keys)
        gap = len(self.separator)
        reserved = sum(len(k.key) + 1 + len(k.label) + gap for k in self._keys if k.essential)
        used, shown = 0, []
        for key in self._keys:
            cost = len(key.key) + 1 + len(key.label) + gap
            if key.essential or used + cost + reserved <= width + gap:
                shown.append(key)
                if not key.essential:
                    used += cost
        return shown

    def render(self) -> Text:
        colors = palette_of(self)
        text = Text(no_wrap=True, overflow="crop")
        self._spans = []
        for index, key in enumerate(self.visible_keys()):
            if index:
                text.append(self.separator, style=colors["dim"])
            start = len(text)
            text.append(key.key, style=colors["accent"])
            text.append(" ")
            text.append(key.label, style=colors["dim"])
            self._spans.append((start, len(text), key))
        return text

    def offset_of(self, name: str) -> Tuple[int, int]:
        """Cell offset of a named group, for pointer tests and accessibility tooling."""
        self.render()
        for start, _end, key in self._spans:
            if key.name == name:
                return (start, 0)
        raise KeyError(name)

    async def on_click(self, event) -> None:
        for start, end, key in self._spans:
            if start <= event.x < end and key.action:
                event.stop()
                await self.run_action(key.action)
                return


def control_text(node, label: str) -> Text:
    """A page control's face: its plain label in the accent colour. Optional letter accelerators
    are listed in help, never printed on the control."""
    return Text(label, style=Style.parse(palette_of(node)["accent"]), no_wrap=True)


def title_text(node, title: str, count=None) -> Text:
    """``Title  count``; the count is dim like the reference."""
    colors = palette_of(node)
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(title, style=f"bold {colors['text']}")
    if count is not None and count != "":
        text.append("  ")
        text.append(str(count), style=colors["dim"])
    return text


def key_value_rows(node, rows: Iterable[Tuple[str, str, Optional[str]]], key_width: int = 18) -> Text:
    """Dim keys in a fixed column, values in the text colour (or their status colour)."""
    colors = palette_of(node)
    text = Text(no_wrap=True, overflow="ellipsis")
    for index, (key, value, style) in enumerate(rows):
        if index:
            text.append("\n")
        text.append(f"{key:<{key_width - 1}} "[:key_width], style=colors["dim"])
        text.append(value, style=style or colors["text"])
    return text


def dialog_keys(*keys: Key) -> KeysLine:
    """The one-row hint at the foot of a list dialog (``↑↓ choose · Enter select · Esc close``).

    Replaces a separate Close button; every group is clickable, Esc included."""
    return KeysLine(keys, separator=" \u00b7 ", id="dialog-keys")


def fit_dialog_list(screen, selector: str, cap: int = 14) -> None:
    """Shrink a dialog's option list so the whole dialog keeps one free row above and below.

    The list scrolls instead of the dialog covering the header or clipping its buttons on short
    terminals (80x24)."""
    try:
        dialog = screen.query(".dialog-frame").first() if screen.query(".dialog-frame") else screen.query_one(".dialog")
        options = screen.query_one(selector)
        body = screen.query_one(".dialog")
    except Exception:  # noqa: BLE001 - dialog not composed yet
        return
    # A dialog taller than the screen is clamped and its body scrolls; the clipped rows
    # (``max_scroll_y``) are chrome too, or the list stays too long and the body keeps scrolling.
    clipped = max(0, round(getattr(body, "max_scroll_y", 0) or 0))
    chrome = dialog.outer_size.height - options.outer_size.height + clipped
    if chrome <= 0:
        return
    target = max(3, min(cap, screen.size.height - 2 - chrome))
    if options.styles.max_height is None or options.styles.max_height.value != target:
        options.styles.max_height = target
