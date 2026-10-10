# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Minimal setup: one focal area, reversible input and explicit write approval."""

from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import shlex
from threading import Event
from time import monotonic

from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, Checkbox, Collapsible, Footer, Input, Label, Select, SelectionList, Static, TextArea,
)

from azext_iot.adr.workflows.input import build_setup_request
from azext_iot.adr.workflows.namespace import NamespaceWorkflow
from azext_iot.adr.workflows.tui_model import (
    endpoint_id, form_config, plan_fingerprint, plan_text,
)


class SetupStopped(Exception):
    """Stop before another operation; an already-submitted request may continue."""


@contextmanager
def quiet_providers():
    from azext_iot.adr.providers.base import console

    previous = console.quiet
    console.quiet = True
    try:
        yield
    finally:
        console.quiet = previous


class SetupProgress:
    def __init__(self, app):
        self.app = app

    def run(self, label, operation, *args, workflow_scope=None, mutation=False,
            handled_error=None, **kwargs):
        del workflow_scope, mutation
        if self.app.stop_requested.is_set():
            raise SetupStopped("Stopped watching. Re-read Azure state before resuming.")
        self.app.call_from_thread(self.app.operation_status, label)
        try:
            result = operation(*args, **kwargs)
        except Exception as error:
            if not (handled_error and handled_error(error)):
                self.app.call_from_thread(self.app.operation_status, f"Failed: {label}")
            raise
        self.app.call_from_thread(self.app.operation_status, f"Done: {label}")
        return result


