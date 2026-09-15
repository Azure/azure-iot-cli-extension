# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import AbstractContextManager
from io import StringIO
import sys
import time
from typing import Any, Callable, Dict, Optional

from azure.cli.core.azclierror import AzCLIError
from prompt_toolkit import ANSI, PromptSession
from prompt_toolkit.completion import Completer, FuzzyWordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from prompt_toolkit.output.defaults import create_output
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.theme import Theme

from azext_iot.adr.providers.base import console as provider_console
from azext_iot.adr.workflows.input import BackRequested, WorkflowCancelled
from azext_iot.constants import VERSION


_THEME = Theme(
    {
        "brand": "#eef1f4",
        "active": "#4aa8ff",
        "satisfied": "#57c98a",
        "planned": "#57c98a",
        "manual": "#e0b464",
        "blocked": "#ec7367",
        "warning": "#e0b464",
        "muted": "#7c8794",
        "body": "#d6d9de",
        "selected": "#4aa8ff on #1b2734",
    }
)
_SYMBOLS = {
    "Satisfied": ("✓", "[satisfied]", "satisfied"),
    "Succeeded": ("✓", "[done]", "satisfied"),
    "Planned": ("+", "[planned]", "planned"),
    "Manual": ("!", "[manual]", "manual"),
    "Blocked": ("✖", "[blocked]", "blocked"),
    "Failed": ("✖", "[failed]", "blocked"),
    "Warning": ("!", "[warning]", "warning"),
    "NotConfigured": ("~", "[not configured]", "muted"),
}


class InputFilteredCompleter(Completer):
    def __init__(self, completer):
        self.completer = completer

    def get_completions(self, document, complete_event):
        if not document.text_before_cursor.strip():
            return
        yield from self.completer.get_completions(
            document, complete_event
        )


