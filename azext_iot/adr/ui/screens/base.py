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

from textual.app import ComposeResult
from textual.screen import Screen

from azext_iot.adr.ui.core.spec import Guide
from azext_iot.adr.ui.widgets.chrome import (
    Breadcrumbs,
    ContextBar,
    FlashLine,
    HintBar,
    InfoPanel,
    PageGuide,
)
from azext_iot.adr.ui.widgets.tray import OperationsTray


class ChromeScreen(Screen):
    """Context bar, info panel, breadcrumbs, page guide, hint bar, content, flash line."""

    def compose(self) -> ComposeResult:
        yield ContextBar(id="context-bar")
        yield InfoPanel(id="info-panel")
        yield Breadcrumbs(id="breadcrumbs")
        # Above the keys, because "what is this page" is the question that comes first.
        yield PageGuide(id="page-guide")
        yield HintBar(id="hint-bar")
        yield from self.compose_content()
        yield OperationsTray(id="ops-tray")
        yield FlashLine(id="flash-line")

    def compose_content(self) -> Iterable[ComposeResult]:
        """Yield the screen's own widgets. Overridden by every concrete screen."""
        return iter(())

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

    def flash(self, message: str, level: str = "info") -> None:
        """Show a transient message. Safe before mount and after teardown."""
        try:
            self.query_one("#flash-line", FlashLine).flash(message, level)
        except Exception:  # noqa: BLE001 - a status message must never break a flow
            return
