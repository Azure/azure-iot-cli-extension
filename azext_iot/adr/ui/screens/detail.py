# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Detail view: the resource as dim field names and values; raw JSON only on request."""

import json
import re
import shlex
from typing import Any, Dict, Optional

from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from azext_iot.adr.ui.core.redaction import redact
from azext_iot.adr.ui.core.spec import Guide, ResourceSpec
from azext_iot.adr.ui.screens.base import BACK, FOCUS, HELP, ChromeScreen
from azext_iot.adr.ui.theme import FRAME_WIDTH, style_for
from azext_iot.adr.ui.widgets.minimal import GUTTER, Clickable, control_text, key_value_rows, palette_of

_STATUS_FIELDS = frozenset((
    "state", "status", "linking", "readiness", "membership", "enablement", "provisioning", "health",
))


class DetailScreen(ChromeScreen):
    """Read-only fields for one resource. Editing is deliberately not offered here."""

    CONTENT_SCROLLS = True
    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("y", "toggle_json", "Raw JSON", show=False),
    ]

    def __init__(
        self,
        spec: Optional[ResourceSpec],
        payload: Dict[str, Any],
        title: Optional[str] = None,
        name: Optional[str] = None,
        scope=None,
        count=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.spec = spec
        self.payload = redact(payload)
        self._title = title or (spec.title if spec is not None else "Resource")
        self._name = name
        self._count = count
        self.scope = dict(scope or {})
        self.show_json = False

    def compose_title_extras(self) -> ComposeResult:
        # The page's own controls: Tab reaches them, Enter or Space runs them, the letter is an
        # accelerator. Actions appear only when this resource has any.
        yield Clickable("", action="app.actions", id="actions-control", classes="page-control", focusable=True)
        yield Clickable("", action="screen.toggle_json", id="json-control", classes="page-control", focusable=True)

    def compose_content(self) -> ComposeResult:
        yield Static("", id="detail-name", classes="detail-name")
        yield Static("", id="detail-fields", classes="detail-fields")
        yield Static("", id="json-body")
        if self.spec and self.spec.children:
            yield Static("open", classes="detail-label")
            # Links flow left to right and wrap onto further rows; never clipped at 80 columns.
            with Vertical(id="detail-links"):
                for line in self._link_lines(self._links_width()):
                    with Horizontal(classes="link-row"):
                        for child in line:
                            yield Clickable(
                                "", action=f"screen.open_child('{child.kind}')", id=f"child-{child.kind}",
                                focusable=True,
                            )
        if self._read_command():
            yield Static("read with", classes="detail-label")
            yield Static("", id="detail-read")

    def on_mount(self) -> None:
        self._paint()
        self.query_one("#json-body", Static).display = False
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)
        # Start on the first page control, so Enter does the obvious thing and Tab continues.
        self.paint_controls()
        self.focus_first_control()

    def paint_controls(self) -> None:
        has_actions = getattr(self.app, "has_actions", None)
        visible = bool(self.spec is not None and has_actions is not None and has_actions(self.spec, self.payload))
        self.show_control("actions-control", visible, control_text(self, "Actions"))
        self.show_control("json-control", True, control_text(self, "Fields" if self.show_json else "Raw JSON"))

    def repaint_theme(self) -> None:
        super().repaint_theme()
        self._paint()
        if self.show_json:
            self.show_json = False
            self.action_toggle_json()

    def _paint(self) -> None:
        colors = palette_of(self)
        name = Text(no_wrap=True, overflow="ellipsis")
        name.append(GUTTER, style=colors["accent"])
        name.append(self.resource_name(), style=f"bold {colors['text']}")
        self.query_one("#detail-name", Static).update(name)
        self.query_one("#detail-fields", Static).update(key_value_rows(self, self._fields()))
        for child in self.spec.children if self.spec else ():
            self.query_one(f"#child-{child.kind}", Clickable).update(self._link_text(child))
        if self._read_command():
            command, _, note = self._read_command().partition("  \u00b7  ")
            read = Text(command.strip(), style=colors["text"])
            if note:
                read.append(f"  \u00b7 {note.strip()}", style=colors["dim"])
            self.query_one("#detail-read", Static).update(read)

    _LINK_GAP = 3

    def _links_width(self) -> int:
        try:
            width = self.app.size.width
        except Exception:  # noqa: BLE001 - not mounted yet
            width = FRAME_WIDTH
        return max(20, min(FRAME_WIDTH, width - 4))

    @staticmethod
    def _link_label(child) -> str:
        label = child.display_label
        return label[:1].upper() + label[1:]

    def _link_lines(self, width: int):
        lines, line, used = [], [], 0
        for child in self.spec.children if self.spec else ():
            size = len(self._link_label(child))
            needed = size if not line else used + self._LINK_GAP + size
            if line and needed > width:
                lines.append(line)
                line, needed = [], size
            line.append(child)
            used = needed
        if line:
            lines.append(line)
        return lines

    def on_resize(self, _event) -> None:
        if not (self.spec and self.spec.children):
            return
        current = [[c.id for c in row.children] for row in self.query(".link-row").results()]
        wanted = [[f"child-{c.kind}" for c in line] for line in self._link_lines(self._links_width())]
        if current != wanted:
            self.call_after_refresh(self._rebuild_links)

    async def _rebuild_links(self) -> None:
        holder = self.query_one("#detail-links", Vertical)
        await holder.remove_children()
        rows = []
        for line in self._link_lines(self._links_width()):
            rows.append(Horizontal(*[
                Clickable(self._link_text(child), action=f"screen.open_child('{child.kind}')",
                          id=f"child-{child.kind}", focusable=True)
                for child in line
            ], classes="link-row"))
        await holder.mount_all(rows)
        self.fit_layout()

    def _link_text(self, child) -> Text:
        return Text(self._link_label(child), style=Style.parse(palette_of(self)["accent"]), no_wrap=True)

    def _resource_group(self) -> str:
        if self.scope.get("resource_group_name"):
            return str(self.scope["resource_group_name"])
        match = re.search(r"/resourceGroups/([^/]+)", str(self.payload.get("id", "")), re.IGNORECASE)
        return match.group(1) if match else ""

    def _read_command(self) -> str:
        """A copyable az read command: ``ns show`` for namespaces, else the kind's documented list
        command with known placeholders filled in. Non-command guide text is never shown here.

        The subscription radar is browsing is always explicit: after a scope change it is not the
        CLI default, and a copied command must read the same resource."""
        if not self.spec:
            return ""
        group = self._resource_group()
        subscription = self.scope.get("subscription_id")
        pinned = f" --subscription {shlex.quote(str(subscription))}" if subscription else ""
        if self.spec.kind == "namespace":
            name = self.resource_name()
            if not (name and group):
                return ""
            return f"az iot adr ns show -n {shlex.quote(name)} -g {shlex.quote(group)}{pinned}"
        runs = self.spec.guide.runs if self.spec.guide else ""
        if not runs.startswith("az "):
            return ""
        command, sep, note = runs.partition("·")
        values = {"<namespace>": self.scope.get("namespace_name"), "<resource-group>": group,
                  "<group>": self.scope.get("group_name"), "<job>": self.scope.get("job_name")}
        for placeholder, value in values.items():
            if value:
                command = command.replace(placeholder, shlex.quote(str(value)))
        if "<" in command or "|" in command:
            # Shown only when it would run as printed.
            return ""
        command = command.strip() + pinned
        return f"{command}  ·  {note.strip()}" if sep else command

    def _fields(self):
        """Every declared column, in order, as ``(field, value, colour)``; empty values skipped."""
        theme = getattr(self.app, "theme_tokens", None)
        rows = []
        for column in self.spec.columns if self.spec else ():
            try:
                value = column.extract(self.payload)
            except Exception:  # noqa: BLE001 - a partial payload must not hide the others
                value = None
            if value in (None, "", [], {}):
                continue
            style = None
            if column.style is not None and column.key in _STATUS_FIELDS:
                try:
                    style = style_for(column.style(self.payload), theme) or None
                except Exception:  # noqa: BLE001
                    style = None
            rows.append((column.label.lower(), str(value), style))
        if not rows:
            rows.append(("name", self.resource_name(), None))
        return rows

    def action_toggle_json(self) -> None:
        """Raw, redacted JSON replaces the field list until ``y`` is pressed again."""
        self.show_json = not self.show_json
        body = self.query_one("#json-body", Static)
        if self.show_json:
            syntax_theme = ("ansi_dark" if getattr(self.app, "_theme_name", "terminal") in {"dark", "high-contrast"}
                            else "ansi_light")
            text = json.dumps(self.payload, indent=2, sort_keys=True, default=str)
            body.update(Syntax(text, "json", theme=syntax_theme, word_wrap=True, background_color="default"))
        body.display = self.show_json
        self.query_one("#detail-fields", Static).display = not self.show_json
        self.refresh_keys()

    def resource_name(self) -> str:
        if self._name is not None:
            return self._name
        if self.payload.get("name"):
            return str(self.payload["name"])
        if self.spec is not None:
            return str(self.spec.row_id(self.payload))
        return ""

    def breadcrumb(self) -> str:
        return f"{self._title.lower()} {self.resource_name()}"

    def title_parts(self):
        if self.spec is None:
            return (self._title, None)
        return (self.spec.title_plural, self._count)

    def keys(self):
        # Actions, raw JSON and child lists are page controls that name their own keys.
        return [FOCUS, BACK, HELP]

    def guide(self) -> Guide:
        return Guide(
            about=(
                f"The complete record for this {self._title.lower()}, exactly as the service "
                "returns it - including fields the table has no room for."
            ),
            runs="Already loaded  \u00b7  no further call is made to open this view",
            note=(
                "Read-only by design. Change a resource through its actions or the equivalent "
                "az command, so the change is auditable."
            ),
        )

    def action_back(self) -> None:
        self.app.pop_screen_safely()

    def selected_payload(self):
        return self.payload

    def action_open_child(self, kind: str) -> None:
        for child in self.spec.children if self.spec else ():
            if child.kind == kind:
                self.app.open_scoped_child(child, self.scope)
                return

    def on_key(self, event):
        for child in self.spec.children if self.spec else ():
            if child.key == event.key:
                event.stop()
                self.app.open_scoped_child(child, self.scope)
                return

    def on_button_pressed(self, event):
        """Kept for callers that still post button presses; child links are text now."""
        if event.button.id and event.button.id.startswith("child-"):
            self.action_open_child(event.button.id[len("child-"):])