class RenderedWorkflowError(AzCLIError):
    def __init__(
        self,
        error: Exception,
        renderer: "WorkflowRenderer",
        result: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(str(error) or error.__class__.__name__)
        self.error = error
        self.renderer = renderer
        self.result = result

    def print_error(self):
        self.renderer.error(self, self.result)


class WorkflowRenderer:
    def __init__(
        self,
        command_name: str,
        plain: bool = False,
        console: Optional[Console] = None,
    ):
        self.command_name = command_name
        injected_console = console is not None
        self.console = console or Console(
            stderr=True,
            theme=_THEME,
            no_color=plain,
            highlight=False,
        )
        self.rich = (
            self.console.is_terminal
            and (injected_console or sys.stdin.isatty())
            and not plain
        )
        self.content_width = min(96, max(40, self.console.width))
        self._phase = None
        self._stages = ()
        self._subscription_id = None
        self._body = []
        self._tasks = []
        self._account = {}
        self._hold_live = None
        self._alert = None
        self._busy = None
        self._header_printed = False
        self._printed_statuses = {}
        self._printed_phase = None
        self._phase_pending = False
        self._plan_actions = 0
        self._execution_started = None
        self._execution_completed = 0
        self._execution_total = 0
        self._failure: Optional[Dict[str, Any]] = None
        self._mutated_scopes = set()
        self._search_context = None
        self._footer = ":back previous · :help commands · :quit cancel"
        bindings = KeyBindings()
        bindings.add("escape")(self._back_key)
        bindings.add("up")(self._up_key)
        bindings.add("down")(self._down_key)
        self._base_bindings = bindings

        self._prompt_style = Style.from_dict(
            {
                "completion-menu.completion": "fg:#7c8794",
                "completion-menu.completion.current": (
                    "fg:#4aa8ff bg:#1b2734"
                ),
                "scrollbar.background": "bg:#101317",
                "scrollbar.button": "bg:#3b424b",
            }
        )
        self._prompt_session = (
            self._create_prompt_session() if self.rich else None
        )

    def _create_prompt_session(self):
        return PromptSession(
            erase_when_done=True,
            reserve_space_for_menu=8,
            output=create_output(stdout=sys.stderr),
            key_bindings=self._base_bindings,
            style=self._prompt_style,
        )

    @staticmethod
    def _back_key(event):
        event.app.exit(result=":back")

    @staticmethod
    def _up_key(event):
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_previous()
        elif buffer.text.strip():
            buffer.start_completion(select_first=False)

    @staticmethod
    def _down_key(event):
        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_next()
        elif buffer.text.strip():
            buffer.start_completion(select_first=False)

    def prompt(self, label: str) -> str:
        return self._prompt(label)

    def select(
        self,
        title: str,
        options: Dict[str, tuple],
        guidance: Optional[str] = None,
        allow_custom: bool = False,
        show_options: bool = True,
    ) -> str:
        self._ensure_phase()
        lookup = {}
        self._body.clear()
        self._show(title)
        if self._search_context:
            self._show(f"searched         {self._search_context}")
        if guidance:
            self._show(guidance)
        words = []
        for number, (value, label, *aliases) in enumerate(
            options.values(), start=1
        ):
            display = f"{number}  {label}"
            if not self.rich or show_options:
                self._show(display)
            words.append(str(label))
            for key in (str(number), label, value, *aliases):
                lookup[str(key).casefold()] = value
        completer = InputFilteredCompleter(
            FuzzyWordCompleter(
                [str(word) for word in words if word],
                WORD=True,
            )
        )
        self._footer = (
            "number choose · enter select · [esc] back · "
            "[?] help · [ctrl-c] cancel"
            if show_options
            else
            "↑↓ choose · enter select · type to filter · "
            "[esc] back · [?] help · [ctrl-c] cancel"
        )
        while True:
            raw_choice = self._prompt(
                "❯ ",
                completer=completer,
                action_keys=(
                    {
                        key: value
                        for key, value in lookup.items()
                        if len(key) == 1 and len(options) <= 9
                    }
                    if show_options
                    else None
                ),
            ).strip()
            choice = raw_choice.casefold()
            if show_options and choice in {"q", "quit"}:
                raise WorkflowCancelled()
            selected = lookup.get(choice)
            if selected is not None:
                self._body.clear()
                self._alert = None
                self._search_context = None
                self._footer = (
                    ":back previous · :help commands · :quit cancel"
                )
                self._refresh_hold()
                return selected
            if allow_custom and choice:
                self._body.clear()
                self._alert = None
                self._search_context = None
                self._refresh_hold()
                return raw_choice
            if self.rich:
                self._body[:] = [
                    title,
                    "! Choose a listed number or name.",
                ]
            else:
                self.console.print(
                    "! Choose a listed number or name.",
                    markup=False,
                )

    def action(
        self,
        title: str,
        actions: Dict[str, str],
        default: Optional[str] = None,
    ) -> str:
        self._ensure_phase()
        self._body.clear()
        lookup = {
            alias: key
            for index, (key, label) in enumerate(
                actions.items(), start=1
            )
            for alias in (
                key,
                label.casefold(),
                label.casefold().split()[0],
                str(index),
            )
        }
        self._footer = " · ".join(
            [
                *(f"[{key}] {label}" for key, label in actions.items()),
                "[esc] back",
                "[?] help",
                "[ctrl-c] cancel",
            ]
        )
        if not self.rich:
            self.console.print(self._footer, style="muted", markup=False)
        while True:
            value = self._prompt(
                f"❯ {title} ",
                action_keys={
                    key: key
                    for key in actions
                    if key != "enter"
                },
            ).casefold()
            if not value and default:
                self._body.clear()
                self._alert = None
                self._footer = (
                    ":back previous · :help commands · :quit cancel"
                )
                return default
            selected = lookup.get(value)
            if selected:
                self._body.clear()
                self._alert = None
                self._footer = (
                    ":back previous · :help commands · :quit cancel"
                )
                return selected
            if self.rich:
                self._body[:] = [
                    "! Choose one of the highlighted keys.",
                ]
            else:
                self.console.print(
                    "! Choose one of the highlighted keys.",
                    markup=False,
                )

    def _prompt(
        self,
        label: str,
        completer=None,
        action_keys: Optional[Dict[str, str]] = None,
    ) -> str:
        self._ensure_phase()
        while True:
            if self.rich:
                self._stop_hold()
                self._prompt_session.default_buffer.reset()
                value = self._prompt_session.prompt(
                    ANSI(self._workspace_ansi(label)),
                    completer=completer,
                    complete_style=CompleteStyle.COLUMN,
                    complete_while_typing=bool(completer),
                    style=self._prompt_style,
                    bottom_toolbar=ANSI(self._footer_ansi()),
                    key_bindings=(
                        self._action_bindings(action_keys)
                        if action_keys
                        else None
                    ),
                ).strip()
                if action_keys:
                    self._prompt_session = self._create_prompt_session()
            else:
                self.console.print(
                    label, style="active", end="", markup=False
                )
                value = input().strip()
            command = value.casefold()
            if command == ":back":
                self._start_hold()
                raise BackRequested()
            if command == ":quit":
                self._body.clear()
                raise WorkflowCancelled()
            if command in {":help", "?"}:
                help_text = (
                    ":back previous input  ·  :help commands  ·  :quit cancel"
                )
                if help_text not in self._body:
                    self._show(help_text)
                continue
            self._start_hold()
            return value

    def _action_bindings(self, actions):
        bindings = KeyBindings()
        bindings.add("escape")(self._back_key)
        bindings.add("up")(self._up_key)
        bindings.add("down")(self._down_key)

        def help_key(event):
            event.app.exit(result="?")

        bindings.add("?")(help_key)

        for key, value in actions.items():
            def accept(event, selected=value):
                event.app.exit(result=selected)

            bindings.add(key)(accept)
        return bindings

    def write(self, message: str):
        if not self.rich:
            self.console.print(message, markup=False)
            return
        if message.startswith("!"):
            self._alert = message
            self._refresh_hold()
            return
        self._show(message)

    def busy(self, message: str):
        self._ensure_phase()
        if not self.rich:
            self.console.print(
                f"[working] {message}", markup=False, style="active"
            )
            return
        self._alert = None
        self._busy = message
        self._start_hold()
        self._refresh_hold()

    def idle(self):
        self._busy = None
        self._refresh_hold()

    def search_context(self, resource_group=None):
        subscription = (
            self._account.get("subscriptionName")
            or self._subscription_id
        )
        self._search_context = " · ".join(
            str(value)
            for value in (resource_group, subscription)
            if value
        )

    def clear_search_context(self):
        self._search_context = None

    def notice(self, message):
        self._stop_hold()
        line = Text("✔ ", style="satisfied")
        line.append(message, style="body")
        self.console.print(line)

    def header(
        self,
        subscription_id: str,
        resource_group_name: Optional[str],
        namespace_name: Optional[str],
    ):
        self._subscription_id = subscription_id
        if self._header_printed:
            return
        self._header_printed = True
        launch = Text()
        launch.append(
            f"$ az iot adr ns {self.command_name.split()[-1].lower()}",
            style="satisfied",
        )
        launch.append(
            f"\npreview command · v{VERSION} · reference and support: "
            "aka.ms/CLI_refstatus",
            style="muted",
        )
        launch.append(
            f"\n\nAzure IoT · Device Registry {self.command_name.lower()}",
            style="brand",
        )
        launch.append(
            "\nNothing is applied until you review and confirm the plan. "
            "ctrl-c aborts.",
            style="muted",
        )
        self.console.print(launch)

    def account(self, value: Dict[str, Any]):
        self._account = dict(value or {})
        self._subscription_id = (
            self._account.get("subscriptionId")
            or self._subscription_id
        )
        if self._account.get("userName"):
            tenant = (
                f"tenant {self._account['tenantId']}"
                if self._account.get("tenantId")
                else ""
            )
            self._print_summary(
                "Account",
                str(self._account["userName"]),
                tenant,
            )

    def journey(self, *stages: str):
        self._stages = stages
        self._phase_pending = True

    def phase(self, name: str):
        if self._phase == name:
            return
        self._stop_hold()
        self._phase = name
        self._body.clear()
        self._alert = None
        self._busy = None
        self._phase_pending = True

    def input_status(
        self,
        label: str,
        value: str,
        state: str,
        message: str = "",
    ):
        self._alert = None
        self._busy = None
        self._stop_hold()
        detail = message
        if state == "Planned" and "nothing" not in detail.casefold():
            detail = (
                f"{detail} · nothing written yet"
                if detail
                else "nothing written yet"
            )
        self._print_summary(label, value, detail, state)

    def validation(
        self,
        plan: Dict[str, Any],
        item_filter: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        self._ensure_phase()
        items = [
            item
            for item in plan["items"]
            if item["action"] in {"validate", "reuse", "check"}
            and (item_filter is None or item_filter(item))
        ]
        if not items:
            return
        self._stop_hold()
        self.console.print("\nValidation", style="brand")
        for item in items:
            self._status_line(item)

    def trust(self, plan: Dict[str, Any]):
        self._ensure_phase()
        roles = [
            item
            for item in plan["items"]
            if (item.get("details") or {}).get("role")
        ]
        if not roles:
            return
        self._stop_hold()
        self.console.print("\nIdentity and permissions", style="brand")
        for item in roles:
            details = item.get("details") or {}
            principal = str(details.get("principalId") or "resolved at apply")
            role = str(details.get("role") or "required role")
            target = item["target"]
            line = Text("  ")
            line.append(principal)
            line.append(" ── ")
            line.append(role)
            line.append(" ──> ")
            line.append(target)
            self.console.print(line, soft_wrap=True)
            self._status_line(item, indent="    ")

    def plan(self, plan: Dict[str, Any]):
        self._ensure_phase()
        self._plan_actions = sum(
            item.get("state") in {"Planned", "Manual"}
            for item in plan.get("items", [])
        )
        self._stop_hold()
        self.console.print()
        self._print_plan_header("awaiting confirmation")
        for item in plan.get("items", []):
            self.console.print(self._plan_row(item), soft_wrap=True)

    def confirmation(self, plan: Dict[str, Any]):
        changes = sum(
            count
            for state, count in plan.get("summary", {}).items()
            if state in {"Planned", "Manual"}
        )
        role_changes = sum(
            item.get("action") == "grant"
            and item.get("state") == "Planned"
            for item in plan.get("items", [])
        )
        role_message = (
            f"{role_changes} missing role assignment(s) will be created."
            if role_changes
            else (
                "Atomic link commands own service role validation and "
                "creation."
            )
        )
        self._body[:] = [
            f"{changes} change(s) · {role_message}",
            "Successful operations are preserved if a later step fails.",
        ]
        if not self.rich:
            self.console.print("\n".join(self._body), markup=False)
        self._refresh_hold()

    def confirmed(self):
        self._body.clear()
        self._stop_hold()
        self.console.print()
        self._print_plan_header("confirmed")

    def recovery(self, can_continue=False):
        actions = {"r": "retry this step"}
        if can_continue:
            actions["c"] = "continue without it"
        actions["q"] = "quit"
        return self.action("Apply could not finish.", actions)

    @property
    def failure(self):
        return self._failure

    @property
    def mutated_scopes(self):
        return frozenset(self._mutated_scopes)

    def _print_plan_header(self, state):
        line = Text("Plan", style="brand")
        line.append(
            f"{'':<32}{self._plan_actions} actions · {state}",
            style="muted",
        )
        self.console.print(line)

    @classmethod
    def _plan_row(cls, item):
        symbol, _, style = _SYMBOLS.get(
            item.get("state"), ("·", "", "muted")
        )
        action, subject, value = cls._plan_columns(item)
        row = Text()
        row.append(symbol, style=style)
        row.append(f" {action:<12}", style=style)
        row.append(f"{subject:<28}", style="muted")
        row.append(value, style="body")
        for label, detail in cls._plan_details(item):
            row.append(f"\n  {'':<12}{label.lower():<28}", style="muted")
            row.append(detail, style="body")
        return row

    @staticmethod
    def _plan_columns(item):
        item_id = str(item.get("id") or "")
        action = str(item.get("action") or "update")
        target = str(item.get("target") or "")
        if item_id == "namespace":
            return action, "namespace", target
        if item_id == "namespace-tags":
            return action, "namespace tags", target
        if item_id == "namespace-outbound-identity":
            identity = (item.get("details") or {}).get(
                "identityType", target
            )
            return action, "outbound identity", str(identity)
        if item_id.startswith("resource-"):
            return action, "target resource", target
        if item_id.startswith("link-"):
            kind = item_id.split("-", 2)[1]
            return action, f"{kind} link", target
        if item_id.startswith(("role-", "roles-")):
            role = (item.get("details") or {}).get("role")
            return action, "access", str(role or target)
        if item_id.startswith("skip-"):
            return "skip", target, "not configured in this run"
        if item_id == "namespace-status":
            return action, "namespace status", target
        return action, target, ""

    @staticmethod
    def _execution_row(state, label, elapsed):
        symbol, _, style = _SYMBOLS[state]
        row = Text(symbol, style=style)
        row.append(f" {label:<56}", style="body")
        row.append(f"{elapsed:>7.1f}s", style="muted")
        return row

    def receipt(self, result: Dict[str, Any]):
        summary = result.get("summary", {})
        if not self.rich:
            lines = [
                f"{self.command_name} complete",
                f"Namespace: {result.get('namespace')}",
                f"State: {result.get('state')}",
            ]
            lines.extend(f"{state}: {count}" for state, count in summary.items())
            self.console.print("\n".join(lines), markup=False)
            return
        self._stop_hold()
        self._body.clear()
        self._tasks.clear()
        self._body.extend(
            [
                f"State: {result.get('state')}",
                *(
                    [
                        "Elapsed: "
                        f"{time.monotonic() - self._execution_started:.1f}s"
                    ]
                    if self._execution_started is not None
                    else []
                ),
                *(
                    f"{state}: {count}"
                    for state, count in summary.items()
                ),
            ]
        )
        if self.command_name == "Namespace check":
            for item in result.get("items", []):
                self._body.append(
                    f"{_SYMBOLS.get(item.get('state'), ('○', '', ''))[0]} "
                    f"{item.get('target')}: "
                    f"{item.get('message') or item.get('state')}"
                )
        else:
            namespace_id = (
                f"/subscriptions/{self._subscription_id}"
                f"/resourceGroups/{result.get('resourceGroup')}"
                "/providers/Microsoft.DeviceRegistry/namespaces/"
                f"{result.get('namespace')}"
            )
            self._body.append(f"Resource ID: {namespace_id}")
            principals = {
                str((item.get("details") or {}).get("principalId"))
                for item in result.get("items", [])
                if (item.get("details") or {}).get("principalId")
            }
            for principal in sorted(principals):
                self._body.append(f"Identity principal: {principal}")
            for item in result.get("items", []):
                item_id = str(item.get("id") or "")
                if item_id.startswith("link-") or item_id.startswith("skip-"):
                    self._body.append(
                        f"{_SYMBOLS.get(item.get('state'), ('○', '', ''))[0]} "
                        f"{self._plan_label(item)}"
                    )
        if result.get("receipt"):
            self._body.append(f"Receipt: {result['receipt']}")
        manual_items = [
            item
            for item in result.get("items", [])
            if item.get("state") == "Manual"
        ]
        for item in manual_items:
            self._body.append(
                f"Manual: {self._plan_label(item)}"
            )
            if item.get("command"):
                self._body.append(f"  {item['command']}")
        if manual_items:
            self._body.append(
                "Resume: "
                + str(
                    result.get("resumeCommand")
                    or (
                        "az iot adr ns setup "
                        f"-n {result.get('namespace')} "
                        f"-g {result.get('resourceGroup')} --yes"
                    )
                )
            )
        else:
            self._body.extend(
                [
                    "Next: az iot adr ns show "
                    f"-n {result.get('namespace')} "
                    f"-g {result.get('resourceGroup')}",
                    "Next: az iot adr ns check "
                    f"-n {result.get('namespace')} "
                    f"-g {result.get('resourceGroup')}",
                ]
            )
        style = (
            "satisfied"
            if result.get("state") == "Succeeded"
            else "warning"
        )
        self.console.print(
            self._final_view(
                f"✓ {self.command_name} complete", style
            )
        )

    def error(self, error: Exception, result: Optional[Dict[str, Any]] = None):
        self._stop_hold()
        self._body.clear()
        self._tasks.clear()
        original = getattr(error, "error", error)
        original = getattr(original, "__cause__", None) or original
        kept = sum(
            item.get("state") == "Succeeded"
            for item in (result or {}).get("items", [])
        )
        kept = max(kept, int((result or {}).get("keptActions", 0)))
        failed = max(
            1,
            sum(
                item.get("state") == "Failed"
                for item in (result or {}).get("items", [])
            ),
        )
        total = max(self._plan_actions, kept + failed)
        self._body.append(str(original) or original.__class__.__name__)
        failure = self._failure
        if failure:
            failure_label = failure.get("label")
            failure_elapsed = failure.get("elapsed")
            self._body.append(
                f"{'step':<14}{failure_label}"
            )
            self._body.append(
                f"{'elapsed':<14}{float(failure_elapsed):.1f}s"
            )
        self._body.extend(self._failure_metadata(original))
        self._body.append("Exit: nonzero")
        if result:
            self._body.append(
                f"{kept} of {total} kept · rerunning setup is safe."
            )
            for item in result.get("items", []):
                if item["state"] not in {"Manual", "Blocked", "Failed"}:
                    continue
                self._body.append(
                    f"{item['target']}: "
                    f"{item.get('message') or item['state']}"
                )
                if item.get("command"):
                    self._body.append(f"Fix: {item['command']}")
            if result.get("receipt"):
                self._body.append(f"Receipt: {result['receipt']}")
            if result.get("receiptError"):
                self._body.append(
                    "Receipt write failed: "
                    f"{result['receiptError']}"
                )
        self.console.print(
            self._final_view(
                f"! {failed} of {total} actions failed · "
                f"{kept} of {total} kept",
                "blocked",
            )
        )

    @staticmethod
    def _failure_metadata(error):
        code = (
            getattr(error, "error_code", None)
            or getattr(error, "code", None)
        )
        response = getattr(error, "response", None)
        status = (
            getattr(error, "status_code", None)
            or getattr(response, "status_code", None)
        )
        retries = getattr(error, "retry_count", None)
        values = (
            ("code", code),
            ("status", status),
            ("retries", retries),
        )
        return [
            f"{label:<14}{value}"
            for label, value in values
            if value is not None
        ]

    def cancelled(self):
        self._stop_hold()
        message = Text(f"{self.command_name} cancelled", style="brand")
        message.append(" · Nothing was changed.", style="muted")
        self.console.print(message)

    def execution(self):
        return WorkflowExecution(self)

    def close(self):
        self._stop_hold()

    def reset_setup(self):
        self._stop_hold()
        self._body.clear()
        self._alert = None
        self._busy = None
        self._tasks.clear()
        self._phase = None
        self.phase("Configuration")

    def _print_summary(
        self,
        label: str,
        value: str,
        detail: str = "",
        state: str = "Satisfied",
    ):
        self._ensure_phase()
        signature = (value, detail, state)
        if self._printed_statuses.get(label) == signature:
            return
        self._printed_statuses[label] = signature
        symbol, _, style = _SYMBOLS.get(
            state, ("·", "", "muted")
        )
        line = Text()
        line.append(symbol, style=style)
        line.append(f" {label.lower():<18}", style="muted")
        line.append(str(value), style="body")
        if detail:
            line.append(f" · {detail}", style="muted")
        self.console.print(line, soft_wrap=True)

    def _ensure_phase(self):
        if not self._phase_pending or not self._stages:
            return
        active = self._active_stage()
        signature = (active, self._stages)
        self._phase_pending = False
        if self._printed_phase == signature:
            return
        self._printed_phase = signature
        current = self._stages.index(active) + 1
        line = Text(f"\nstep {current}/{len(self._stages)}  ", style="muted")
        for index, stage in enumerate(self._stages):
            if index:
                line.append(" ── ", style="muted")
            if index < current - 1:
                line.append("✔ ", style="satisfied")
                line.append(stage.lower(), style="satisfied")
            elif index == current - 1:
                line.append("● ", style="active")
                line.append(stage.lower(), style="active")
            else:
                line.append("○ ", style="muted")
                line.append(stage.lower(), style="muted")
        self.console.print(line)

    def _show(self, message: str):
        if self.rich:
            self._body.append(message)
            self._body[:] = self._body[-12:]
            self._refresh_hold()
        else:
            self.console.print(message, markup=False)

    def _start_hold(self):
        if not self.rich or self._hold_live:
            return
        self._hold_live = Live(
            self._workspace(),
            console=self.console,
            transient=True,
            auto_refresh=False,
        )
        self._hold_live.start(refresh=True)

    def _refresh_hold(self):
        if self._hold_live:
            self._hold_live.update(
                self._workspace(), refresh=True
            )

    def _stop_hold(self):
        if not self._hold_live:
            return
        self._hold_live.stop()
        self._hold_live = None

    def _workspace_ansi(self, prompt_label: str) -> str:
        stream = StringIO()
        console = Console(
            file=stream,
            force_terminal=True,
            color_system=self.console.color_system or "standard",
            width=self.console.width,
            theme=_THEME,
            highlight=False,
        )
        console.print(self._workspace(include_footer=False))
        console.print(
            prompt_label,
            style="active",
            end="",
            markup=False,
        )
        return stream.getvalue()

    def _footer_ansi(self) -> str:
        stream = StringIO()
        console = Console(
            file=stream,
            force_terminal=True,
            color_system=self.console.color_system or "standard",
            width=self.console.width,
            theme=_THEME,
            highlight=False,
        )
        footer = Text()
        self._append_footer(footer)
        console.print(footer, end="")
        return stream.getvalue()

    def _workspace(self, include_footer=True):
        content = Text()
        if self._tasks:
            active = self._tasks[-1]
            total = max(
                self._execution_total,
                self._execution_completed + 1,
            )
            content.append("Applying", style="brand")
            content.append(
                f"  {self._execution_completed}/{total}",
                style="muted",
            )
            if self._execution_started is not None:
                content.append(
                    f" · {time.monotonic() - self._execution_started:.1f}s",
                    style="muted",
                )
            content.append("\n")
            content.append("⠋ ", style="active")
            content.append(str(active["target"]), style="body")

        if self._body:
            if content:
                content.append("\n\n")
            for index, line in enumerate(self._body):
                if index:
                    content.append("\n")
                content.append(str(line))

        if self._busy:
            if content:
                content.append("\n\n")
            content.append("⠋ ", style="active")
            content.append(self._busy, style="body")
        if self._alert:
            if content:
                content.append("\n\n")
            content.append(self._alert, style="blocked")

        if include_footer and not self._tasks:
            if content:
                content.append("\n\n")
            self._append_footer(content)
        return content

    def _append_footer(self, content: Text):
        for index, item in enumerate(self._footer.split(" · ")):
            if index:
                content.append(" · ", style="muted")
            key, separator, description = item.partition(" ")
            content.append(key, style="active")
            if separator:
                content.append(
                    f"{separator}{description}",
                    style="muted",
                )

    def _active_stage(self):
        if self._phase in self._stages:
            return self._phase
        if "Subscription" in self._stages:
            return "Configuration"
        if self._phase in {"Subscription", "Resource group", "Namespace"}:
            return "Scope"
        if self._phase == "Links":
            return "Results"
        return self._stages[0] if self._stages else ""

    def _final_view(self, title: str, style: str):
        content = Text()
        content.append(title, style=style)
        content.append("\n")
        content.append("─" * min(self.content_width, len(title) + 12), style="muted")
        if self._body:
            content.append("\n")
            for line in self._body:
                content.append(f"\n{line}")
        return content

    @staticmethod
    def _plan_details(item: Dict[str, Any]):
        details = item.get("details") or {}
        result = []
        if details.get("resourceId"):
            result.append(
                ("Target", str(details["resourceId"]))
            )
        identity = (
            details.get("userAssignedIdentity")
            or details.get("identityType")
        )
        if identity:
            result.append(("Identity", str(identity)))
        if details.get("role"):
            result.append(("Role", str(details["role"])))
        if details.get("principalId"):
            result.append(
                ("Principal", str(details["principalId"]))
            )
        if details.get("location"):
            result.append(("Location", str(details["location"])))
        if details.get("tags"):
            result.append(
                (
                    "Tags",
                    ", ".join(
                        f"{key}={value}"
                        for key, value in sorted(
                            details["tags"].items()
                        )
                    ),
                )
            )
        if item.get("message"):
            result.append(("Reason", str(item["message"])))
        return result

    @staticmethod
    def _plan_label(item: Dict[str, Any]) -> str:
        item_id = str(item.get("id") or "")
        action = str(item.get("action") or "update")
        target = str(item.get("target") or "")
        if item_id == "namespace":
            verb = "Create" if action == "create" else "Use"
            return f"{verb} namespace: {target}"
        if item_id == "namespace-outbound-identity":
            return f"Configure namespace outbound identity: {target}"
        if item_id.startswith("resource-software-updates-"):
            verb = "Create" if action == "create" else "Validate"
            return f"{verb} Update Instance: {target}"
        if item_id.startswith("resource-dps-"):
            return f"Validate DPS: {target}"
        if item_id.startswith("resource-hub-"):
            return f"Validate IoT Hub: {target}"
        if item_id.startswith("link-dps-"):
            return f"Configure DPS link: {target}"
        if item_id.startswith("link-hub-"):
            return f"Configure IoT Hub link: {target}"
        if item_id.startswith("link-software-updates-"):
            return f"Configure Software Updates link: {target}"
        if item_id.startswith("role") or item_id.startswith("roles-"):
            return f"Configure access: {target}"
        if item_id == "hub-prerequisite":
            return f"Check Hub prerequisite: {target}"
        if item_id.startswith("skip-"):
            return f"Skip {target}: not configured in this run"
        if item_id == "namespace-status":
            return f"Check namespace status: {target}"
        return f"{action.capitalize()} {target}"

    def _status_line(self, item: Dict[str, Any], indent: str = ""):
        symbol, fallback, style = _SYMBOLS.get(
            item["state"], ("…", "[pending]", "muted")
        )
        line = Text(indent)
        line.append(symbol or fallback, style=style)
        line.append(
            f" {str(item.get('action') or ''):<12}",
            style=style,
        )
        line.append(str(item["target"]), style="body")
        if item.get("message"):
            line.append(f" · {item['message']}", style="muted")
        self.console.print(line, soft_wrap=True)


class WorkflowExecution(AbstractContextManager):
    def __init__(self, renderer: WorkflowRenderer):
        self.renderer = renderer
        self.console = renderer.console
        self.rich = renderer.rich
        self.live = None
        self._provider_quiet = provider_console.quiet

    def __enter__(self):
        provider_console.quiet = True
        if self.renderer._execution_started is None:
            self.renderer._execution_started = time.monotonic()
        self.renderer._execution_completed = 0
        self.renderer._execution_total = max(
            1, self.renderer._plan_actions
        )
        self.renderer._failure = None
        if self.rich:
            self.renderer.close()
            self.renderer._body.clear()
            self.renderer._tasks.clear()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.live:
            self.live.stop()
            self.live = None
        provider_console.quiet = self._provider_quiet
        return False

    def run(
        self,
        label: str,
        operation: Callable,
        *args,
        workflow_scope=None,
        mutation=False,
        handled_error=None,
        **kwargs,
    ):
        if not self.rich:
            self.console.print(
                f"[running] {label}", markup=False, style="active"
            )
        task = {
            "state": "Warning",
            "target": label,
            "message": "running",
            "startedAt": time.monotonic(),
        }
        if self.rich:
            self.renderer._tasks[:] = [task]
            self.live = Live(
                self.renderer._workspace(include_footer=False),
                console=self.console,
                transient=True,
                auto_refresh=False,
            )
            self.live.start(refresh=True)
        try:
            result = operation(*args, **kwargs)
        except Exception as error:
            elapsed = time.monotonic() - task["startedAt"]
            if handled_error and handled_error(error):
                if self.rich:
                    self.live.stop()
                    self.live = None
                self.renderer._tasks.clear()
                raise
            self.renderer._failure = {
                "label": label,
                "elapsed": elapsed,
                "error": error,
                "scope": workflow_scope,
                "mutationAttempted": mutation,
            }
            if self.rich:
                self.live.stop()
                self.live = None
                self.console.print(
                    self.renderer._execution_row(
                        "Failed", label, elapsed
                    )
                )
            else:
                self.console.print(
                    f"[failed] {label} · {elapsed:.1f}s",
                    markup=False,
                    style="blocked",
                )
            self.renderer._tasks.clear()
            raise
        elapsed = time.monotonic() - task["startedAt"]
        self.renderer._execution_completed += 1
        if mutation and workflow_scope:
            self.renderer._mutated_scopes.add(workflow_scope)
        if self.rich:
            self.live.stop()
            self.live = None
            self.console.print(
                self.renderer._execution_row(
                    "Succeeded", label, elapsed
                )
            )
            self.renderer._tasks.clear()
        else:
            self.console.print(
                f"[done] {label} · {elapsed:.1f}s",
                markup=False,
                style="satisfied",
            )
        return result
