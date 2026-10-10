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
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Static
from textual.css.query import NoMatches

from azext_iot.adr.ui.core.spec import Guide
from azext_iot.adr.ui.widgets.chrome import FlashLine


class ChromeScreen(Screen):
    """Context bar, info panel, breadcrumbs, page guide, hint bar, content, flash line."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="selectors"):
            yield Button("Namespaces", id="namespace-selector")
            yield Button("Resources", id="resource-selector")
            yield Button("o ops idle", id="operations")
        yield Static("", id="context-bar")
        yield from self.compose_content()
        yield FlashLine(id="flash-line")
        yield Footer()

    def on_button_pressed(self, event):
        actions = {
            "namespace-selector": self.app.action_namespaces,
            "resource-selector": self.app.action_command_bar,
            "operations": self.app.action_operations,
        }
        if event.button.id in actions:
            actions[event.button.id]()

    def on_screen_resume(self):
        self.app.sync_chrome(self)

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
        except NoMatches:
            return
