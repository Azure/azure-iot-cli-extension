# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""The guided onboarding screen: step rail, current step, and the plan."""

from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
)

from azext_iot.adr.ui.core import diagnostics
from azext_iot.adr.ui.core.spec import (
    STYLE_ACTIVE,
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_WARN,
    Guide,
    state_style,
)
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.kinds.namespace import (
    endpoint_count,
    link_readiness,
    readiness_style,
    tag_summary,
)
from azext_iot.adr.ui.screens.onboard.flow import StepState
from azext_iot.adr.ui.screens.onboard.pickers import (
    INELIGIBLE,
    ResourceCatalog,
    catalog_key,
    evaluate,
    rank,
)
from azext_iot.adr.ui.screens.onboard.create import (
    DEFAULT_CAPACITY,
    DEFAULT_DPS_SKU,
    DEFAULT_HUB_SKU,
    CreateRequest,
)
from azext_iot.adr.ui.screens.onboard.forms import parse_tags, validate_name
from azext_iot.adr.ui.screens.onboard.execution import ExecutionScreen
from azext_iot.adr.ui.screens.onboard.identity import (
    assignment_rows,
    choice_from_namespace,
    get_choice,
    has_choice,
    has_system_identity,
    has_uami,
    remove_choice,
    set_choice,
    system_choice,
)
from azext_iot.adr.ui.screens.onboard.identity_dialog import IdentityChoiceDialog
from azext_iot.adr.ui.screens.onboard.steps import build_flow
from azext_iot.adr.ui.theme import style_for
from azext_iot.adr.ui.widgets.tray import CommandPreviewDialog

_VERDICT_TOKENS = {
    "eligible": STYLE_ACTIVE,
    "warning": STYLE_WARN,
    "ineligible": STYLE_ERROR,
}

#: step id -> (creation kind, human label, context key for the request)
_CREATABLE = {
    "scope": ("resource_group", "resource group", "create_resource_group"),
    "namespace": ("namespace", "namespace", "create_namespace"),
    "dps": ("dps", "DPS", "create_dps"),
    "hub": ("hub", "IoT Hub", "create_hub"),
    "su": ("su", "update instance", "create_su"),
}
#: step id -> context key holding the chosen existing resource
_SELECTABLE = {"dps": "selected_dps", "hub": "selected_hubs", "su": "selected_sus"}

#: Steps where several resources may be chosen. A namespace accepts many messaging and
#: many updating endpoints, but exactly one DPS endpoint - so DPS is not here.
_MULTI_SELECT = {"hub": "IoT Hub", "su": "update instance"}

#: How many chosen names the rail spells out before it summarises the rest.
_RAIL_CHOICE_LIMIT = 10
_HUB_SKUS = {"F1", "B1", "B2", "B3", "S1", "S2", "S3"}
#: Shown when a picker finds nothing. An empty table with no explanation reads as a
#: broken product; every one of these ends with the action that moves the customer on.
_EMPTY_GUIDANCE = {
    "subscription": "No subscriptions found. Run 'az login' and reopen radr.",
    "scope": "No resource groups in this subscription yet - press n to create one.",
    "namespace": "No Device Registry namespaces in this resource group yet - "
                 "press n to create one.",
    "dps": "No DPS found that this namespace can use - "
           "press n to create one.",
    "hub": "No IoT Hub found that this namespace can use - press n to create one.",
    "su": "No Software Updates instance found - press n to create one, or skip this "
          "optional step.",
}

#: What each picker is looking for, used while it loads.
_PICKER_NOUNS = {
    "subscription": "subscriptions",
    "scope": "resource groups",
    "namespace": "namespaces",
    "dps": "DPS resources",
    "hub": "IoT Hubs",
    "su": "update instances",
}
_PICKER_TITLES = {
    "subscription": "Subscription",
    "scope": "Resource group",
    "namespace": "Namespace",
    "dps": "DPS",
    "hub": "IoT Hub",
    "su": "Software Updates instance",
}

#: Steps that show a picker, and the catalog method that fills it.
_PICKER_STEPS = ("subscription", "scope", "namespace", "dps", "hub", "su")

#: Columns per step. Subscriptions and resource groups have no identity to report, and a
#: column of "n/a" is worse than no column.
_PICKER_COLUMNS = {
    "subscription": (("NAME", 52), ("SUBSCRIPTION ID", 42)),
    "scope": (("NAME", 46), ("REGION", 22)),
    "namespace": (
        ("NAME", 34),
        ("RESOURCE GROUP", 26),
        ("REGION", 20),
        ("STATE", 14),
        ("LINK READINESS", 16),
        ("HUBS", 7),
        ("DPS", 6),
        ("UPDATES", 9),
        ("IDENTITY", 18),
        ("TAGS", 34),
    ),
}
_DEFAULT_PICKER_COLUMNS = (
    ("NAME", 28), ("RESOURCE GROUP", 20), ("REGION", 16), ("IDENTITY", 16),
    ("LINK READINESS", 32),
)


class SetupStepList(ListView):
    """The left rail: Right moves into the corresponding detail workspace."""

    BINDINGS = [Binding("right", "details", show=False)]

    def action_details(self) -> None:
        self.screen.action_focus_details()


class SetupCandidateTable(DataTable):
    """The right picker: Left returns to the step rail."""

    BINDINGS = [Binding("left", "steps", show=False)]

    def action_steps(self) -> None:
        self.screen.action_focus_steps()


class SetupPane(VerticalScroll):
    """Focusable detail area for steps that do not show a candidate table."""

    can_focus = True
    BINDINGS = [Binding("left", "steps", show=False)]

    def action_steps(self) -> None:
        self.screen.action_focus_steps()


class SetupFormInput(Input):
    """Creation input with optional Up/Down field navigation."""

    BINDINGS = [
        Binding("up", "previous_field", show=False),
        Binding("down", "next_field", show=False),
    ]

    def action_previous_field(self) -> None:
        self.screen.action_focus_form_control(-1)

    def action_next_field(self) -> None:
        self.screen.action_focus_form_control(1)


class SetupFormButton(Button):
    """Flat form action that participates in Up/Down navigation."""

    BINDINGS = [
        Binding("up", "previous_control", show=False),
        Binding("down", "next_control", show=False),
    ]

    def action_previous_control(self) -> None:
        self.screen.action_focus_form_control(-1)

    def action_next_control(self) -> None:
        self.screen.action_focus_form_control(1)


