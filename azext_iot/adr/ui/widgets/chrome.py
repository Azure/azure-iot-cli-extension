# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Persistent application chrome: context bar, info panel, hint bar, breadcrumbs, flash."""

from typing import Iterable, List, Optional, Sequence, Tuple

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

# Flash severities. Kept as plain strings so callers need no import.
INFO = "info"
SUCCESS = "success"
WARNING = "warning"
ERROR = "error"

_FLASH_TOKENS = {
    INFO: "",
    SUCCESS: "active",
    WARNING: "warn",
    ERROR: "error",
}
_FLASH_PREFIX = {INFO: "", SUCCESS: "OK  ", WARNING: "!   ", ERROR: "ERR "}


def _palette(widget, role: str, fallback: str = "") -> str:
    return getattr(widget.app, "theme_palette", {}).get(role, fallback)


class ContextBar(Static):
    """Current subscription, resource group and namespace."""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._scope = {}
        self.text = ""

    def set_scope(
        self,
        subscription: Optional[str] = None,
        resource_group: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        self._scope = {"sub": subscription, "rg": resource_group, "ns": namespace}
        self.refresh_display()

    def refresh_display(self) -> None:
        text = Text()
        title_foreground = _palette(self, "title_fg", "")
        for label, key in (("sub ", "sub"), ("rg ", "rg"), ("ns ", "ns")):
            value = self._scope.get(key)
            if not value:
                continue
            if text:
                text.append("  ·  ", style=title_foreground)
            text.append(label, style=title_foreground)
            text.append(str(value), style=f"bold {title_foreground}")
        if not text:
            text.append("choose a subscription to begin", style=title_foreground)
        self.text = text.plain
        self.update(text)


class InfoPanel(Static):
    """Key facts for the current scope. Collapsible to reclaim rows on small terminals."""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._facts: List[Tuple[str, str]] = []
        self._collapsed = False
        self.text = ""

    def set_facts(self, facts: Sequence[Tuple[str, str]]) -> None:
        self._facts = list(facts)
        self.refresh_display()

    def toggle(self) -> bool:
        self._collapsed = not self._collapsed
        self.refresh_display()
        return self._collapsed

    def refresh_display(self) -> None:
        if self._collapsed or not self._facts:
            self.display = False
            return
        self.display = True
        text = Text()
        dim = _palette(self, "dim", "dim")
        for index, (label, value) in enumerate(self._facts):
            if index:
                text.append("   ", style=dim)
            text.append(f"{label} ", style=dim)
            text.append(str(value), style="")
        self.text = text.plain
        self.update(text)


class PageGuide(Static):
    """Two or three lines explaining the page the customer just arrived on.

    Shown by default because the cost of reading it once is far lower than the cost of
    guessing what a page does against live infrastructure. Dismissible with a key, so it
    stops being shown to anyone who no longer needs it.
    """

    #: Column the values line up on, so three labels of different lengths read as a table.
    _LABEL_WIDTH = 5
    _DISPLAY_LABELS = {
        "about": "VIEW",
        "action": "DO",
        "info": "INFO",
    }

    def __init__(self, **kwargs):  # noqa: D107
        super().__init__("", **kwargs)
        self._rows: List[Tuple[str, str]] = []
        self._collapsed = False
        self.text = ""

    def set_guide(self, rows: Sequence[Tuple[str, str]]) -> None:
        self._rows = list(rows)
        self.refresh_display()

    def toggle(self) -> bool:
        self._collapsed = not self._collapsed
        self.refresh_display()
        return self._collapsed

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.refresh_display()

    def refresh_display(self) -> None:
        if self._collapsed or not self._rows:
            self.display = False
            self.text = ""
            return
        self.display = True
        # A two-column table rather than one wrapped string: on a narrow terminal a long
        # sentence must wrap under its own value, not back under the label.
        rows = []
        values = dict(self._rows)
        if values.get("about"):
            rows.append(("about", values["about"]))
        if values.get("action"):
            rows.append(("action", values["action"]))
        context = "  ·  ".join(
            value for value in (values.get("runs"), values.get("note")) if value
        )
        if context:
            rows.append(("info", context))

        table = Table.grid(padding=(0, 2))
        table.add_column(width=self._LABEL_WIDTH, no_wrap=True)
        table.add_column(ratio=1, overflow="fold")
        palette = getattr(self.app, "theme_palette", {})
        active = palette.get("accent", "cyan")
        muted = palette.get("dim", "dim")
        do_background = palette.get("do_bg", active)
        do_foreground = palette.get("do_fg", "white")
        for label, value in rows:
            label_style = {
                "about": f"bold {active}",
                "action": f"bold {active}",
                "info": muted,
            }.get(label, "dim")
            value_style = {
                "about": "bold",
                "action": f"bold {do_foreground} on {do_background}",
                "info": muted,
            }.get(label, "")
            table.add_row(
                Text(self._DISPLAY_LABELS.get(label, label.upper()), style=label_style),
                Text(f" {value} " if label == "action" else value, style=value_style),
            )
        self.text = "\n".join(
            f"{self._DISPLAY_LABELS.get(label, label.upper())}  {value}"
            for label, value in rows
        )
        self.update(table)


class HintBar(Static):
    """Available keys for the focused screen.

    Always generated from the screen's real bindings, never hand-written, so the hints
    cannot drift from behaviour.
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.text = ""

    def set_bindings(self, bindings: Iterable[Tuple[str, str]]) -> None:
        text = Text()
        dim = _palette(self, "dim", "dim")
        for key, description in bindings:
            if not description:
                continue
            if text:
                text.append("   ", style=dim)
            is_onboarding = description in ("New setup", "Connect selected")
            active = getattr(self.app, "theme_tokens", {}).get("active", "")
            text.append(f"{key}", style=f"bold {active}" if is_onboarding else "bold")
            text.append(
                f" {description}",
                style=f"bold {active}" if is_onboarding else dim,
            )
        self.text = text.plain
        self.update(text)


class Breadcrumbs(Static):
    """Position in the page stack, plus the active filter when one is set."""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.text = ""

    def set_path(self, parts: Sequence[str], filter_text: str = "") -> None:
        text = Text()
        dim = _palette(self, "dim", "dim")
        warning = _palette(self, "warning", "yellow")
        for index, part in enumerate(parts):
            if index:
                text.append("  ›  ", style=dim)
            style = "bold" if index == len(parts) - 1 else ""
            text.append(str(part), style=style)
        if filter_text:
            text.append(f"   [filter: {filter_text}]", style=warning)
        self.text = text.plain
        self.update(text)


class FlashLine(Static):
    """Transient status messages. Non-error messages clear themselves."""

    AUTO_CLEAR_SECONDS = 6.0

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._timer = None
        self.text = ""

    def flash(self, message: str, level: str = INFO) -> None:
        self._cancel_timer()
        self.text = message
        token = _FLASH_TOKENS.get(level, "")
        style = getattr(self.app, "theme_tokens", {}).get(token, "")
        if level == ERROR and style:
            style = f"bold {style}"
        self.update(Text(f"{_FLASH_PREFIX.get(level, '')}{message}", style=style))
        if level != ERROR:
            # Errors persist: they usually require the user to do something.
            self._timer = self.set_timer(self.AUTO_CLEAR_SECONDS, self.clear)

    def clear(self) -> None:
        self._cancel_timer()
        self.text = ""
        self.update("")

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