class SetupApp(App):
    TITLE = "ADR namespace setup"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("escape", "previous", "Back"),
        Binding("ctrl+enter", "next", "Continue"),
        Binding("ctrl+s", "save", "Save config"),
        Binding("ctrl+r", "retry", "Re-read / retry"),
        Binding("ctrl+x", "stop", "Stop watching"),
        Binding("ctrl+q", "close_setup", "Quit"),
    ]
    CSS = """
    Screen { background: #0e1014; color: #d7dae0; }
    #workspace { width: 100%; max-width: 88; height: 1fr; align-horizontal: center; margin: 0 1; }
    #heading { height: 2; padding-top: 1; color: #8b929c; }
    #steps { height: 3; }
    #steps Button { width: auto; min-width: 10; border: none; background: transparent; }
    #steps Button.current { color: #7cc4fa; text-style: bold underline; }
    #content { height: 1fr; }
    .page { height: auto; padding: 0 1; }
    #namespace-fields { height: auto; }
    .scope-field { width: 1fr; height: auto; margin-right: 1; }
    .title { text-style: bold; margin-top: 1; }
    .note { color: #8b929c; height: auto; margin-bottom: 1; }
    Label { height: auto; margin-top: 1; }
    Input, Select { width: 100%; height: 3; border: none; border-bottom: solid #262b33; background: transparent; }
    Input:focus, Select:focus { border-bottom: solid #7cc4fa; }
    Collapsible { padding: 0; border: none; background: transparent; }
    Collapsible > Contents { padding: 0 1; }
    Checkbox { border: none; background: transparent; height: auto; padding: 0; margin: 1 0; }
    Checkbox:focus { background: #161b22; }
    SelectionList { height: auto; max-height: 10; min-height: 3; border: none; background: transparent; }
    SelectionList > .option-list--option-highlighted { background: #161b22; color: #7cc4fa; }
    Button { min-width: 9; width: auto; height: 3; background: transparent; border: none; }
    Button:hover { background: #161b22; }
    Button:focus { text-style: bold underline; color: #7cc4fa; }
    Button.primary { background: #7cc4fa; color: #0e1014; text-style: bold; }
    Button:disabled { color: #8b929c; background: #262b33; }
    #actions { height: 3; margin: 1 0; }
    #notice { height: auto; max-height: 5; color: #e3b341; padding: 0 1; }
    #plan, #run-log { height: auto; }
    #json-editor { height: 14; border: solid #262b33; }
    #hub-ids { height: 6; border: solid #262b33; }
    #details { height: auto; }
    #details Button { min-width: 15; }
    Footer { background: #0e1014; color: #8b929c; }
    FooterKey { background: #0e1014; }
    FooterKey .footer-key--key { background: #0e1014; color: #7cc4fa; }
    FooterKey .footer-key--description { background: #0e1014; color: #8b929c; }
    """

    def __init__(self, services, subscription_id, config=None, *, review=False, output_script=None):
        super().__init__()
        self.services = services
        self.subscription_id = subscription_id
        self.config = deepcopy(config or {})
        self.start_at_review = review
        self.output_script = output_script
        self.step = 0
        self.busy = False
        self.plan = None
        self.request = None
        self.result = None
        self.stop_requested = Event()
        self.show_commands = False
        self.show_roles = False
        self.started = 0.0
        self.operation = ""
        self.operation_log = []
        self.timer = None

    def compose(self) -> ComposeResult:
        ns = self.config.get("namespace", {})
        links = self.config.get("links", {})
        cms = self.config.get("cms", {})
        outbound = ns.get("outboundIdentity", {})
        identity = outbound.get("userAssignedResourceId") or (
            "system-assigned" if outbound.get("type") in {"SystemAssigned", "system-assigned"} else ""
        )
        existing = any(links.get(key) for key in ("dps", "hubs"))
        with Vertical(id="workspace"):
            yield Static(f"az iot adr ns setup  /  {self.subscription_id}", id="heading", markup=False)
            with Horizontal(id="steps"):
                for index, name in enumerate(("Namespace", "Connectivity", "Capabilities", "Review")):
                    yield Button(name, id=f"step-{index}")
            with VerticalScroll(id="content"):
                with Vertical(id="page-0", classes="page"):
                    yield Label("Name your namespace", classes="title")
                    yield Static("Create or reuse a namespace. Nothing is written before approval.", classes="note")
                    with Horizontal(id="namespace-fields"):
                        with Vertical(classes="scope-field"):
                            yield Label("Resource group")
                            yield Input(ns.get("resourceGroup", ""), id="group")
                        with Vertical(classes="scope-field"):
                            yield Label("Name")
                            yield Input(ns.get("name", ""), placeholder="ns-my-plant", id="name")
                    with Collapsible(title="Browse existing namespaces", id="browse-options"):
                        yield Button("Load namespaces", id="browse")
                        yield Select([], prompt="Choose a namespace", id="namespace-choice")
                    with Collapsible(title="More options: region, tags, outbound identity", id="namespace-options"):
                        yield Label("Region (blank uses resource-group location for new resources)")
                        yield Input(ns.get("location", ""), id="location")
                        yield Label("Tags (name=value)")
                        yield Input(" ".join(shlex.quote(f"{k}={v}") for k, v in ns.get("tags", {}).items()), id="tags")
                        yield Label("Outbound identity: system-assigned, ARM identity ID, or blank to reuse")
                        yield Input(identity or ("system-assigned" if not self.config else ""), id="outbound")
                with Vertical(id="page-1", classes="page"):
                    yield Label("How will devices connect?", classes="title")
                    yield Static("DPS first, then IoT Hubs. Use existing resources or explicitly create new ones.",
                                 classes="note")
                    yield Select(
                        [("Use existing DPS and IoT Hubs", "existing"),
                         ("Create a new DPS and IoT Hubs", "new"), ("Skip for now", "skip")],
                        value="existing" if existing else "skip", allow_blank=False, id="mode",
                    )
                    with Vertical(id="existing-targets"):
                        yield Button("Find targets", id="targets")
                        yield Select([], prompt="Choose DPS", id="dps-choice")
                        yield SelectionList(id="hub-choices")
                        with Collapsible(title="Resource IDs / advanced", collapsed=not existing):
                            yield Label("DPS ARM resource ID (optional if already linked)")
                            yield Input(
                                endpoint_id(links["dps"], "dps", ns, self.subscription_id) if links.get("dps") else "",
                                id="dps-id",
                            )
                            yield Label("IoT Hub ARM IDs, one per line")
                            yield TextArea("\n".join(
                                endpoint_id(item, "hub", ns, self.subscription_id) for item in links.get("hubs", [])
                            ), id="hub-ids")
                    with Vertical(id="new-targets"):
                        yield Select([("Small: 1 hub", "1"), ("Production: 2 hubs", "2"), ("Large: 4 hubs", "4")],
                                     value="1", allow_blank=False, id="count")
                        yield Static("Defaults: S1, 1 unit. Review all names and writes before creating.",
                                     classes="note")
                        with Collapsible(title="More options: names and Hub SKU"):
                            yield Input(placeholder="<namespace>-provisioning", id="dps-name")
                            yield Input(placeholder="<namespace>-hub", id="hub-prefix")
                            yield Select([(value, value) for value in ("S1", "S2", "S3")],
                                         value="S1", allow_blank=False, id="sku")
                    with Collapsible(title="Link identity"):
                        yield Input("system-assigned", placeholder="system-assigned or ARM identity ID",
                                    id="link-identity")
                with Vertical(id="page-2", classes="page"):
                    yield Label("Optional capabilities", classes="title")
                    yield Static("You can add these later.", classes="note")
                    yield Checkbox("Software updates", value=bool(links.get("softwareUpdates")), id="software-updates")
                    yield Checkbox("Certificate management (Azure-managed)", value=bool(cms.get("enabled")), id="cms")
                    with Vertical(id="cms-options"):
                        yield Static(
                            "Azure-managed root -> intermediate -> policy. No service-role grants.\n"
                            "External PKI is configured with individual CA commands or the portal.",
                            classes="note",
                        )
                        with Collapsible(title="More options: certificate names and validity"):
                            yield Input(cms.get("rootName", ""), placeholder="<namespace>-root", id="root")
                            yield Input(cms.get("intermediateName", ""), placeholder="<namespace>-ica", id="intermediate")
                            yield Input(cms.get("policyName", ""), placeholder="<namespace>-devices", id="policy")
                            yield Label("Device certificate validity (1-90 days)")
                            yield Input(str(cms.get("validityDays", 30)), type="integer", id="validity")
                with Vertical(id="page-3", classes="page"):
                    yield Label("Review changes", classes="title")
                    yield Static("", id="plan", markup=False)
                    with Horizontal(id="details"):
                        yield Button("Role details", id="roles")
                        yield Button("Commands", id="commands")
                        yield Button("Re-check", id="recheck")
                    with Collapsible(title="Edit full JSON configuration", id="json-options"):
                        yield TextArea("", id="json-editor")
                        yield Button("Validate and review", id="use-json")
                    with Collapsible(title="Save configuration to a new file"):
                        yield Input(placeholder="namespace-setup.json", id="save-path")
                        yield Button("Save config", id="save-config")
                    yield Label("Type the namespace name to approve the displayed writes", id="confirm-label")
                    yield Input(id="confirm")
                with Vertical(id="page-4", classes="page"):
                    yield Label("Setup progress", classes="title")
                    yield Static("", id="progress", markup=False)
                    yield Static("", id="run-log", markup=False)
            yield Static("", id="notice", markup=False)
            with Horizontal(id="actions"):
                yield Button("Back", id="back")
                yield Button("Continue", id="next", classes="primary")
                yield Button("Stop watching", id="stop")
                yield Button("Retry / re-read", id="retry")
                yield Button("Close", id="close")
        yield Footer()

    def on_mount(self):
        self.set_step(0)
        self.refresh_disclosure()
        if self.start_at_review:
            self.prepare(self.config)
        else:
            self.query_one("#name", Input).focus()

    def set_step(self, step):
        self.step = step
        for index in range(5):
            self.query_one(f"#page-{index}").display = step == index
        for index in range(4):
            button = self.query_one(f"#step-{index}", Button)
            button.set_class(step == index, "current")
            button.disabled = self.busy or step == 4 or index > step
        self.query_one("#back").display = 0 < step < 4
        self.query_one("#next").display = step < 4
        self.query_one("#next", Button).label = "Create / apply" if step == 3 else "Review" if step == 2 else "Continue"
        self.query_one("#stop").display = step == 4 and self.busy
        self.query_one("#retry").display = step == 4 and not self.busy and bool(self.result) and (
            self.result.get("state") in {"Failed", "Blocked", "Stopped"}
        )
        self.query_one("#close").display = not self.busy
        self.query_one("#content", VerticalScroll).scroll_home(animate=False)
        self.update_confirmation()

    def refresh_disclosure(self):
        mode = self.query_one("#mode", Select).value
        self.query_one("#existing-targets").display = mode == "existing"
        self.query_one("#new-targets").display = mode == "new"
        self.query_one("#cms-options").display = self.query_one("#cms", Checkbox).value

    def values(self):
        values = {
            name.replace("-", "_"): self.query_one(f"#{name}", Input).value
            for name in (
                "name", "group", "location", "tags", "outbound", "link-identity", "dps-id",
                "dps-name", "hub-prefix", "validity", "root", "intermediate", "policy",
            )
        }
        values.update({
            key: self.query_one(f"#{key}", Select).value for key in ("mode", "count", "sku")
        })
        values["hub_ids"] = self.query_one("#hub-ids", TextArea).text.splitlines()
        for key in ("cms", "software-updates"):
            values[key.replace("-", "_")] = self.query_one(f"#{key}", Checkbox).value
        return values

    def notice(self, message):
        self.query_one("#notice", Static).update(Text(str(message)))

    def update_confirmation(self):
        approved = bool(self.plan and self.request) and self.query_one("#confirm", Input).value == (
            self.request.namespace_name
        )
        self.query_one("#next", Button).disabled = self.busy or (
            self.step == 3 and (not approved or self.plan["state"] == "Blocked")
        )

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.query("Input, Select, Checkbox, SelectionList, TextArea, #content Button").results():
            widget.disabled = busy
        self.set_step(self.step)

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "confirm":
            self.update_confirmation()

    def on_text_area_changed(self, event: TextArea.Changed):
        if event.text_area.id == "json-editor" and event.text_area.text != json.dumps(self.config, indent=2):
            self.plan = None
            self.query_one("#confirm", Input).value = ""
            self.update_confirmation()
            self.notice("Configuration edited. Validate and review it before applying.")

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "mode":
            self.refresh_disclosure()
        elif event.value is not Select.BLANK:
            target = {"namespace-choice": "name", "dps-choice": "dps-id"}.get(event.select.id)
            if target:
                self.query_one(f"#{target}", Input).value = str(event.value)

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged):
        self.query_one("#hub-ids", TextArea).load_text("\n".join(event.selection_list.selected))

    def on_checkbox_changed(self, _event: Checkbox.Changed):
        self.refresh_disclosure()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "save-path":
            self.action_save()
        else:
            self.action_next()

    def on_button_pressed(self, event: Button.Pressed):
        name = event.button.id or ""
        if name.startswith("step-") and not self.busy:
            self.set_step(int(name[-1]))
        elif name in {"browse", "targets"}:
            self.browse(name == "targets")
        elif name in {"roles", "commands"}:
            setattr(self, f"show_{name}", not getattr(self, f"show_{name}"))
            self.render_plan()
        elif name == "recheck":
            self.prepare(self.config)
        elif name == "use-json":
            self.use_json()
        else:
            action = {
                "next": self.action_next, "back": self.action_previous, "close": self.action_close_setup,
                "stop": self.action_stop, "retry": self.action_retry, "save-config": self.action_save,
            }.get(name)
            if action:
                action()

    def action_previous(self):
        if not self.busy and 0 < self.step < 4:
            self.set_step(self.step - 1)

    def action_next(self):
        if self.busy:
            return
        if self.step == 3:
            if not self.query_one("#next", Button).disabled:
                self.set_busy(True)
                self.apply_plan()
            return
        try:
            values = self.values()
            if not values["name"].strip() or not values["group"].strip():
                raise InvalidArgumentValueError("Namespace name and resource group are required.")
            config = form_config(self.config, values, self.subscription_id)
            if self.step == 2:
                self.prepare(config)
            else:
                self.set_step(self.step + 1)
                self.notice("")
        except (ValueError, InvalidArgumentValueError) as error:
            self.notice(error)

    def action_retry(self):
        if not self.busy:
            self.prepare(self.config)

    def action_stop(self):
        if self.busy:
            self.stop_requested.set()
            self.notice("Stopping before the next operation. A request already submitted may continue in Azure.")

    def action_close_setup(self):
        if self.busy:
            self.action_stop()
            return
        self.exit(self.result)

    def action_save(self):
        try:
            path = self.query_one("#save-path", Input).value.strip()
            if not path:
                raise InvalidArgumentValueError("Enter a new file path; existing files are never overwritten.")
            value = self.config if self.step >= 3 else form_config(self.config, self.values(), self.subscription_id)
            with Path(path).expanduser().open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(value, indent=2) + "\n")
            self.notice(f"Configuration saved to {path}.")
        except (OSError, ValueError, InvalidArgumentValueError) as error:
            self.notice(error)

    def use_json(self):
        from azext_iot.adr.workflows.configuration import load_config

        try:
            config = load_config(self.query_one("#json-editor", TextArea).text)
        except InvalidArgumentValueError as error:
            self.notice(error)
            return
        self.prepare(config)

    def prepare(self, config):
        if self.busy:
            return
        self.stop_requested.clear()
        self.set_busy(True)
        self.query_one("#confirm", Input).value = ""
        self.update_confirmation()
        self.notice("Reading Azure state. No writes.")
        self.prepare_worker(deepcopy(config))

    def read_plan(self, config):
        request = build_setup_request(
            None, None, self.subscription_id, config=config, no_input=True, interactive=False,
        )
        if not self.services.show_subscription(self.subscription_id):
            raise InvalidArgumentValueError("The selected subscription is not accessible.")
        group = self.services.show_resource_group(request.resource_group_name)
        if not group:
            raise InvalidArgumentValueError("Resource group not found. Create it before setup.")
        plan, _ = NamespaceWorkflow(self.services).plan_setup(request)
        return request, plan

    @work(thread=True)
    def prepare_worker(self, config):
        try:
            request, plan = self.read_plan(config)
        except Exception as error:  # SDK/CLI boundary: report failures in the UI, never continue to apply.
            self.call_from_thread(self.finish_error, error, False)
        else:
            self.call_from_thread(self.accept_plan, config, request, plan)

    def accept_plan(self, config, request, plan):
        if self.stop_requested.is_set():
            self.finish_error(SetupStopped("Stopped reading. Re-read Azure state before continuing."), False)
            return
        changed = self.plan is not None and plan_fingerprint(self.plan) != plan_fingerprint(plan)
        self.config, self.request, self.plan = config, request, plan
        self.set_busy(False)
        self.load_form()
        self.query_one("#confirm", Input).value = ""
        self.query_one("#json-editor", TextArea).load_text(json.dumps(config, indent=2))
        self.render_plan()
        self.set_step(3)
        self.notice("Plan changed. Review and confirm again." if changed else "No writes yet. Review all changes.")
        self.query_one("#confirm", Input).focus()
        if self.output_script:
            from azext_iot.adr.workflows.input import write_script_file

            missing = [item for item in plan["items"] if item.get("action") != "role"
                       and item["state"] in {"Planned", "Manual"} and not item.get("command")]
            if missing:
                self.notice("Some commands depend on prerequisites. Apply them before exporting a script.")
            else:
                try:
                    write_script_file(self.output_script, [
                        item["command"] for item in plan["items"]
                        if item["state"] in {"Planned", "Manual"} and item.get("command")
                    ])
                except OSError as error:
                    self.notice(error)

    def render_plan(self):
        if self.plan:
            self.query_one("#plan", Static).update(
                plan_text(self.plan, commands=self.show_commands, roles=self.show_roles)
            )

    def load_form(self):
        """Keep Back/Edit faithful to the reviewed JSON, including unexposed fields."""
        ns = self.config.get("namespace", {})
        links = self.config.get("links", {})
        cms = self.config.get("cms", {})
        outbound = ns.get("outboundIdentity", {})
        fields = {
            "name": ns.get("name", ""), "group": ns.get("resourceGroup", ""),
            "location": ns.get("location", ""),
            "tags": " ".join(shlex.quote(f"{key}={value}") for key, value in ns.get("tags", {}).items()),
            "outbound": outbound.get("userAssignedResourceId") or (
                "system-assigned" if outbound.get("type") in {"SystemAssigned", "system-assigned"} else ""
            ),
            "dps-id": endpoint_id(links["dps"], "dps", ns, self.subscription_id) if links.get("dps") else "",
            "root": cms.get("rootName", ""), "intermediate": cms.get("intermediateName", ""),
            "policy": cms.get("policyName", ""), "validity": str(cms.get("validityDays", 30)),
        }
        for key, value in fields.items():
            self.query_one(f"#{key}", Input).value = value
        self.query_one("#hub-ids", TextArea).load_text("\n".join(
            endpoint_id(item, "hub", ns, self.subscription_id) for item in links.get("hubs", [])
        ))
        self.query_one("#mode", Select).value = "existing" if links.get("dps") or links.get("hubs") else "skip"
        self.query_one("#cms", Checkbox).value = bool(cms.get("enabled"))
        self.query_one("#software-updates", Checkbox).value = bool(links.get("softwareUpdates"))
        self.refresh_disclosure()

    @work(thread=True)
    def apply_plan(self):
        try:
            request, current = self.read_plan(self.config)
            if plan_fingerprint(current) != plan_fingerprint(self.plan):
                self.call_from_thread(self.accept_plan, self.config, request, current)
                return
            if self.stop_requested.is_set():
                raise SetupStopped("Stopped before apply.")
            self.call_from_thread(self.begin_run)
            with quiet_providers():
                result = NamespaceWorkflow(self.services, progress=SetupProgress(self)).setup(request)
        except Exception as error:  # Preserve partial workflow failures and report them without swallowing.
            self.call_from_thread(self.finish_error, error, True)
        else:
            self.call_from_thread(self.finish_run, result)

    def begin_run(self):
        self.started = monotonic()
        self.operation_log = []
        self.set_step(4)
        self.notice("Writes approved. Stop watching prevents unstarted steps; Azure operations are not cancelled.")
        if self.animation_level != "none":
            self.timer = self.set_interval(0.1, self.tick)

    def operation_status(self, label):
        self.operation = label
        self.operation_log.append(label)
        self.query_one("#run-log", Static).update(Text("\n".join(self.operation_log[-12:])))
        self.tick()

    def tick(self):
        elapsed = max(0, int(monotonic() - self.started))
        frames = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"
        marker = frames[int(monotonic() * 10) % len(frames)] if self.busy and self.timer else "-"
        self.query_one("#progress", Static).update(
            Text(f"{marker} {self.operation}  /  {elapsed}s", style="#7cc4fa")
        )

    def stop_timer(self):
        if self.timer:
            self.timer.stop()
            self.timer = None

    def finish_error(self, error, execution):
        self.set_busy(False)
        self.stop_timer()
        self.notice(str(error))
        if execution:
            self.result = getattr(error, "result", {"state": "Failed", "items": [], "message": str(error)})
            if self.stop_requested.is_set():
                self.result["state"] = "Stopped"
            self.set_step(4)
            self.query_one("#retry", Button).focus()
        else:
            self.plan = None
            self.request = None
            self.set_step(self.step)
        self.stop_requested.clear()

    def finish_run(self, result):
        self.set_busy(False)
        self.result = result
        self.stop_timer()
        self.set_step(4)
        self.operation_status(f"Setup {result['state']}.")
        self.notice(
            f"Read-only diagnostics: az iot adr ns check -n {self.request.namespace_name} "
            f"-g {self.request.resource_group_name} --subscription {self.subscription_id}"
        )
        self.query_one("#close", Button).focus()

    def browse(self, targets=False):
        if self.busy:
            return
        group = self.query_one("#group", Input).value.strip()
        self.stop_requested.clear()
        self.set_busy(True)
        self.notice("Loading accessible resources...")
        self.browse_worker(group, targets)

    @work(thread=True)
    def browse_worker(self, group, targets):
        try:
            if not group:
                raise InvalidArgumentValueError("Enter a resource group first.")
            namespaces = [] if targets else self.services.list_namespaces(group)
            dps = self.services.list_link_targets("dps", group) if targets else []
            hubs = self.services.list_link_targets("hub", group) if targets else []
        except Exception as error:  # Read-only browsing errors remain visible; exact IDs are still accepted.
            self.call_from_thread(self.finish_error, error, False)
        else:
            self.call_from_thread(self.accept_choices, namespaces, dps, hubs, group, targets)

    def accept_choices(self, namespaces, dps, hubs, group, targets):
        self.set_busy(False)
        if self.stop_requested.is_set():
            self.finish_error(SetupStopped("Stopped reading. Browse again when ready."), False)
            return
        if self.query_one("#group", Input).value.strip() != group:
            return
        if targets:
            selected = set(self.query_one("#hub-ids", TextArea).text.splitlines())
            self.query_one("#dps-choice", Select).set_options([(item["name"], item["id"]) for item in dps])
            choices = self.query_one("#hub-choices", SelectionList)
            choices.clear_options()
            choices.add_options([(item["name"], item["id"], item["id"] in selected) for item in hubs])
        else:
            self.query_one("#namespace-choice", Select).set_options([
                (item["name"], item["name"]) for item in namespaces
            ])
        self.notice("Resources loaded. You can also enter exact resource IDs.")

    def on_unmount(self):
        self.stop_requested.set()
        self.stop_timer()