class OnboardScreen(ChromeScreen):
    """Walks the connectivity flow: select, plan, then apply.

    Nothing is mutated while selecting. The plan is the contract shown before apply, and
    plan-only mode never applies at all.
    """

    BINDINGS = [
        Binding("escape", "back", "Back", show=True),
        Binding("enter", "select", "Choose", show=True),
        Binding("space", "toggle_multi", "Toggle", show=False),
        Binding("p", "show_plan", "Plan", show=True),
        Binding("a", "apply", "Run setup", show=True),
        Binding("n", "create_new", "Create new", show=True),
        Binding("d", "done_step", "Done, next", show=True),
        Binding("j", "show_json", "JSON", show=True),
        Binding("i", "configure_identity", "Identity", show=True),
        Binding("slash", "start_filter", "Filter", show=True, key_display="/"),
        Binding("1,2,3,4,5,6,7,8,9", "goto_step", "Jump to step", show=False),
        Binding("x", "export", "Copy script", show=True),
        Binding("r", "reload", "Reload state", show=True),
    ]

    def __init__(self, session, scope: Dict[str, Any], namespace: Optional[Dict[str, Any]] = None,
                 catalog: Optional[ResourceCatalog] = None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.scope = dict(scope or {})
        self.context: Dict[str, Any] = dict(self.scope)
        self.context["namespace"] = namespace or {}
        self.context["_catalog"] = catalog
        if namespace:
            set_choice(
                self.context,
                "namespace",
                choice_from_namespace(namespace),
            )
        self.flow = build_flow(self.context)
        self.catalog = catalog
        self._candidates: List = []
        self._candidates_for: Optional[str] = None
        self._candidates_loading = False
        self._candidate_generation = 0
        #: A step the user jumped to. Satisfied steps are skipped by the flow, so without
        #: this there is no way to revisit one - for example to change subscription.
        self._focus_step: Optional[str] = None
        self._candidate_filter = ""
        #: Guards the rail highlight handler while the rail is repainted, so syncing the
        #: highlight does not read back as the customer choosing a step.
        self._syncing_rail = False
        # Step states are meaningless until live state has been read once; showing them
        # early would claim an existing namespace still needs creating.
        self._state_loaded = bool(namespace) or not scope.get("namespace_name")

    # -- composition -------------------------------------------------------

    def compose_content(self) -> ComposeResult:
        with Horizontal(id="setup-layout"):
            with Vertical(classes="rail", id="rail"):
                yield Static("SETUP", id="rail-title")
                # A list, not static text: arrows move through steps and the focused
                # step is what the right-hand pane acts on.
                yield SetupStepList(id="step-list")
            with SetupPane(classes="pane", id="work-pane"):
                yield Static("", id="step-heading")
                yield Static(id="step-body")
                yield Static(id="candidate-status")
                yield LoadingIndicator(id="candidate-loading")
                yield Input(placeholder="filter...", id="candidate-filter")
                yield SetupCandidateTable(id="candidates", cursor_type="row")
                # Creation happens in place. A pushed screen would lose the step rail and
                # the context the customer is working against.
                with Vertical(id="create-form"):
                    yield Static("NEW RESOURCE", id="create-kicker")
                    yield Label(Text("Create new", style="bold"), id="create-title")
                    yield Static(
                        "This is added to the plan; Azure is unchanged until Review and run.",
                        id="create-subtitle",
                    )
                    with Horizontal(classes="form-field"):
                        yield Label("Name", classes="form-label")
                        yield SetupFormInput(
                            id="create-name", placeholder="globally unique name"
                        )
                    with Horizontal(classes="form-field"):
                        yield Label("Azure region", classes="form-label")
                        yield SetupFormInput(
                            id="create-location", placeholder="for example, eastus2"
                        )
                    with Horizontal(classes="form-field", id="create-tags-row"):
                        yield Label("Tags", classes="form-label")
                        yield SetupFormInput(
                            id="create-tags",
                            placeholder="environment=dev owner=team",
                        )
                    with Horizontal(classes="form-field", id="create-sku-row"):
                        yield Label("SKU", classes="form-label")
                        yield SetupFormInput(
                            id="create-sku",
                            placeholder="S1, S2, S3, B1, B2, B3, or F1",
                        )
                    with Horizontal(classes="form-field", id="create-capacity-row"):
                        yield Label("Units", classes="form-label")
                        yield SetupFormInput(id="create-capacity", placeholder="1")
                    yield Static(
                        "Tab next field  \u00b7  Shift+Tab previous  \u00b7  "
                        "\u2191/\u2193 fields and actions  \u00b7  View plan below",
                        id="create-form-hint",
                    )
                    yield Static("", id="create-error")
                    with Horizontal(classes="modal-buttons"):
                        yield SetupFormButton("Back", id="create-cancel")
                        yield SetupFormButton("View plan", id="create-plan")
                        yield SetupFormButton(
                            "Add to setup",
                            id="create-confirm",
                            variant="primary",
                        )
        yield Static(id="command-hint")

    def on_mount(self) -> None:
        self.query_one("#create-form", Vertical).display = False
        self.query_one("#candidate-loading", LoadingIndicator).display = False
        self.query_one("#candidate-filter", Input).display = False
        self.refresh_view()
        # Focus the picker, or arrow keys would go nowhere on arrival.
        self.query_one("#candidates", DataTable).focus()
        # Principle O3: derive every step from live state rather than trusting a snapshot.
        if self.session is not None and self.context.get("namespace_name") \
                and not self._state_loaded:
            self.run_worker(self._reload_namespace, thread=True, name="onboard-reload")
        if self._state_loaded:
            self._reload_candidates()
        self._probe_grant_rights()

    def action_focus_steps(self) -> None:
        """Move keyboard focus to the step rail without changing the active step."""
        self.query_one("#step-list", SetupStepList).focus()

    def action_focus_details(self) -> None:
        """Move keyboard focus to the control serving the selected step."""
        form = self.query_one("#create-form", Vertical)
        candidates = self.query_one("#candidates", SetupCandidateTable)
        if form.display:
            self.query_one("#create-name", Input).focus()
        elif candidates.display:
            candidates.focus()
        else:
            self.query_one("#work-pane", SetupPane).focus()

    def action_focus_form_control(self, direction: int) -> None:
        """Move Up/Down through visible fields and form actions."""
        step = self.active_step()
        entry = _CREATABLE.get(step.id) if step is not None else None
        if entry is None:
            return
        kind = entry[0]
        field_ids = ["create-name", "create-location"]
        if kind == "namespace":
            field_ids.append("create-tags")
        if kind == "hub":
            field_ids.extend(("create-sku", "create-capacity"))
        elif kind == "dps":
            field_ids.append("create-capacity")
        controls = [
            self.query_one(f"#{field_id}", SetupFormInput)
            for field_id in field_ids
        ]
        controls.extend([
            self.query_one("#create-cancel", SetupFormButton),
            self.query_one("#create-plan", SetupFormButton),
            self.query_one("#create-confirm", SetupFormButton),
        ])
        focused = self.app.focused
        if focused not in controls:
            controls[0].focus()
            return
        index = controls.index(focused)
        controls[max(0, min(index + direction, len(controls) - 1))].focus()

    def _probe_grant_rights(self) -> None:
        """Check the simple permission model at every involved resource group."""
        subscription = self.context.get("subscription_id")
        if self.session is None or not subscription:
            return
        requirements = self._permission_requirements()
        signature = tuple(
            (scope, tuple(sorted(actions)))
            for scope, actions in sorted(requirements.items())
        )
        if self.context.get("_grant_probe_for") == signature:
            return
        self.context["_grant_probe_for"] = signature
        self.context["permission_checking"] = True
        self.run_worker(
            lambda: self._read_grant_rights(signature, requirements),
            thread=True,
            name="onboard-rbac",
        )

    def _permission_requirements(self):
        from azext_iot.adr.ui.core.rbac import ROLE_WRITE_ACTION

        subscription = self.context.get("subscription_id") or ""
        subscription_scope = f"/subscriptions/{subscription}"
        requirements = {}

        def group_scope(group):
            return (
                f"/subscriptions/{subscription}/resourceGroups/{group}"
                if group
                else ""
            )

        planned_group = self.context.get("create_resource_group")

        def parent_scope(group):
            if planned_group is not None and planned_group.name == group:
                return subscription_scope
            return group_scope(group)

        def require(scope, *actions, role_write=False):
            if not scope:
                return
            requirements.setdefault(scope, set()).update(actions)
            if role_write:
                requirements[scope].add(ROLE_WRITE_ACTION)

        namespace_group = self.context.get("resource_group_name")
        namespace_scope = (
            f"{group_scope(namespace_group)}/providers/"
            f"Microsoft.DeviceRegistry/namespaces/"
            f"{self.context.get('namespace_name') or ''}"
        )
        namespace_exists = bool(self.context.get("namespace"))
        require(
            namespace_scope if namespace_exists else parent_scope(namespace_group),
            "Microsoft.DeviceRegistry/namespaces/write",
            role_write=not namespace_exists,
        )
        if namespace_exists:
            require(namespace_scope, role_write=True)

        for kind, key, action in (
            ("dps", "selected_dps", "Microsoft.Devices/provisioningServices/write"),
            ("hub", "selected_hubs", "Microsoft.Devices/IotHubs/write"),
            ("su", "selected_sus", "Microsoft.DeviceUpdate/updateInstances/write"),
        ):
            selected = self.context.get(key)
            resources = (
                [selected]
                if kind == "dps" and selected is not None
                else list(selected or [])
            )
            for resource in resources:
                choice = get_choice(
                    self.context,
                    kind,
                    resource.resource_id,
                )
                raw = resource.raw or {}
                identity_ready = (
                    has_uami(raw, choice.uami_id)
                    if choice.is_user_assigned
                    else has_system_identity(raw)
                )
                require(
                    resource.resource_id,
                    *((action,) if not identity_ready else ()),
                    role_write=True,
                )
            request = self.context.get(f"create_{kind}")
            if request is not None:
                require(
                    parent_scope(request.resource_group_name),
                    action,
                    role_write=True,
                )
        identity_choices = list(
            (self.context.get("identity_choices") or {}).values()
        )
        for key in ("create_namespace", "create_dps", "create_hub", "create_su"):
            request = self.context.get(key)
            if request is not None:
                identity_choices.append(request.identity)
        for choice in identity_choices:
            if not choice.is_user_assigned:
                continue
            identity_scope = (
                parent_scope(choice.uami_resource_group)
                if choice.create_uami
                else choice.uami_id
            )
            require(
                identity_scope,
                "Microsoft.ManagedIdentity/userAssignedIdentities/read",
                "Microsoft.ManagedIdentity/userAssignedIdentities/assign/action",
            )
            if choice.create_uami:
                require(
                    identity_scope,
                    "Microsoft.ManagedIdentity/userAssignedIdentities/write",
                )
        if planned_group is not None:
            require(
                subscription_scope,
                "Microsoft.Resources/subscriptions/resourceGroups/write",
            )
        return requirements

    def _read_grant_rights(self, signature, requirements) -> None:
        from azext_iot.adr.ui.core.rbac import (
            ROLE_WRITE_ACTION,
            permissions_at_scope,
        )

        matrix = {}
        for scope, actions in requirements.items():
            matrix[scope] = permissions_at_scope(
                self.session, scope, sorted(actions)
            )
        role_ready = all(
            matrix.get(scope) is not None
            and matrix[scope].get(ROLE_WRITE_ACTION) is True
            for scope, actions in requirements.items()
            if ROLE_WRITE_ACTION in actions
        )
        write_ready = bool(matrix) and all(
            result is not None
            and all(allowed for action, allowed in result.items()
                    if action != ROLE_WRITE_ACTION)
            for result in matrix.values()
        )
        self.app.call_from_thread(
            self._grant_rights_read,
            signature,
            matrix,
            role_ready,
            write_ready,
        )

    def _grant_rights_read(
        self,
        signature,
        matrix,
        role_ready: bool,
        write_ready: bool,
    ) -> None:
        if self.context.get("_grant_probe_for") != signature:
            return
        self.context["permission_checking"] = False
        self.context["permission_matrix"] = matrix
        self.context["can_grant_roles"] = role_ready
        self.context["can_write_resources"] = write_ready
        self.refresh_view()

    # -- rendering ---------------------------------------------------------

    def _render_review(self, text: Text) -> None:
        """The commit point: what will run, what you must run, what is already done."""
        missing_identity = self._missing_identity_choice()
        if missing_identity is not None:
            text.append(
                "BLOCKED\n",
                style=f"bold {self._style(STYLE_ERROR)}",
            )
            text.append(
                f"Choose the managed identity for {missing_identity}. "
                "Return to that resource, highlight it, and press i.\n",
                style=self._style(STYLE_WARN),
            )
            return
        plan = self.flow.build_plan()
        runnable = [item for item in plan if item.invoke is not None]
        manual = [item for item in plan if item.action == "manual"]
        manual_grants = [
            item for item in manual if item.key != "grant-propagation"
        ]
        blocked = [item for item in plan if item.action == "blocked"]
        visible_changes = [
            item
            for item in runnable
            if not item.key.startswith("grant-")
            and item.key != "grant-propagation"
        ]

        if not runnable and not manual:
            text.append(
                "READY\n",
                style=f"bold {self._style(STYLE_ACTIVE)}",
            )
            text.append("Everything is already configured. Nothing to run.\n")
            text.append("\nNEXT  Escape returns to browsing.\n", style="bold")
            return

        heading = "PLANNED AFTER ACCESS" if manual else "CHANGES"
        text.append(f"{heading}\n", style=f"bold {self._style(STYLE_ACTIVE)}")
        text.append(
            f"{len(runnable)} operations"
            + (f" ({len(visible_changes)} resource changes)" if visible_changes else "")
            + "\n",
            style="bold",
        )
        for item in visible_changes[:6]:
            text.append(f"  \u2022 {item.description}\n")
        if len(visible_changes) > 6:
            text.append(f"  \u2022 {len(visible_changes) - 6} more; press p for details\n")

        if manual:
            text.append(
                "\nNEEDS ADMIN ACCESS\n",
                style=f"bold {self._style(STYLE_WARN)}",
            )
            text.append(
                f"{len(manual_grants)} role grants cannot be created by this account.\n"
                "Activate Owner/User Access Administrator and press r. If another "
                "administrator will grant access, press x to copy the runnable script "
                "and send it to them.\n"
            )

        if blocked:
            text.append(
                "\nBLOCKED\n",
                style=f"bold {self._style(STYLE_ERROR)}",
            )
            for item in blocked[:2]:
                text.append(f"  \u2022 {item.blocked_reason or item.description}\n")

        text.append("\nNEXT\n", style=f"bold {self._style(STYLE_ACTIVE)}")
        if blocked:
            text.append("Return to the highlighted step and resolve it before running.\n")
        elif manual:
            text.append("x Copy admin script  \u00b7  r Recheck access  \u00b7  "
                        "p Full details\n")
        else:
            text.append("a Run setup  \u00b7  p Full details  \u00b7  x Copy script\n",
                        style="bold")

    #: What the customer has settled on for a step, shown beneath it on the rail. A list,
    #: because a step may hold several choices and "+3 more" hides the very thing the
    #: customer is trying to check before running the plan.
    def _chosen_lines(self, step_id: str) -> List[str]:
        single = {
            "subscription": self.context.get("subscription_name")
            or self.context.get("subscription_id"),
            "scope": self.context.get("resource_group_name"),
            "namespace": self.context.get("namespace_name"),
        }
        if step_id in single:
            value = single[step_id]
            if step_id == "namespace" and value:
                return [
                    f"{value} · {self._identity_indicator('namespace')}"
                ]
            return [value] if value else []
        if step_id == "dps":
            chosen = self.context.get("selected_dps")
            return [
                f"{chosen.name} · "
                f"{self._identity_indicator('dps', chosen.resource_id)}"
            ] if chosen is not None else []
        if step_id in _MULTI_SELECT:
            chosen = self.context.get(_SELECTABLE[step_id]) or []
            names = [
                f"{item.name} · "
                f"{self._identity_indicator(step_id, item.resource_id)}"
                for item in chosen[:_RAIL_CHOICE_LIMIT]
            ]
            if len(chosen) > _RAIL_CHOICE_LIMIT:
                names.append(f"and {len(chosen) - _RAIL_CHOICE_LIMIT} more")
            return names
        return []

    def _identity_indicator(self, kind: str, resource_id: str = "") -> str:
        if not has_choice(self.context, kind, resource_id):
            return "choose identity"
        choice = get_choice(self.context, kind, resource_id)
        if choice.is_user_assigned:
            return f"UAMI {choice.uami_name or choice.uami_id.rsplit('/', 1)[-1]}"
        return "SAMI"

    def _missing_identity_choice(self) -> Optional[str]:
        if (
            self.context.get("namespace_name")
            and self.context.get("create_namespace") is None
            and not has_choice(self.context, "namespace")
        ):
            return f"namespace '{self.context.get('namespace_name')}'"
        dps = self.context.get("selected_dps")
        if (
            dps is not None
            and not has_choice(self.context, "dps", dps.resource_id)
        ):
            return f"DPS '{dps.name}'"
        for kind, key, label in (
            ("hub", "selected_hubs", "Hub"),
            ("su", "selected_sus", "Update Instance"),
        ):
            for resource in self.context.get(key) or []:
                if not has_choice(
                    self.context,
                    kind,
                    resource.resource_id,
                ):
                    return f"{label} '{resource.name}'"
        return None

    def _advance(self, message: str = "") -> None:
        """Move to the next unsatisfied step once a choice is made.

        Without this the pane stays on the step just completed and the customer has to
        navigate manually, which defeats the point of a guided flow.
        """
        current = self.active_step()
        self._focus_step = None
        self._candidate_filter = ""
        visible = self.flow.visible_steps()
        start = 0
        if current is not None:
            current_index = next(
                (index for index, step in enumerate(visible) if step.id == current.id),
                -1,
            )
            start = current_index + 1
        next_step = next(
            (
                step
                for step in visible[start:]
                if not self.flow.blocking(step)
                and (step.id == "review" or not step.will_hold(self.context))
            ),
            None,
        )
        if next_step is None:
            next_step = self.flow.current()
        if next_step is not None:
            self._focus_step = next_step.id
        if not self.is_mounted:
            return
        if message:
            self.flash(message, "success")
        self.refresh_view()
        self._reload_candidates()
        nxt = self.active_step()
        if nxt is not None and nxt.id in _PICKER_STEPS:
            try:
                self.query_one("#candidates", DataTable).focus()
            except Exception:  # noqa: BLE001 - focus is a convenience, never a failure
                pass

    def _pending_creation(self, step_id: str):
        """The creation queued for a step, if any."""
        entry = _CREATABLE.get(step_id)
        return self.context.get(entry[2]) if entry else None

    def active_step(self):
        """The step being worked on: an explicit jump, else the first unsatisfied one."""
        if self._focus_step is not None:
            for step in self.flow.steps:
                if step.id == self._focus_step:
                    return step
        return self.flow.current()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Arrowing through the rail changes which step the right-hand pane serves."""
        if self._syncing_rail:
            return
        rail = self.query_one("#step-list", ListView)
        # Programmatic index changes keep the rail synchronized with auto-advance. They
        # are not customer navigation and must not re-pin the previous step while focus
        # remains in the right workspace.
        if not rail.has_focus:
            return
        index = rail.index
        # The rail lists visible steps only; indexing all steps selects the wrong one
        # as soon as a hidden step sits between two visible ones.
        steps = self.flow.visible_steps()
        if index is None or not (0 <= index < len(steps)):
            return
        step = steps[index]
        self._paint_rail_selection(index)
        if step.id == self._focus_step:
            return
        self._focus_step = step.id
        self._render_body()
        self._reload_candidates()

    def action_goto_step(self) -> None:
        """Jump to a step by number, including ones already satisfied."""
        key = self.app.last_key_pressed if hasattr(self.app, "last_key_pressed") else None
        index = int(key) - 1 if key and key.isdigit() else None
        steps = self.flow.visible_steps()
        if index is None or not (0 <= index < len(steps)):
            return
        step = steps[index]
        self._focus_step = step.id
        self.flash(f"step {index + 1}: {step.title}", "info")
        self.refresh_view()
        self._reload_candidates()

    def refresh_view(self) -> None:
        # The persistent context bar is the read-only home for subscription/resource
        # group/namespace while forms expose only fields the customer can actually edit.
        self.scope.update({
            "subscription": self.context.get("subscription_name")
            or self.context.get("subscription_id"),
            "subscription_id": self.context.get("subscription_id"),
            "resource_group_name": self.context.get("resource_group_name"),
            "namespace_name": self.context.get("namespace_name"),
        })
        self._render_rail()
        self._render_body()
        self._render_candidate_status()
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)
        if self.is_mounted:
            self._probe_grant_rights()

    def _style(self, token: str) -> str:
        return style_for(token, getattr(self.app, "theme_tokens", None))

    def _render_rail(self) -> None:
        rail = self.query_one("#step-list", ListView)
        if not self._state_loaded:
            rail.clear()
            return

        focused = self.active_step()
        index = 0
        self._syncing_rail = True
        rail.clear()
        for position, (step, state) in enumerate(self.flow.states()):
            pending = self._pending_creation(step.id)
            is_set = bool(self._chosen_lines(step.id)) or pending is not None
            if state is StepState.BLOCKED or (
                state is StepState.PENDING and not is_set
            ):
                title_classes = "step-title step-muted"
            else:
                title_classes = "step-title"
            title = Label(
                f"{position + 1}. {step.title}",
                classes=title_classes,
            )
            detail = Text()
            for chosen in self._chosen_lines(step.id):
                if detail:
                    detail.append("\n")
                detail.append(
                    chosen,
                    style=(
                        self._style(STYLE_WARN)
                        if "choose identity" in chosen
                        else self._style(STYLE_ACTIVE)
                    ),
                )
            if pending is not None:
                if detail:
                    detail.append("\n")
                detail.append(
                    f"create: {pending.name} · "
                    f"{'UAMI ' + pending.identity.uami_name if pending.identity.is_user_assigned else 'SAMI'}",
                    style=self._style(STYLE_ACTIVE),
                )
            children = [title]
            if detail:
                children.append(Label(detail, classes="step-resources"))
            is_selected = focused is not None and step.id == focused.id
            rail.append(
                ListItem(
                    *children,
                    classes="selected-step" if is_selected else "",
                )
            )
            if is_selected:
                index = position
        rail.index = index
        self._paint_rail_selection(index)
        if self.is_mounted:
            # ListView dispatches the highlight caused by `rail.index` after this method
            # returns. Keep the guard through that render cycle or the old item can
            # re-pin the step we just left.
            self.call_after_refresh(self._finish_rail_sync)
        else:
            self._syncing_rail = False

    def _finish_rail_sync(self) -> None:
        focused = self.active_step()
        if focused is not None:
            index = next(
                (
                    position
                    for position, step in enumerate(self.flow.visible_steps())
                    if step.id == focused.id
                ),
                0,
            )
            self._paint_rail_selection(index)
        self._syncing_rail = False

    def _paint_rail_selection(self, index: int) -> None:
        """Highlight the active step even when navigation came from a number key."""
        rail = self.query_one("#step-list", ListView)
        for position, item in enumerate(rail.children):
            item.set_class(position == index, "selected-step")

    def _render_body(self) -> None:
        body = self.query_one("#step-body", Static)
        heading = self.query_one("#step-heading", Static)
        if not self._state_loaded:
            heading.update("Loading setup")
            body.update(Text("Reading the namespace to see what is already configured...",
                             style="dim"))
            self.query_one("#command-hint", Static).update("")
            return
        step = self.active_step()
        if step is None:
            heading.update("Setup complete")
            body.update(
                Text(
                    "Connectivity is configured. Press p to review the plan.",
                    style=f"bold {self._style(STYLE_ACTIVE)}",
                )
            )
            self.query_one("#command-hint", Static).update("")
            return
        heading.update(step.title)
        heading.display = True
        text = Text()
        blockers = self.flow.blocking(step)
        if blockers:
            reason = step.blocked_reason or (
                "Complete " + ", ".join(blocker.title for blocker in blockers) + " first."
            )
            text.append("\nBefore you continue\n", style=f"bold {self._style(STYLE_WARN)}")
            text.append(f"{reason}\n", style=self._style(STYLE_WARN))
        pending = self._pending_creation(step.id)
        if pending is not None:
            text.append(
                f"\nPlanned  create {pending.label} '{pending.name}'\n",
                style=f"bold {self._style(STYLE_ACTIVE)}",
            )
            text.append(
                "Press n to edit it, or choose an existing resource to replace it.\n",
                style="dim",
            )
        if step.id == "review":
            self._render_review(text)
            body.update(text)
            self._render_command_hint(step)
            return
        if step.id == "subscription":
            text.append("Press Enter to use a different subscription.\n", style="dim")
        elif step.id == "scope":
            text.append("Press Enter to use an existing resource group, or n to create "
                        "one.\n", style="dim")
        elif step.id == "namespace":
            text.append("Press n to create a new namespace, or escape and pick an existing "
                        "one from the namespace list. Identity is chosen before continuing.\n",
                        style="dim")
        elif step.id == "dps":
            text.append("Links one DPS to the namespace before any IoT Hub. Press Enter "
                        "to choose the DPS and its caller identity, or n to create one. "
                        "A missing identity can be enabled during setup.\n", style="dim")
        elif step.id == "hub":
            text.append("Links IoT Hubs to the namespace. Enter selects as many as you "
                        "need; i chooses SAMI or UAMI for the highlighted Hub; n creates "
                        "one; d finishes. A missing identity can be enabled during setup.\n",
                        style="dim")
        elif step.id == "su":
            text.append("Optional. Links Software Updates instances so this namespace can "
                        "run update jobs. Enter selects; i chooses SAMI or UAMI for the "
                        "highlighted instance; n creates one; d finishes or skips.\n",
                        style="dim")
        elif step.id == "permissions":
            text.append(
                "Linking only works if the namespace and the linked resource can call each "
                "other, which needs two role assignments per resource:\n"
                "  the namespace identity -> Contributor on the DPS/Hub "
                "(plus IoT Hub Data Contributor on a Hub)\n"
                "  the DPS/Hub identity   -> Contributor on the namespace\n",
                style="dim",
            )
            text.append(self._grant_rights_note(), style="dim")
        pending = self._pending_summary()
        if pending:
            text.append(
                f"\nTo create  {pending}\n",
                style=f"bold {self._style(STYLE_ACTIVE)}",
            )
        runnable = [item for item in self.flow.build_plan() if item.invoke is not None]
        if runnable:
            text.append(
                f"\n{len(runnable)} change(s) ready - go to 'Review and run' to apply them\n",
                style=f"bold {self._style(STYLE_ACTIVE)}",
            )
        body.update(text)
        self._render_command_hint(step)

    def _grant_rights_note(self) -> str:
        """Say plainly whether radr will make the grants, and if not, why not."""
        if self.context.get("permission_checking"):
            return "radr is checking resource and role access at every involved scope...\n"
        verdict = self.context.get("can_grant_roles")
        writes = self.context.get("can_write_resources")
        if verdict is True and writes is True:
            return (
                "Permission preflight passed at every involved resource group. "
                "radr can make resource changes and role assignments.\n"
            )
        if writes is False:
            return (
                "Resource-write access is missing at one or more involved resource "
                "groups. Owner, or Contributor plus User Access Administrator, is "
                "the simplest supported permission model.\n"
            )
        if verdict is False:
            return ("Your account may not create role assignments here, so radr will list "
                    "them instead. Activate Owner or User Access Administrator (PIM) and "
                    "press r, or press x to copy a runnable admin script.\n")
        return ("radr is checking whether your account may create role assignments...\n")

    def _pending_summary(self) -> str:
        parts = []
        for _step_id, (_kind, label, context_key) in _CREATABLE.items():
            request = self.context.get(context_key)
            if request is not None:
                parts.append(f"create {label} '{request.name}'")
        return "; ".join(parts)

    def _render_command_hint(self, step) -> None:
        items = [item for item in self.flow.build_plan() if item.key.startswith(step.id)]
        command = next((item.command for item in items if item.command), "")
        hint = self.query_one("#command-hint", Static)
        hint.update(
            Text(command, style=self._style(STYLE_ACTIVE)) if command else Text("")
        )

    # -- candidates --------------------------------------------------------

    def _reload_candidates(self) -> None:
        if self.catalog is None:
            return
        step = self.active_step()
        if step is None or step.id == self._candidates_for:
            return
        self._candidate_generation += 1
        generation = self._candidate_generation
        if step.id not in _PICKER_STEPS:
            self._candidates, self._candidates_for = [], step.id
            self._candidates_loading = False
            self.query_one("#candidate-loading", LoadingIndicator).display = False
            self.query_one("#candidates", SetupCandidateTable).clear(columns=True)
            self.query_one("#candidates", SetupCandidateTable).display = False
            self._render_candidate_status()
            return
        self._candidates_for = step.id
        # Never leave the previous step's rows visible while a slower Azure list call
        # runs; that makes a Hub look like a DPS candidate (and vice versa).
        self._candidates = []
        self._candidate_filter = ""
        self._candidates_loading = True
        table = self.query_one("#candidates", SetupCandidateTable)
        was_focused = table.has_focus
        table.clear(columns=True)
        table.display = False
        self.query_one("#candidate-loading", LoadingIndicator).display = True
        if was_focused:
            self.query_one("#work-pane", SetupPane).focus()
        self._render_candidate_status()
        step_id = step.id
        self.run_worker(
            lambda: self._load_candidates(step_id, generation),
            thread=True,
            name=f"onboard-candidates-{step_id}",
        )

    def _render_candidate_status(self) -> None:
        """Say what the picker is doing; an empty table alone is ambiguous."""
        status = self.query_one("#candidate-status", Static)
        step = self.active_step()
        if step is None or step.id not in _PICKER_STEPS:
            status.update("")
            return
        if self._candidates_loading:
            noun = _PICKER_NOUNS.get(step.id, "candidates")
            status.update(Text(f"Loading {noun} from Azure...", style="dim"))
        elif not self._candidates:
            failure = None
            if self.catalog is not None:
                error_for = getattr(self.catalog, "error_for", None)
                if callable(error_for):
                    failure = error_for(
                        step.id,
                        self.context.get("resource_group_name"),
                    )
                else:
                    failure = (getattr(self.catalog, "errors", None) or {}).get(
                        catalog_key(
                            step.id,
                            self.context.get("resource_group_name"),
                        )
                    )
            if failure:
                status.update(
                    Text(
                        f"could not list candidates: {failure}",
                        style=f"bold {self._style(STYLE_ERROR)}",
                    )
                )
            else:
                status.update(
                    Text(
                        _EMPTY_GUIDANCE.get(step.id, ""),
                        style=self._style(STYLE_WARN),
                    )
                )
        else:
            shown = len(self._visible_candidates())
            total = len(self._candidates)
            summary = f"{shown} of {total}" if shown != total else f"{total}"
            hint = (
                "Enter toggles selection, i sets identity, d moves on, / filters"
                if step.id in _MULTI_SELECT
                else "Enter chooses, / filters"
            )
            status.update(Text(f"{summary} candidates - {hint}", style="dim"))

    def _load_candidates(self, step_id: str, generation: int) -> None:
        """Enumerate selectable resources on a worker; pickers never block the UI."""
        if self.catalog is None:
            return
        try:
            if step_id == "subscription":
                candidates = [
                    evaluate(resource, require_identity=False)
                    for resource in self.catalog.subscriptions()
                ]
            elif step_id == "scope":
                candidates = [
                    evaluate(resource, require_identity=False)
                    for resource in self.catalog.resource_groups()
                ]
            elif step_id == "namespace":
                candidates = [
                    evaluate(resource, require_identity=False)
                    for resource in self.catalog.namespaces(
                        self.session, self.context.get("resource_group_name")
                    )
                ]
            elif step_id == "dps":
                resources = self.catalog.provisioning_services()
                candidates = [
                    evaluate(resource, namespace_location=self._namespace_location())
                    for resource in resources
                ]
            elif step_id == "hub":
                dps = self.context.get("selected_dps")
                registered = None
                if dps is not None:
                    registered = self.catalog.registered_hub_names(dps.raw or {})
                candidates = [
                    evaluate(resource, namespace_location=self._namespace_location(),
                             registered_hub_names=registered)
                    for resource in self.catalog.hubs()
                ]
            elif step_id == "su":
                candidates = [
                    evaluate(
                        resource,
                        namespace_location=self._namespace_location(),
                    )
                    for resource in self.catalog.update_instances()
                ]
            else:
                candidates = []
        except Exception as error:  # noqa: BLE001 - an unavailable provider yields no candidates
            diagnostics.exception("candidate enumeration failed: %s", error)
            candidates = []
        self.app.call_from_thread(
            self._show_candidates,
            step_id,
            generation,
            rank(candidates),
        )

    def _namespace_location(self) -> Optional[str]:
        return (self.context.get("namespace") or {}).get("location")

    def _visible_candidates(self) -> List:
        needle = (self._candidate_filter or "").strip().lower()
        if not needle:
            return list(self._candidates)
        return [
            candidate for candidate in self._candidates
            if needle in candidate.name.lower()
            or needle in (candidate.resource_group or "").lower()
            or needle in (candidate.location or "").lower()
        ]

    def _show_candidates(self, step_id: str, generation: int, candidates) -> None:
        step = self.active_step()
        if (
            step is None
            or step.id != step_id
            or self._candidates_for != step_id
            or generation != self._candidate_generation
        ):
            return
        self._candidates = candidates
        self._candidates_loading = False
        self.query_one("#candidate-loading", LoadingIndicator).display = False
        pane = self.query_one("#work-pane", SetupPane)
        table = self.query_one("#candidates", SetupCandidateTable)
        restore_focus = pane.has_focus
        table.display = True
        self._render_candidate_status()
        self._paint_candidates()
        if restore_focus:
            table.focus()

    def _paint_candidates(self) -> None:
        table = self.query_one("#candidates", SetupCandidateTable)
        selected_key = None
        if table.row_count:
            try:
                row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
                selected_key = str(row_key.value)
            except Exception:  # noqa: BLE001 - the cursor may be between repaints
                selected_key = None
        table.clear(columns=True)
        candidates = self._visible_candidates()
        if not candidates:
            return
        # Explicit widths: the verdict decides the choice, so it must never be the
        # column pushed off screen.
        step = self.active_step()
        step_id = step.id if step is not None else ""
        columns = _PICKER_COLUMNS.get(step_id, _DEFAULT_PICKER_COLUMNS)
        for label, width in columns:
            table.add_column(label, width=width)

        for candidate in candidates:
            style = self._style(_VERDICT_TOKENS.get(candidate.verdict, ""))
            chosen = self._is_chosen(candidate)
            if candidate.verdict == INELIGIBLE:
                prefix = ""
                name_style = f"bold {self._style(STYLE_ERROR)}"
            else:
                prefix = "[selected] " if chosen else ""
                name_style = (
                    "bold"
                    if chosen else ("bold" if candidate.recommended else "")
                )
            name = Text(
                f"{prefix}{candidate.name}",
                style=name_style,
            )
            if step_id == "subscription":
                row = (name, Text(candidate.resource_id, style="dim"))
            elif step_id == "scope":
                row = (name, candidate.location)
            elif step_id == "namespace":
                raw = candidate.raw or {}
                properties = raw.get("properties") or {}
                readiness = link_readiness(raw)
                row = (
                    name,
                    candidate.resource_group,
                    candidate.location,
                    Text(
                        str(properties.get("provisioningState", "")),
                        style=self._style(state_style(raw) or ""),
                    ),
                    Text(
                        readiness,
                        style=self._style(readiness_style(raw) or ""),
                    ),
                    str(endpoint_count(raw, "messaging")),
                    str(endpoint_count(raw, "provisioning")),
                    str(endpoint_count(raw, "updating")),
                    candidate.identity,
                    tag_summary(raw),
                )
            else:
                identity = candidate.identity[:14]
                if chosen and step_id in ("dps", "hub", "su"):
                    identity = (
                        get_choice(
                            self.context, step_id, candidate.resource_id
                        ).label
                        if has_choice(
                            self.context, step_id, candidate.resource_id
                        )
                        else Text(
                            "choose identity",
                            style=self._style(STYLE_WARN),
                        )
                    )
                row = (
                    name,
                    candidate.resource_group,
                    candidate.location,
                    identity,
                    Text(candidate.describe(), style=style),
                )
            table.add_row(*row, key=candidate.resource_id or candidate.name)
        if selected_key is not None:
            for index, candidate in enumerate(candidates):
                key = str(candidate.resource_id or candidate.name)
                if key == selected_key:
                    table.move_cursor(row=index)
                    break

    def _is_chosen(self, candidate) -> bool:
        """Already queued for linking, so the picker can mark it."""
        single = self.context.get("selected_dps")
        if single is not None and single.resource_id == candidate.resource_id:
            return True
        for key in ("selected_hubs", "selected_sus"):
            if any(chosen.resource_id == candidate.resource_id
                   for chosen in (self.context.get(key) or [])):
                return True
        return False

    def _selected_candidate(self):
        table = self.query_one("#candidates", DataTable)
        visible = self._visible_candidates()
        if table.row_count == 0 or not visible:
            return None
        index = table.cursor_coordinate.row
        return visible[index] if 0 <= index < len(visible) else None

    # -- actions -----------------------------------------------------------

    def _switch_subscription(self, candidate) -> None:
        """Point the whole session at another subscription.

        Clients are built per subscription, so cached providers, cached rows and the
        candidate catalog must all be discarded together.
        """
        subscription_id = candidate.resource_id or candidate.name
        self.context["subscription_id"] = subscription_id
        self.context["subscription_name"] = candidate.name
        for key in (
            "resource_group_name",
            "namespace_name",
            "location",
            "create_resource_group",
            "create_namespace",
            "create_dps",
            "create_hub",
            "create_su",
            "selected_dps",
            "selected_hubs",
            "selected_sus",
            "identity_choices",
        ):
            self.context.pop(key, None)
        self.context["namespace"] = {}
        if self.session is not None:
            self.session.cmd.cli_ctx.data["subscription_id"] = subscription_id
            self.session.scope.subscription_id = subscription_id
            self.session.scope.subscription_name = candidate.name
            self.session._providers.clear()
        if self.catalog is not None:
            self.catalog.clear()
        self._candidate_generation += 1
        store = getattr(self.app, "store", None)
        if store is not None:
            store.clear()
        # Grant rights are per subscription, so the previous answer no longer applies.
        self.context.pop("can_grant_roles", None)
        self._advance(f"subscription {candidate.name}")
        self._probe_grant_rights()

    def action_create_new(self) -> None:
        """Open the inline creation form for the active step."""
        step = self.active_step()
        if step is None or step.id not in _CREATABLE:
            self.flash("nothing to create at this step", "warning")
            return
        kind, label, _ = _CREATABLE[step.id]
        namespace = self.context.get("namespace") or {}
        pending = self._pending_creation(step.id)
        location = (
            getattr(pending, "location", None)
            or namespace.get("location")
            or self.context.get("location")
            or ""
        )
        base = self.context.get("namespace_name") or ""
        editing = pending is not None

        form = self.query_one("#create-form", Vertical)
        self.query_one("#create-kicker", Static).update(
            Text(
                f"{'EDIT PLANNED' if editing else 'NEW'} "
                f"{kind.replace('_', ' ').upper()}",
                style=self._style(STYLE_ACTIVE),
            )
        )
        self.query_one("#create-title", Label).update(
            Text(
                f"{'Edit' if editing else 'Create'} {label}",
                style=f"bold {self._style(STYLE_ACTIVE)}",
            )
        )
        resource_group = self.context.get("resource_group_name")
        scope_note = (
            f" in resource group '{resource_group}'"
            if resource_group and kind != "resource_group"
            else ""
        )
        self.query_one("#create-subtitle", Static).update(
            f"This is added to the plan{scope_note}; Azure is unchanged until "
            "Review and run."
        )
        self.query_one("#create-name", Input).value = (
            pending.name
            if pending is not None
            else (
                f"{base}-{kind}"
                if base and kind not in ("namespace", "resource_group")
                else ""
            )
        )
        self.query_one("#create-location", Input).value = location
        tags = getattr(pending, "tags", None) or {}
        self.query_one("#create-tags", Input).value = " ".join(
            f"{key}={value}" for key, value in tags.items()
        )
        self.query_one("#create-tags-row", Horizontal).display = kind == "namespace"
        self.query_one("#create-sku", Input).value = (
            getattr(pending, "sku", None) or DEFAULT_HUB_SKU
        )
        self.query_one("#create-sku-row", Horizontal).display = kind == "hub"
        self.query_one("#create-capacity", Input).value = str(
            getattr(pending, "capacity", None) or DEFAULT_CAPACITY
        )
        self.query_one("#create-capacity-row", Horizontal).display = kind in ("hub", "dps")
        self.query_one("#create-confirm", Button).label = (
            "Update setup" if editing else "Add to setup"
        )
        self.query_one("#create-error", Static).update("")
        self.query_one("#step-body", Static).display = False
        self.query_one("#candidate-status", Static).display = False
        self.query_one("#candidate-loading", LoadingIndicator).display = False
        self.query_one("#candidate-filter", Input).display = False
        self.query_one("#candidates", SetupCandidateTable).display = False
        form.display = True
        self.query_one("#create-name", Input).focus()

    def _close_form(self) -> None:
        self.query_one("#create-form", Vertical).display = False
        self.query_one("#candidate-filter", Input).display = False
        self.query_one("#step-body", Static).display = True
        self.query_one("#candidate-status", Static).display = True
        step = self.active_step()
        is_picker = step is not None and step.id in _PICKER_STEPS
        self.query_one("#candidate-loading", LoadingIndicator).display = (
            is_picker and self._candidates_loading
        )
        table = self.query_one("#candidates", SetupCandidateTable)
        table.display = is_picker and not self._candidates_loading
        if table.display:
            table.focus()
        else:
            self.query_one("#work-pane", SetupPane).focus()

    def _submit_form(self) -> None:
        step = self.active_step()
        if step is None or step.id not in _CREATABLE:
            self._close_form()
            return
        kind, _label, context_key = _CREATABLE[step.id]
        pending = self.context.get(context_key)

        name = self.query_one("#create-name", Input).value.strip()
        location = self.query_one("#create-location", Input).value.strip()
        resource_group = (
            name if kind == "resource_group"
            else str(self.context.get("resource_group_name") or "").strip()
        )
        tags, tags_problem = parse_tags(
            self.query_one("#create-tags", Input).value
            if kind == "namespace"
            else ""
        )
        sku = (
            self.query_one("#create-sku", Input).value.strip().upper()
            if kind == "hub"
            else (DEFAULT_DPS_SKU if kind == "dps" else None)
        )
        capacity = DEFAULT_CAPACITY
        capacity_problem = None
        if kind in ("hub", "dps"):
            try:
                capacity = int(self.query_one("#create-capacity", Input).value.strip())
                if capacity < 1:
                    raise ValueError
            except ValueError:
                capacity_problem = "units must be a whole number greater than zero"
        problem = validate_name(name, kind)
        if problem is None and not resource_group:
            problem = "a resource group is required"
        if problem is None and not location:
            problem = "a region is required"
        if problem is None:
            problem = tags_problem
        if problem is None and kind == "hub" and sku not in _HUB_SKUS:
            problem = "Hub SKU must be F1, B1, B2, B3, S1, S2, or S3"
        if problem is None:
            problem = capacity_problem
        if problem:
            self.query_one("#create-error", Static).update(
                Text(problem, style=f"bold {self._style(STYLE_ERROR)}")
            )
            return

        request = CreateRequest(
            kind=kind,
            name=name,
            resource_group_name=resource_group,
            location=location,
            sku=sku,
            capacity=capacity,
            tags=tags or None,
            identity=getattr(pending, "identity", system_choice()),
        )
        self._close_form()
        if kind == "resource_group":
            self._accept_create(step.id, context_key, request)
            return
        self._prompt_create_identity(step.id, context_key, request)

    def action_start_filter(self) -> None:
        field = self.query_one("#candidate-filter", Input)
        field.display = True
        field.value = self._candidate_filter
        field.focus()

    def _end_filter(self, keep: bool) -> None:
        field = self.query_one("#candidate-filter", Input)
        if not keep:
            self._candidate_filter = ""
            field.value = ""
        field.display = False
        self.query_one("#candidates", DataTable).focus()
        self._paint_candidates()
        self._render_candidate_status()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "candidate-filter":
            self._candidate_filter = event.value
            self._paint_candidates()
            self._render_candidate_status()

    def _accept_create(self, step_id: str, context_key: str,
                       request: Optional[CreateRequest]) -> None:
        """Record a creation request. Nothing is created until apply."""
        if request is None:
            return
        replacing = context_key in self.context
        self.context[context_key] = request
        if step_id == "scope":
            # A new resource group fixes both the group and the region for everything below.
            self.context["resource_group_name"] = request.name
            self.context["location"] = request.location
        if step_id == "namespace":
            # Everything downstream is scoped to the namespace being created.
            self.context["namespace_name"] = request.name
            self.context["resource_group_name"] = request.resource_group_name
            self.context["location"] = request.location
        diagnostics.log("queued creation: %s '%s' in %s/%s", request.kind, request.name,
                        request.resource_group_name, request.location)
        if self.is_mounted:
            if step_id == "hub":
                self.flash(
                    f"{request.label} '{request.name}' "
                    f"{'updated' if replacing else 'added'} in the plan; press n to edit",
                    "success",
                )
                self.refresh_view()
                self._reload_candidates()
            else:
                self._advance(
                    f"{request.label} '{request.name}' "
                    f"{'updated' if replacing else 'added'} in the plan; "
                    f"return to {step_id} and press n to edit"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-confirm":
            self._submit_form()
        elif event.button.id == "create-plan":
            self.action_show_plan()
        elif event.button.id == "create-cancel":
            self._close_form()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "candidate-filter":
            self._end_filter(keep=True)
            return
        self._submit_form()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "candidates":
            self.action_select()

    def action_select(self) -> None:
        candidate = self._selected_candidate()
        step = self.active_step()
        if candidate is None or step is None:
            return
        if not candidate.selectable:
            self.flash(f"{candidate.name} cannot be used: {candidate.reason}", "warning")
            return
        if step.id == "review":
            self.action_apply()
            return
        if step.id == "subscription":
            self._switch_subscription(candidate)
            return
        if step.id == "namespace":
            current = choice_from_namespace(candidate.raw or {})
            self._prompt_candidate_identity(step.id, candidate, current)
            return
        if step.id == "scope":
            old_group = self.context.get("resource_group_name")
            self.context["resource_group_name"] = candidate.name
            self.context["location"] = candidate.location or self.context.get("location", "")
            self.context.pop("create_resource_group", None)
            if old_group != candidate.name:
                for _kind, _label, context_key in _CREATABLE.values():
                    request = self.context.get(context_key)
                    if request is not None:
                        request.resource_group_name = candidate.name
            self._advance(f"resource group {candidate.name}")
            return
        if step.id == "dps":
            self._prompt_candidate_identity(
                step.id,
                candidate,
                get_choice(self.context, "dps", candidate.resource_id),
            )
            return
        if step.id in _MULTI_SELECT:
            added = self._toggle_choice(step.id, candidate)
            if added:
                self._prompt_candidate_identity(
                    step.id,
                    candidate,
                    system_choice(),
                )
        self.refresh_view()
        self._paint_candidates()

    def action_toggle_multi(self) -> None:
        """Compatibility shortcut: Space only toggles collections that allow many."""
        step = self.active_step()
        if step is not None and step.id in _MULTI_SELECT:
            self.action_select()

    def action_show_json(self) -> None:
        """Open the highlighted candidate's complete Azure payload."""
        candidate = self._selected_candidate()
        step = self.active_step()
        if candidate is None or step is None or step.id not in _PICKER_STEPS:
            self.flash("move to a resource row before opening JSON", "warning")
            return
        payload = (
            dict(candidate.raw)
            if candidate.raw is not None
            else {
                "name": candidate.name,
                "id": candidate.resource_id,
                "resourceGroup": candidate.resource_group,
                "location": candidate.location,
            }
        )
        self.app.push_screen(
            DetailScreen(
                None,
                payload,
                title=_PICKER_TITLES.get(step.id, "Resource"),
                name=candidate.name,
            )
        )

    def _toggle_choice(self, step_id: str, candidate) -> bool:
        """Add or remove one resource on a step that accepts several.

        Toggling rather than appending: pressing select twice on the same row used to
        queue it twice, which then failed at link time with a duplicate endpoint.
        """
        noun = _MULTI_SELECT[step_id]
        key = _SELECTABLE[step_id]
        chosen = list(self.context.get(key) or [])
        if any(item.resource_id == candidate.resource_id for item in chosen):
            chosen = [item for item in chosen if item.resource_id != candidate.resource_id]
            remove_choice(self.context, step_id, candidate.resource_id)
            self.flash(f"removed {noun} {candidate.name} ({len(chosen)} selected)", "info")
            added = False
        else:
            chosen.append(candidate)
            self.flash(
                f"{noun} {candidate.name} selected ({len(chosen)} total) - "
                "choose its identity, then select more or press d",
                "success",
            )
            added = True
        self.context[key] = chosen
        self.context.pop({"hub": "create_hub", "su": "create_su"}[step_id], None)
        return added

    def action_configure_identity(self) -> None:
        """Choose SAMI or UAMI for the highlighted or planned resource."""
        step = self.active_step()
        if step is None or step.id not in ("namespace", "dps", "hub", "su"):
            self.flash("identity is configured on namespace and link resources", "info")
            return
        request = self._pending_creation(step.id)
        if request is not None:
            self._prompt_create_identity(
                step.id,
                _CREATABLE[step.id][2],
                request,
                editing=True,
            )
            return
        candidate = self._selected_candidate()
        if candidate is None:
            self.flash("highlight a resource first", "warning")
            return
        current = (
            choice_from_namespace(candidate.raw or {})
            if step.id == "namespace"
            else get_choice(self.context, step.id, candidate.resource_id)
        )
        self._prompt_candidate_identity(step.id, candidate, current)

    def _identity_purpose(self, kind: str) -> str:
        if kind == "namespace":
            return "Identity the namespace uses to call linked resources"
        labels = {"dps": "DPS", "hub": "Hub", "su": "Update Instance"}
        return f"Identity this {labels[kind]} uses to call the namespace"

    def _identity_dialog(
        self,
        kind: str,
        label: str,
        current,
        callback,
        resource=None,
    ) -> None:
        pane = self.query_one("#work-pane", SetupPane)
        self.app.push_screen(
            IdentityChoiceDialog(
                catalog=self.catalog,
                resource_label=label,
                purpose=self._identity_purpose(kind),
                subscription_id=self.context.get("subscription_id") or "",
                resource_group_name=self.context.get("resource_group_name") or "",
                location=self._namespace_location()
                or self.context.get("location")
                or "",
                current=current,
                resource=resource,
                pane_left=pane.region.x,
                pane_top=pane.region.y,
                pane_height=pane.region.height,
                pane_width=pane.region.width,
            ),
            callback,
        )

    def _prompt_candidate_identity(self, kind: str, candidate, current) -> None:
        self._identity_dialog(
            kind,
            candidate.name,
            current,
            lambda choice: self._accept_candidate_identity(kind, candidate, choice),
            resource=candidate.raw or {},
        )

    def _accept_candidate_identity(self, kind: str, candidate, choice) -> None:
        if choice is None:
            return
        set_choice(self.context, kind, choice, candidate.resource_id)
        if kind == "namespace":
            self.context["namespace_name"] = candidate.name
            self.context["resource_group_name"] = (
                candidate.resource_group or self.context.get("resource_group_name")
            )
            self.context.pop("create_namespace", None)
            self.context["namespace"] = candidate.raw or {}
            self._state_loaded = True
            self._advance(f"namespace {candidate.name} · {choice.label}")
            return
        if kind == "dps":
            self.context["selected_dps"] = candidate
            self.context.pop("create_dps", None)
            self._advance(f"DPS {candidate.name} · {choice.label}")
            return
        key = _SELECTABLE[kind]
        selected = list(self.context.get(key) or [])
        if not any(item.resource_id == candidate.resource_id for item in selected):
            selected.append(candidate)
            self.context[key] = selected
        self.context.pop({"hub": "create_hub", "su": "create_su"}[kind], None)
        self.flash(f"{candidate.name} will use {choice.label}", "success")
        self.refresh_view()
        self._paint_candidates()

    def _prompt_create_identity(
        self,
        step_id: str,
        context_key: str,
        request: CreateRequest,
        editing: bool = False,
    ) -> None:
        self._identity_dialog(
            step_id,
            request.name,
            request.identity,
            lambda choice: self._accept_create_identity(
                step_id, context_key, request, choice, editing
            ),
            resource={},
        )

    def _accept_create_identity(
        self,
        step_id: str,
        context_key: str,
        request: CreateRequest,
        choice,
        editing: bool,
    ) -> None:
        if choice is None:
            return
        request.identity = choice
        self._accept_create(step_id, context_key, request)
        if editing:
            self.flash(f"{request.label} will use {choice.label}", "success")

    def action_done_step(self) -> None:
        """Finish a multi-select step and move on.

        Selecting does not advance on these steps, because linking a second hub is the
        normal case; this is the explicit "that is all of them" signal.
        """
        step = self.active_step()
        if step is None:
            return
        if step.id not in _MULTI_SELECT:
            self._advance()
            return
        chosen = self.context.get(_SELECTABLE[step.id]) or []
        pending = self.context.get({"hub": "create_hub", "su": "create_su"}[step.id])
        if not chosen and pending is None:
            if step.optional:
                self._advance(f"skipped {step.title.lower()}")
            else:
                self.flash(
                    f"select at least one {_MULTI_SELECT[step.id]} first, or press n to "
                    "create one",
                    "warning",
                )
            return
        missing_identity = next(
            (
                resource
                for resource in chosen
                if not has_choice(
                    self.context,
                    step.id,
                    resource.resource_id,
                )
            ),
            None,
        )
        if missing_identity is not None:
            self.flash(
                f"choose an identity for {missing_identity.name}; highlight it and press i",
                "warning",
            )
            return
        count = len(chosen) + (1 if pending is not None else 0)
        self._advance(f"{count} {_MULTI_SELECT[step.id]}(s) will be linked")

    def action_show_plan(self) -> None:
        self.app.push_screen(PlanDialog(self.flow))

    def action_apply(self) -> None:
        """Run the plan, including the role grants when this account may create them."""
        if getattr(self.app, "read_only", False):
            self.flash("read-only session: apply is disabled", "warning")
            return
        missing_identity = self._missing_identity_choice()
        if missing_identity is not None:
            self.flash(
                f"choose the managed identity for {missing_identity} before running",
                "warning",
            )
            return
        if self.context.get("permission_checking"):
            self.flash("permission preflight is still running", "warning")
            return
        if self.context.get("can_write_resources") is False:
            self.flash(
                "setup needs resource-write access at every involved resource group",
                "warning",
            )
            return
        plan = self.flow.build_plan()
        runnable = [item for item in plan if item.invoke is not None]
        manual = [item for item in plan if item.action == "manual"]
        blocked = [item for item in plan if item.action == "blocked"]
        adu_consent = next(
            (
                item
                for item in blocked
                if item.key.startswith("grant-adu-fpa-")
                and self.context.get("adu_fpa_confirmed") is not True
            ),
            None,
        )
        if adu_consent is not None:
            self.app.push_screen(
                CommandPreviewDialog(
                    "Approve Software Updates service access",
                    adu_consent.command,
                    note=(
                        "Software Updates linking currently requires Contributor for "
                        "the Azure Device Update first-party service on this Update "
                        "Instance. This grant is shown separately for explicit approval."
                    ),
                ),
                self._adu_consent_result,
            )
            return
        if blocked:
            self.flash(
                f"setup is blocked: {blocked[0].blocked_reason or blocked[0].description}",
                "warning",
            )
            return
        if manual:
            self.flash(
                "role grants need administrator access; press x to copy a runnable "
                "script for an administrator, or activate Owner/User Access "
                "Administrator and press r",
                "warning",
            )
            return
        if not runnable:
            self.flash("nothing to apply - this namespace is already configured", "info")
            return

        grants = sum(1 for item in runnable if item.key.startswith("grant-"))
        note = f"{len(runnable)} operation(s) will run in order."
        if grants:
            note += (
                f" {grants} of them are role assignments radr will create for you, "
                "because your account is allowed to."
            )
        preview = "\n".join(item.command for item in runnable)
        self.app.push_screen(
            CommandPreviewDialog("Run setup", preview, note=note),
            lambda approved: self._start_apply(runnable) if approved else None,
        )

    def _start_apply(self, items) -> None:
        self.app.push_screen(
            ExecutionScreen(
                session=self.session,
                context=self.context,
                items=items,
                on_complete=self._execution_finished,
            )
        )

    def _adu_consent_result(self, approved: bool) -> None:
        if not approved:
            return
        self.context["adu_fpa_confirmed"] = True
        self.refresh_view()
        self.action_apply()

    def _execution_finished(self, _succeeded: bool) -> None:
        self.action_reload()
        if hasattr(self.app, "_refresh_tray"):
            self.app._refresh_tray()

    def action_export(self) -> None:
        script = self.flow.script()
        try:
            self.app.copy_to_clipboard(script)
            self.flash("runnable setup script copied to clipboard", "success")
        except Exception:  # noqa: BLE001 - clipboard is unavailable over plain SSH
            self.flash("clipboard unavailable; press p to read the plan", "warning")

    def action_reload(self) -> None:
        """Re-derive every step from live state, which is what makes the flow resumable."""
        self._state_loaded = False
        self._candidates_for = None
        self._candidate_generation += 1
        if self.catalog is not None:
            self.catalog.clear()
        self.refresh_view()
        self.run_worker(self._reload_namespace, thread=True, name="onboard-reload")
        # Grant rights are live state too: activating Owner in PIM should be picked up
        # here, which is exactly what the review panel tells the customer to do.
        self.context.pop("_grant_probe_for", None)
        self._probe_grant_rights()

    def _reload_namespace(self) -> None:
        try:
            namespace = self.session.call(
                self.session.provider("namespace").show,
                namespace_name=self.context.get("namespace_name"),
                resource_group_name=self.context.get("resource_group_name"),
            )
        except Exception:  # noqa: BLE001 - a missing namespace simply leaves the step unmet
            namespace = {}
        self.app.call_from_thread(self._apply_namespace, namespace)

    def _apply_namespace(self, namespace) -> None:
        self.context["namespace"] = namespace or {}
        if (
            namespace
            and "namespace"
            not in (self.context.get("identity_choices") or {})
        ):
            set_choice(
                self.context,
                "namespace",
                choice_from_namespace(namespace),
            )
        self._state_loaded = True
        self.refresh_view()
        # Which candidates matter depends on the current step, which is only known now.
        self._reload_candidates()

    def action_back(self) -> None:
        """Escape precedence: close the form first, then leave."""
        field = self.query_one("#candidate-filter", Input)
        if field.display:
            self._end_filter(keep=False)
            return
        form = self.query_one("#create-form", Vertical)
        if form.display:
            self._close_form()
            return
        self.app.pop_screen_safely()

    def breadcrumb(self) -> str:
        return "guided setup"

    def guide(self) -> Guide:
        """Orientation for the one page that changes infrastructure.

        The note is written from live state rather than fixed, because the single most
        common question here - "will this create the role assignments or not?" - has a
        different answer depending on who is signed in.
        """
        verdict = self.context.get("can_grant_roles")
        if verdict is True:
            grants = "Role grants included."
        elif verdict is False:
            grants = "Role grants need Owner/User Access Administrator; x copies an admin script."
        else:
            grants = "Checking role access."
        return Guide(
            about=(
                "Build or repair namespace connectivity. Nothing changes until Run setup."
            ),
            action=(
                "\u2190/\u2192 switch pane  \u00b7  \u2191/\u2193 choose  \u00b7  "
                "Enter choose  \u00b7  n create  \u00b7  d next"
            ),
            runs=(
                "Runs only after confirmation; p shows exact commands."
            ),
            note=(
                f"DPS before hubs. {grants}"
            ),
        )


class PlanDialog(ChromeScreen):
    """The plan: what exists, what will be created, what is blocked, and the commands."""

    BINDINGS = [Binding("escape", "back", "Back", show=True)]

    _ACTION_TOKENS = {
        "exists": STYLE_MUTED,
        "create": STYLE_ACTIVE,
        "modify": STYLE_ACTIVE,
        "manual": STYLE_WARN,
        "blocked": STYLE_ERROR,
    }

    def __init__(self, flow, **kwargs):
        super().__init__(**kwargs)
        self.flow = flow

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="pane", id="plan-pane"):
            yield Static(id="plan-body")

    def on_mount(self) -> None:
        self.query_one("#plan-pane", VerticalScroll).border_title = "plan"
        self.repaint_theme()

    def repaint_theme(self) -> None:
        """Rebuild Rich styles after the app changes palette."""
        text = Text()
        text.append("nothing has been applied yet\n\n", style="bold")
        theme = getattr(self.app, "theme_tokens", None)
        text.append("IDENTITIES\n", style=f"bold {style_for(STYLE_ACTIVE, theme)}")
        text.append(f"{'DIRECTION':<25}{'RESOURCE':<24}IDENTITY\n", style="dim")
        for direction, resource, choice in assignment_rows(self.flow.context):
            text.append(f"{direction:<25}{resource:<24}{choice.label}\n")
        text.append("\nPERMISSIONS\n", style=f"bold {style_for(STYLE_ACTIVE, theme)}")
        matrix = self.flow.context.get("permission_matrix") or {}
        if self.flow.context.get("permission_checking"):
            text.append("Checking every involved resource group...\n", style="dim")
        elif matrix:
            for scope, result in matrix.items():
                group = scope.rsplit("/", 1)[-1]
                ready = result is not None and all(result.values())
                text.append(
                    f"{'READY' if ready else 'BLOCKED':<9}{group}\n",
                    style=style_for(STYLE_ACTIVE if ready else STYLE_ERROR, theme),
                )
        else:
            text.append("Permission preflight has not completed.\n", style="dim")
        text.append("\nOPERATIONS\n", style=f"bold {style_for(STYLE_ACTIVE, theme)}")
        for item in self.flow.build_plan():
            style = style_for(self._ACTION_TOKENS.get(item.action, ""), theme)
            text.append(f"{item.action.upper():<8}", style=style)
            text.append(f"{item.description}\n")
            if item.blocked_reason:
                text.append(
                    f"         {item.blocked_reason}\n",
                    style=style_for(STYLE_WARN, theme),
                )
            if item.command:
                text.append(
                    f"         {item.command}\n",
                    style=style_for(STYLE_ACTIVE, theme),
                )
        text.append("\npress x on the previous screen to copy the runnable script", style="dim")
        self.query_one("#plan-body", Static).update(text)
        if hasattr(self.app, "sync_chrome"):
            self.app.sync_chrome(self)

    def action_back(self) -> None:
        self.app.pop_screen_safely()

    def breadcrumb(self) -> str:
        return "plan"

    def guide(self) -> Guide:
        return Guide(
            about=(
                "Every operation guided setup will perform, in the order it will run them, "
                "with the equivalent az command for each."
            ),
            action="Escape returns to setup  ·  x copies the complete plan as a shell script.",
            note=(
                "Grants must land before the links that depend on them, which is why a "
                "propagation wait sits between the two. Press x to copy the runnable script."
            ),
        )
