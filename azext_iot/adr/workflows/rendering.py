# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import AbstractContextManager
from collections import Counter
import sys
import time
from typing import Any, Callable, Dict, Optional

from azure.cli.core.azclierror import AzCLIError
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from azext_iot.adr.providers.base import console as provider_console
from azext_iot.constants import VERSION


# ANSI palette names only: the terminal's own foreground/background stay in charge on dark and light themes.
_THEME = Theme(
    {
        "brand": "bold",
        "active": "blue",
        "satisfied": "green",
        "planned": "none",
        "manual": "yellow",
        "blocked": "red",
        "warning": "yellow",
        "muted": "dim",
        "body": "none",
    }
)
_SYMBOLS = {
    "Satisfied": ("✓", "[satisfied]", "satisfied"),
    "Succeeded": ("✓", "[done]", "satisfied"),
    "Planned": ("+", "[planned]", "planned"),
    "Manual": ("!", "[manual]", "manual"),
    "Blocked": ("✗", "[blocked]", "blocked"),
    "Failed": ("✗", "[failed]", "blocked"),
    "Warning": ("▲", "[warning]", "warning"),
    "NotConfigured": ("–", "[not configured]", "muted"),
}


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
        self._subscription_id = None
        self._body = []
        self._tasks = []
        self._account = {}
        self._hold_live = None
        self._busy = None
        self._printed_statuses = {}
        self._plan_actions = 0
        self._execution_started = None
        self._execution_completed = 0
        self._execution_total = 0
        self._failure: Optional[Dict[str, Any]] = None

    def busy(self, message: str):
        if not self.rich:
            self.console.print(
                f"[working] {message}", markup=False, style="active"
            )
            return
        self._busy = message
        if self._hold_live:
            self._hold_live.update(self._workspace(), refresh=True)
            return
        self._hold_live = Live(
            self._workspace(),
            console=self.console,
            transient=True,
            auto_refresh=False,
        )
        self._hold_live.start(refresh=True)

    def header(
        self,
        subscription_id: str,
        resource_group_name: Optional[str],
        namespace_name: Optional[str],
    ):
        self._subscription_id = subscription_id
        if self.command_name == "Namespace check":
            self.console.print(
                f"Namespace: {namespace_name} · Resource group: {resource_group_name}",
                markup=False, style="body", soft_wrap=True,
            )
            self.console.print(
                f"Subscription: {subscription_id}",
                markup=False, style="muted", soft_wrap=True,
            )
            return
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
            "\nUnattended: plans first and applies only with --yes. "
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

    def phase(self, name: str):
        if self._phase == name:
            return
        self._stop_hold()
        self._phase = name
        self._body.clear()
        self._busy = None

    def input_status(
        self,
        label: str,
        value: str,
        state: str,
        message: str = "",
    ):
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

    def plan(self, plan: Dict[str, Any]):
        self._plan_actions = sum(
            item.get("state") in {"Planned", "Manual"}
            for item in plan.get("items", [])
        )
        self._stop_hold()
        self.console.print()
        self._print_plan_header("awaiting confirmation")
        for item in plan.get("items", []):
            self.console.print(self._plan_row(item), soft_wrap=True)

    def confirmed(self):
        self._body.clear()
        self._stop_hold()
        self.console.print()
        self._print_plan_header("confirmed")

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
        if self.command_name == "Namespace check":
            self._check_receipt(result)
            return
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

    def _check_receipt(self, result):
        self._stop_hold()
        state = result.get("state", "Unknown")
        items = result.get("items", [])
        failed = state in {"Blocked", "Failed"}
        counts = Counter(item.get("state", "Unknown") for item in items)
        if not self.rich:
            lines = [
                f"Namespace check: {state}",
                f"Namespace: {result.get('namespace')}",
                f"Exit: {int(failed)} · 0 writes",
            ]
            for item in items:
                target = str(item.get("target", ""))
                role = (item.get("details") or {}).get("role")
                if role:
                    target += " · " + str(role)
                lines.append(
                    f"[{item.get('state')}] {item.get('id', '')} "
                    f"{target}: {item.get('message') or item.get('state')}"
                )
            lines.extend(
                f"Suggested only [{self._check_command_label(item['command'])}]: {item['command']}"
                for item in items if item.get("command")
            )
            self.console.print("\n".join(lines), markup=False, highlight=False, soft_wrap=True)
            return
        verdict = Text()
        verdict.append(
            "✗ " + state if failed else "✓ Ready" if state == "Succeeded" else "▲ " + state,
            "bold blocked" if failed else "bold body" if state == "Succeeded" else "bold warning",
        )
        verdict.append(f"  exit {int(failed)}", "muted")
        for name, count in counts.items():
            verdict.append(" · ", "muted")
            verdict.append(str(count), "bold body")
            verdict.append(" " + name, "muted")
        verdict.append(" · 0 writes", "muted")
        self.console.print()
        self.console.print(verdict)
        groups = {}
        for item in items:
            item_id = str(item.get("id", ""))
            phase = (
                "ACCESS" if (item.get("details") or {}).get("role") or item_id.startswith("role-")
                else "LINKS" if "link" in item_id else "RESOURCES"
            )
            groups.setdefault(phase, []).append(item)
        for phase, findings in groups.items():
            self.console.print("\n" + phase, style="muted")
            table = Table.grid(padding=(0, 1), expand=False)
            table.add_column(width=1)
            table.add_column(width=13)
            table.add_column(width=35 if self.content_width >= 96 else 24, overflow="fold")
            table.add_column(overflow="fold")
            for item in findings:
                status = item.get("state", "Unknown")
                symbol, _plain, style = _SYMBOLS.get(status, ("·", "", "muted"))
                detail = Text(str(item.get("target", "")), style="body", overflow="fold")
                role = (item.get("details") or {}).get("role")
                if role:
                    detail.append(" · " + str(role), "body")
                if item.get("message"):
                    detail.append(" · " + item["message"], "muted")
                if item.get("command"):
                    detail.append("  › fix below", "active")
                table.add_row(
                    Text(symbol, style), Text(status, style),
                    Text(str(item.get("id", "")), "body", overflow="fold"), detail,
                )
            self.console.print(table)
        remediations = [item for item in items if item.get("command")]
        if remediations:
            self.console.print("\nSUGGESTED COMMANDS", style="muted")
            self.console.print("Not executed by check. Review the target and permissions first.", style="muted")
            for item in remediations:
                label = self._check_command_label(item["command"])
                line = Text(f"[{label}] ", style="bold warning" if label == "WRITE" else "active")
                line.append(str(item["command"]), "body")
                self.console.print(line)

    @staticmethod
    def _check_command_label(command):
        prefix = command.split(" -", 1)[0].split()
        return "read-only" if prefix and prefix[-1] in {"show", "list", "check", "wait"} else "WRITE"

    def error(self, error: Exception, result: Optional[Dict[str, Any]] = None):
        self._stop_hold()
        if self.command_name == "Namespace check":
            if result:
                self._check_receipt(result)
            else:
                self.console.print(
                    Text("✗ Check failed  · exit 1 · 0 writes", "bold blocked")
                    if self.rich else "Namespace check failed · exit 1 · 0 writes"
                )
                original = error.error if isinstance(error, RenderedWorkflowError) else error
                self.console.print(str(original), markup=False, soft_wrap=True)
                for line in self._failure_metadata(original):
                    self.console.print(line, markup=False, soft_wrap=True)
            return
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
        service_error = getattr(error, "error", None)
        code = (
            getattr(error, "error_code", None)
            or getattr(error, "code", None)
            or (
                service_error.get("code")
                if isinstance(service_error, dict)
                else getattr(service_error, "code", None)
            )
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

    def execution(self):
        return WorkflowExecution(self)

    def close(self):
        self._stop_hold()

    def _print_summary(
        self,
        label: str,
        value: str,
        detail: str = "",
        state: str = "Satisfied",
    ):
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

    def _stop_hold(self):
        if not self._hold_live:
            return
        self._hold_live.stop()
        self._hold_live = None

    def _workspace(self):
        """Transient view of the current read or Azure operation; final results are printed, not held."""
        content = Text()
        if self._tasks:
            active = self._tasks[-1]
            total = max(
                self._execution_total,
                self._execution_completed + 1,
            )
            content.append("Applying", style="brand")
            content.append(
                f"  {self._execution_completed}/{total}"
                f" · {time.monotonic() - self._execution_started:.1f}s",
                style="muted",
            )
            content.append("\n")
            content.append("⠋ ", style="active")
            content.append(str(active["target"]), style="body")

        if self._busy:
            if content:
                content.append("\n\n")
            content.append("⠋ ", style="active")
            content.append(self._busy, style="body")
        return content

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
                self.renderer._workspace(),
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