def run_setup(cmd, *, config=None, output_script=None, **arguments):
    from azure.cli.core.commands.client_factory import get_subscription_id
    from azext_iot.adr.workflows.configuration import load_config, request_config
    from azext_iot.adr.workflows.services import WorkflowServices

    subscription = get_subscription_id(cmd.cli_ctx)
    review = False
    if config is not None:
        initial = load_config(config)
        if any(arguments.get(key) for key in (
            "namespace_outbound_identity", "dps", "hubs", "software_updates", "complete_connectivity",
        )):
            raise ArgumentUsageError("--config cannot be combined with workflow capability arguments.")
        if initial.get("subscriptionId", subscription).casefold() != subscription.casefold():
            raise InvalidArgumentValueError(
                "Workflow config subscriptionId does not match the selected subscription. "
                "Select it explicitly with --subscription."
            )
        namespace = initial.setdefault("namespace", {})
        for field, argument in (
            ("name", "namespace_name"), ("resourceGroup", "resource_group_name"),
            ("location", "location"), ("tags", "tags"),
        ):
            explicit = arguments.get(argument)
            if explicit is not None:
                if field in namespace and namespace[field] != explicit:
                    raise InvalidArgumentValueError(
                        f"Workflow config namespace.{field} conflicts with explicit CLI input."
                    )
                namespace[field] = explicit
        initial = load_config(initial)
        review = bool(namespace.get("name") and namespace.get("resourceGroup"))
        if review:
            request = build_setup_request(None, None, subscription, config=initial, no_input=True, interactive=False)
            initial = request_config(request)
    elif any(arguments.get(key) for key in (
        "dps", "hubs", "software_updates", "complete_connectivity",
    )):
        request = build_setup_request(
            subscription_id=subscription, config=config, no_input=True, interactive=False, **arguments,
        )
        initial = request_config(request)
    else:
        namespace = {
            key: arguments[source] for key, source in (
                ("name", "namespace_name"), ("resourceGroup", "resource_group_name"),
                ("location", "location"), ("tags", "tags"),
            ) if arguments.get(source) is not None
        }
        identity = arguments.get("namespace_outbound_identity")
        if identity:
            namespace["outboundIdentity"] = (
                {"type": "SystemAssigned"} if identity == "system-assigned"
                else {"type": "UserAssigned", "userAssignedResourceId": identity}
            )
        initial = load_config({"namespace": namespace})
    app = SetupApp(
        WorkflowServices(cmd), subscription, initial, review=review, output_script=output_script,
    )
    return app.run(mouse=True)
