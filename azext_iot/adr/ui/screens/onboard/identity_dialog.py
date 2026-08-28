# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the repo root for license information.
# --------------------------------------------------------------------------------------------

"""Identity chooser used by namespace, DPS, Hub, and Software Updates pickers."""

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, LoadingIndicator, Static

from azext_iot.adr.ui.core.spec import STYLE_ERROR
from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice,
    USER_ASSIGNED,
    has_uami,
    system_choice,
)
from azext_iot.adr.ui.theme import style_for


class IdentityModeButton(Button):
    """Identity mode button with horizontal keyboard navigation."""

    BINDINGS = [
        Binding("left", "previous_mode", show=False),
        Binding("right", "next_mode", show=False),
    ]

    def action_previous_mode(self) -> None:
        self.screen.action_focus_identity_mode(-1)

    def action_next_mode(self) -> None:
        self.screen.action_focus_identity_mode(1)


class IdentityUamiTable(DataTable):
    """UAMI list where Up from the first row returns to identity modes."""

    BINDINGS = [Binding("up", "identity_up", show=False)]

    def action_identity_up(self) -> None:
        if self.cursor_coordinate.row <= 0:
            self.screen.action_focus_identity_modes()
            return
        self.action_cursor_up()


class IdentityTopInput(Input):
    """Top input in an identity view; Up returns to the identity mode row."""

    BINDINGS = [Binding("up", "identity_modes", show=False)]

    def action_identity_modes(self) -> None:
        self.screen.action_focus_identity_modes()


