# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Detail view: the full resource payload as formatted JSON."""

import json
from typing import Any, Dict, Optional

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from azext_iot.adr.ui.core.redaction import redact
from azext_iot.adr.ui.core.spec import Guide, ResourceSpec
from azext_iot.adr.ui.screens.base import ChromeScreen


class DetailScreen(ChromeScreen):
    """Read-only JSON for one resource. Editing is deliberately not offered."""

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("y", "back", "Close", show=False),
        Binding("j", "back", "Close", show=False),
    ]

    def __init__(
        self,
        spec: Optional[ResourceSpec],
        payload: Dict[str, Any],
        title: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.spec = spec
        self.payload = redact(payload)
        self._title = title or (spec.title if spec is not None else "Resource")
        self._name = name

    def compose_content(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="json-body")

    def on_mount(self) -> None:
        try:
            body = json.dumps(self.payload, indent=2, sort_keys=True, default=str)
        except (TypeError, ValueError):  # pragma: no cover - payloads are JSON already
            body = str(self.payload)
        syntax_theme = (
            "ansi_light"
            if getattr(self.app, "_theme_name", "dark") == "light"
            else "ansi_dark"
        )
        self.query_one("#json-body", Static).update(
            Syntax(body, "json", theme=syntax_theme, word_wrap=True)
        )
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)

    def resource_name(self) -> str:
        if self._name is not None:
            return self._name
        if self.spec is not None:
            return str(self.spec.row_id(self.payload))
        return str(self.payload.get("name") or "")

    def breadcrumb(self) -> str:
        return f"{self._title.lower()} {self.resource_name()}"

    def guide(self) -> Guide:
        return Guide(
            about=(
                f"The complete record for this {self._title.lower()}, exactly as the service "
                "returns it - including fields the table has no room for."
            ),
            runs="Already loaded  ·  no further call is made to open this view",
            note=(
                "Read-only by design. Change a resource through its actions or the equivalent "
                "az command, so the change is auditable."
            ),
        )

    def action_back(self) -> None:
        self.app.pop_screen_safely()