class IdentityChoiceDialog(ModalScreen[Optional[IdentityChoice]]):
    """Make one link-direction identity decision without losing onboarding context."""

    BINDINGS = [
        Binding("escape", "cancel", "Back to resources", show=True),
        Binding("slash", "filter_uamis", "Filter UAMIs", show=True, key_display="/"),
    ]

    _MODE_BUTTONS = ("identity-sami", "identity-uami", "identity-new")

    def __init__(
        self,
        catalog,
        resource_label: str,
        purpose: str,
        subscription_id: str,
        resource_group_name: str,
        location: str,
        current: Optional[IdentityChoice] = None,
        resource: Optional[dict] = None,
        pane_left: Optional[int] = None,
        pane_top: Optional[int] = None,
        pane_height: Optional[int] = None,
        pane_width: Optional[int] = None,
    ):
        super().__init__()
        self.catalog = catalog
        self.resource_label = resource_label
        self.purpose = purpose
        self.subscription_id = subscription_id
        self.resource_group_name = resource_group_name
        self.location = location
        self.current = current or system_choice()
        self.resource = resource or {}
        self.pane_left = pane_left
        self.pane_top = pane_top
        self.pane_height = pane_height
        self.pane_width = pane_width
        self._uamis = []
        self._uami_filter = ""
        self._active_mode = "identity-sami"

    def compose(self) -> ComposeResult:
        with Vertical(id="identity-dialog"):
            yield Label(Text("Managed identity", style="bold"), classes="modal-title")
            yield Static(
                f"{self.resource_label}\n{self.purpose}",
                id="identity-context",
            )
            yield Static(
                f"Current setup choice: {self.current.label}",
                id="identity-current",
            )
            yield Static(
                "System-assigned is the simplest choice. Use a UAMI when the same "
                "identity must be managed independently or shared.",
                id="identity-explanation",
            )
            with Horizontal(id="identity-actions"):
                yield IdentityModeButton(
                    "Use system-assigned",
                    id="identity-sami",
                )
                yield IdentityModeButton("Choose existing UAMI", id="identity-uami")
                yield IdentityModeButton("Create UAMI", id="identity-new")
            yield LoadingIndicator(id="identity-loading")
            yield Static("", id="identity-status")
            yield IdentityTopInput(
                placeholder="filter UAMIs by name or resource group...",
                id="identity-filter",
            )
            yield IdentityUamiTable(id="identity-table", cursor_type="row")
            with Vertical(id="identity-new-form"):
                yield Label("Create user-assigned identity", classes="section-title")
                with Horizontal(classes="form-field"):
                    yield Label("Name", classes="form-label")
                    yield IdentityTopInput(
                        id="identity-name",
                        placeholder="connectivity-identity",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Resource group", classes="form-label")
                    yield Input(
                        id="identity-rg",
                        value=self.resource_group_name,
                        placeholder="resource group",
                    )
                with Horizontal(classes="form-field"):
                    yield Label("Azure region", classes="form-label")
                    yield Input(
                        id="identity-location",
                        value=self.location,
                        placeholder="for example, eastus2",
                    )
                yield Static("", id="identity-error")
                with Horizontal(classes="modal-buttons"):
                    yield Button("Back", id="identity-new-back")
                    yield Button("Add identity", id="identity-new-confirm")
            with Horizontal(classes="modal-buttons", id="identity-footer"):
                yield Button(
                    "Back to resources",
                    id="identity-cancel",
                )

    def on_mount(self) -> None:
        if (
            self.pane_top is not None
            and self.pane_left is not None
            and self.pane_height is not None
            and self.pane_width is not None
        ):
            self.styles.align_horizontal = "left"
            self.styles.align_vertical = "top"
            panel = self.query_one("#identity-dialog", Vertical)
            panel.styles.width = self.pane_width
            panel.styles.height = self.pane_height
            panel.styles.margin = (
                self.pane_top,
                0,
                0,
                self.pane_left,
            )
        self.query_one("#identity-loading", LoadingIndicator).display = False
        self.query_one("#identity-table", DataTable).display = False
        self.query_one("#identity-filter", Input).display = False
        self.query_one("#identity-new-form", Vertical).display = False
        self.query_one("#identity-sami", Button).focus()

    def _style(self, token: str) -> str:
        return style_for(token, getattr(self.app, "theme_tokens", None))

    def _show_uamis(self) -> None:
        self._active_mode = "identity-uami"
        self.query_one("#identity-new-form", Vertical).display = False
        self.query_one("#identity-footer", Horizontal).display = True
        table = self.query_one("#identity-table", DataTable)
        table.clear(columns=True)
        table.display = False
        identity_filter = self.query_one("#identity-filter", Input)
        identity_filter.display = True
        identity_filter.value = self._uami_filter
        self.query_one("#identity-loading", LoadingIndicator).display = True
        self.query_one("#identity-status", Static).update(
            Text("Loading user-assigned identities...", style="dim")
        )
        self.run_worker(self._load_uamis, thread=True, name="identity-uamis")

    def _load_uamis(self) -> None:
        try:
            identities = self.catalog.user_assigned_identities()
            problem = ""
        except Exception as error:  # noqa: BLE001 - shown in the chooser
            identities = []
            problem = str(error)
        self.app.call_from_thread(self._apply_uamis, identities, problem)

    def _apply_uamis(self, identities, problem: str) -> None:
        self.query_one("#identity-loading", LoadingIndicator).display = False
        status = self.query_one("#identity-status", Static)
        table = self.query_one("#identity-table", DataTable)
        self._uamis = list(identities or [])
        if problem:
            status.update(
                Text(
                    f"Could not list user-assigned identities: {problem}",
                    style=f"bold {self._style(STYLE_ERROR)}",
                )
            )
            return
        if not self._uamis:
            status.update(
                Text(
                    "No user-assigned identities found. Choose Create UAMI.",
                    style="dim",
                )
            )
            return
        self._paint_uamis()
        table.display = True
        table.focus()

    def _visible_uamis(self):
        needle = self._uami_filter.strip().casefold()
        if not needle:
            return list(self._uamis)
        return [
            identity
            for identity in self._uamis
            if needle in str(identity.get("name") or "").casefold()
            or needle in _resource_group(str(identity.get("id") or "")).casefold()
            or needle in str(identity.get("id") or "").casefold()
        ]

    def _paint_uamis(self) -> None:
        status = self.query_one("#identity-status", Static)
        table = self.query_one("#identity-table", DataTable)
        table.clear(columns=True)
        table.add_columns("NAME", "RESOURCE GROUP", "REGION", "ATTACHED", "PRINCIPAL")
        visible = self._visible_uamis()
        for identity in visible:
            resource_id = str(identity.get("id") or "")
            table.add_row(
                str(identity.get("name") or ""),
                _resource_group(resource_id),
                str(identity.get("location") or ""),
                "yes" if has_uami(self.resource, resource_id) else "no",
                str(
                    identity.get("principalId")
                    or identity.get("principal_id")
                    or ""
                )[:18],
                key=resource_id,
            )
        if visible:
            count = (
                f"{len(visible)} of {len(self._uamis)}"
                if len(visible) != len(self._uamis)
                else str(len(visible))
            )
            status.update(
                Text(
                    f"{count} identities · / filters · Enter selects",
                    style="dim",
                )
            )
        else:
            status.update(
                Text(
                    "No identities match this filter.",
                    style="dim",
                )
            )

    def _show_new(self) -> None:
        self._active_mode = "identity-new"
        self.query_one("#identity-table", DataTable).display = False
        self.query_one("#identity-filter", Input).display = False
        self.query_one("#identity-loading", LoadingIndicator).display = False
        self.query_one("#identity-status", Static).update("")
        self.query_one("#identity-footer", Horizontal).display = False
        self.query_one("#identity-new-form", Vertical).display = True
        self.query_one("#identity-name", Input).focus()

    def _create_choice(self) -> Optional[IdentityChoice]:
        name = self.query_one("#identity-name", Input).value.strip()
        group = self.query_one("#identity-rg", Input).value.strip()
        location = self.query_one("#identity-location", Input).value.strip()
        problem = ""
        if not name:
            problem = "a name is required"
        elif not group:
            problem = "a resource group is required"
        elif not location:
            problem = "an Azure region is required"
        if problem:
            self.query_one("#identity-error", Static).update(
                Text(problem, style=f"bold {self._style(STYLE_ERROR)}")
            )
            return None
        resource_id = (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{group}"
            f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
        )
        return IdentityChoice(
            mode=USER_ASSIGNED,
            uami_id=resource_id,
            uami_name=name,
            create_uami=True,
            uami_resource_group=group,
            uami_location=location,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "identity-table":
            return
        index = event.data_table.cursor_coordinate.row
        visible = self._visible_uamis()
        if not (0 <= index < len(visible)):
            return
        identity = visible[index]
        self.dismiss(
            IdentityChoice(
                mode=USER_ASSIGNED,
                uami_id=str(identity.get("id") or ""),
                uami_name=str(identity.get("name") or ""),
                principal_id=str(
                    identity.get("principalId")
                    or identity.get("principal_id")
                    or ""
                ),
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "identity-sami":
            self._active_mode = "identity-sami"
            self.dismiss(system_choice())
        elif button_id == "identity-uami":
            self._show_uamis()
        elif button_id == "identity-new":
            self._show_new()
        elif button_id == "identity-new-confirm":
            choice = self._create_choice()
            if choice is not None:
                self.dismiss(choice)
        elif button_id == "identity-new-back":
            self.query_one("#identity-new-form", Vertical).display = False
            self.query_one("#identity-footer", Horizontal).display = True
            self.query_one("#identity-sami", Button).focus()
        else:
            self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "identity-filter":
            return
        self._uami_filter = event.value
        if self._uamis:
            self._paint_uamis()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "identity-filter":
            self.query_one("#identity-table", DataTable).focus()

    def action_filter_uamis(self) -> None:
        identity_filter = self.query_one("#identity-filter", Input)
        if identity_filter.display:
            identity_filter.focus()

    def action_focus_identity_mode(self, direction: int) -> None:
        buttons = [
            self.query_one(f"#{button_id}", IdentityModeButton)
            for button_id in self._MODE_BUTTONS
        ]
        focused = self.app.focused
        if focused not in buttons:
            buttons[0].focus()
            return
        index = buttons.index(focused)
        buttons[(index + direction) % len(buttons)].focus()

    def action_focus_identity_modes(self) -> None:
        """Return from the current identity content to its mode button."""
        self.query_one(f"#{self._active_mode}", IdentityModeButton).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)


def _resource_group(resource_id: str) -> str:
    parts = resource_id.split("/")
    for index, part in enumerate(parts):
        if part.casefold() == "resourcegroups" and index + 1 < len(parts):
            return parts[index + 1]
    return ""
