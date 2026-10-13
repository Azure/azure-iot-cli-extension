# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError
from rich.console import Console

from azext_iot.adr.workflows import rendering as subject
from azext_iot.adr.workflows.models import EndpointSpec, SetupRequest


def _console(stream, force_terminal=False):
    return Console(
        file=stream,
        force_terminal=force_terminal,
        color_system="standard" if force_terminal else None,
        theme=subject._THEME,
        width=100,
    )


def _plain_terminal(stream):
    return subject.Text.from_ansi(stream.getvalue()).plain


def _request():
    return SetupRequest(
        "ns",
        "rg",
        outbound_identity_type="SystemAssigned",
        dps=EndpointSpec(
            "dps", "primary", "/subscriptions/s/dps", "system-assigned"
        ),
        hubs=(
            EndpointSpec(
                "hub",
                "primary",
                "/subscriptions/s/hub",
                "user-assigned",
                "/subscriptions/s/uami",
            ),
        ),
    )


def _plan():
    return {
        "state": "Planned",
        "summary": {
            "Satisfied": 1,
            "Planned": 2,
            "Manual": 1,
            "Blocked": 1,
        },
        "items": [
            {
                "id": "namespace",
                "state": "Planned",
                "action": "create",
                "target": "ns",
                "details": {"location": "eastus"},
            },
            {
                "id": "resource-hub-primary",
                "state": "Planned",
                "action": "validate",
                "target": "hub",
                "message": "exact GET",
            },
            {
                "id": "role-hub-namespace-access",
                "state": "Manual",
                "action": "grant",
                "target": "/hub",
                "command": "az role assignment create",
                "details": {
                    "principalId": "principal",
                    "role": "Contributor",
                },
            },
            {
                "id": "link-hub-primary",
                "state": "Blocked",
                "action": "link",
                "target": "hub",
                "message": "missing role",
            },
            {
                "id": "unknown",
                "state": "Unknown",
                "action": "verify",
                "target": "hub",
            },
        ],
    }


@pytest.mark.parametrize("plain", [True, False])
@pytest.mark.parametrize("state", ["Succeeded", "Warning", "Blocked"])
def test_minimal_check_verdict_findings_and_unexecuted_remediation(plain, state):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace check", plain=plain, console=_console(stream, force_terminal=not plain),
    )
    renderer.header("sub", "rg", "ns")
    report = {
        "namespace": "ns", "state": state, "items": [
            {"id": "namespace", "state": "Satisfied", "target": "ns", "message": "Provisioned"},
            {"id": "role-hub", "state": "Blocked", "target": "hub", "details": {"role": "IoT Hub Data Contributor"},
             "message": "Grant missing", "command": "az role assignment create --role Contributor"},
            {"id": "hub-link", "state": "Warning", "target": "hub", "message": "Accepted",
             "command": "az iot adr ns link hub show -n west --ns ns -g rg"},
            {"id": "dps-links", "state": "NotConfigured", "target": "DPS"},
        ],
    }
    if state == "Blocked":
        renderer.error(ValueError("blocked"), report)
    else:
        renderer.receipt(report)
    output = _plain_terminal(stream)
    assert "0 writes" in output
    assert "Grant missing" in output and "Accepted" in output
    assert "[WRITE]" in output and "[read-only]" in output
    assert "az role assignment create" in output
    assert "Applying" not in output and "confirm the plan" not in output
    assert "kept" not in output
    assert "step " not in output and "❯" not in output and "▌" not in output
    assert "Namespace: ns" in output and "Resource group: rg" in output and "Subscription: sub" in output
    if not plain:
        assert "RESOURCES" in output and "ACCESS" in output and "LINKS" in output
        assert "Contributor" in output
    else:
        assert "\x1b" not in stream.getvalue()
        assert "hub · IoT Hub Data Contributor: Grant missing" in output


def test_check_result_and_failure_never_open_interactive_ui(mocker):
    stream = StringIO()
    live = mocker.patch.object(subject, "Live")
    renderer = subject.WorkflowRenderer("Namespace check", console=_console(stream, force_terminal=True))
    renderer.receipt({"namespace": "ns", "state": "Succeeded", "items": []})
    renderer.error(RuntimeError("Denied"))
    output = _plain_terminal(stream)
    assert "Ready" in output and "Check failed" in output and "Denied" in output
    assert "Applying" not in output and "0 writes" in output
    assert renderer._hold_live is None
    live.assert_not_called()
    assert subject.WorkflowRenderer._check_command_label("") == "WRITE"


@pytest.mark.parametrize("plain", [True, False])
@pytest.mark.parametrize("wrapped", [True, False])
def test_check_preserves_service_error_code_and_status(plain, wrapped):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace check", plain=plain, console=_console(stream, force_terminal=not plain),
    )
    response = MagicMock(status_code=403, reason="Forbidden")
    response.json.return_value = {"error": {"code": "AuthorizationFailed", "message": "Request denied"}}
    response.text.return_value = '{"error": {"code": "AuthorizationFailed", "message": "Request denied"}}'
    error = HttpResponseError(message="Request denied", response=response)
    renderer.error(subject.RenderedWorkflowError(error, renderer) if wrapped else error)
    output = _plain_terminal(stream)
    assert "status        403" in output
    assert "code          AuthorizationFailed" in output
    assert "Request denied" in output and "0 writes" in output
    assert "Applying" not in output and "kept" not in output


def test_failure_metadata_preserves_nested_mapping_code():
    error = RuntimeError("Request denied")
    error.error = {"code": "AuthorizationFailed"}
    error.response = SimpleNamespace(status_code=403)
    assert subject.WorkflowRenderer._failure_metadata(error) == [
        "code          AuthorizationFailed", "status        403",
    ]


def test_plain_check_keeps_long_suggested_commands_on_one_line():
    stream = StringIO()
    renderer = subject.WorkflowRenderer("Namespace check", plain=True, console=Console(file=stream, width=40))
    command = "az role assignment create --role Contributor --scope /subscriptions/sub/resourceGroups/long-group"
    renderer.receipt({"namespace": "ns", "state": "Blocked", "items": [
        {"id": "role", "state": "Blocked", "target": "scope", "command": command},
    ]})
    assert f"Suggested only [WRITE]: {command}" in stream.getvalue().splitlines()


def test_check_keeps_complete_target_scope_at_eighty_columns():
    stream = StringIO()
    target = (
        "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/another-group/"
        "providers/Microsoft.Devices/IotHubs/complete-target-name"
    )
    renderer = subject.WorkflowRenderer(
        "Namespace check",
        console=Console(file=stream, force_terminal=True, width=80, theme=subject._THEME),
    )
    renderer.receipt({
        "namespace": "ns", "state": "Blocked",
        "items": [{"id": "role-hub", "state": "Blocked", "target": target,
                   "details": {"role": "Contributor"}, "message": "Required grant missing"}],
    })
    assert target in "".join(_plain_terminal(stream).split())
    assert "Required grant missing" in _plain_terminal(stream)


@pytest.mark.parametrize("width", [80, 120])
def test_check_keeps_complete_finding_identifiers(width):
    stream = StringIO()
    console = Console(file=stream, force_terminal=True, width=width, theme=subject._THEME)
    renderer = subject.WorkflowRenderer("Namespace check", console=console)
    names = [
        "namespace-outbound-identity",
        "role-hub-west-namespace-iot-hub-data-contributor",
        "role-hub-west-namespace-contributor",
    ]
    renderer.receipt({
        "namespace": "ns", "state": "Blocked",
        "items": [{"id": name, "state": "Blocked", "target": ""} for name in names],
    })
    output = _plain_terminal(stream)
    for name in names:
        assert name in "".join(output.split())
    assert "…" not in output


def test_plain_renderer_outputs_all_views():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(stream),
    )
    renderer.busy("validating")
    renderer.header("sub", "rg", "ns")
    renderer.phase("Prepare")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    renderer.phase("Prepare")
    renderer.phase("Resources")
    renderer.input_status("Resource group", "rg", "Satisfied", "Found")
    renderer.plan(_plan())
    renderer.confirmed()
    renderer.receipt({
        "namespace": "ns",
        "state": "Succeeded",
        "summary": {"Succeeded": 2},
    })
    renderer.error(RuntimeError("failed"), _plan())
    output = _plain_terminal(stream)
    assert "Azure IoT · Device Registry" in output
    assert "step " not in output  # unattended runs have no steps to navigate
    assert "✓ subscription" in output
    assert "create      namespace" in output
    assert "location" in output
    assert "link        hub link" in output
    assert "[working] validating" in output
    assert "confirmed" in output
    assert "Namespace setup complete" in output
    assert "Fix: az role assignment create" in output


def test_plain_execution_reports_success_and_failure():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(stream),
    )
    original_quiet = subject.provider_console.quiet
    with renderer.execution() as execution:
        assert subject.provider_console.quiet is True
        assert execution.run("Successful", lambda: "result") == "result"
        with pytest.raises(RuntimeError, match="boom"):
            execution.run(
                "Failed", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
    assert subject.provider_console.quiet is original_quiet
    output = _plain_terminal(stream)
    assert "[running] Successful" in output
    assert "[done] Successful" in output
    assert "[failed] Failed" in output


def test_rich_execution_and_symbols():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    assert renderer.rich
    renderer.header("sub", "rg", "ns")
    renderer.phase("Prepare")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    renderer.phase("Resources")
    renderer.plan(_plan())
    renderer.confirmed()
    renderer.receipt({
        "namespace": "ns",
        "state": "Warning",
        "summary": {"Warning": 1},
    })
    renderer.error(RuntimeError("failed"), _plan())
    with renderer.execution() as execution:
        assert execution.run("Successful", lambda: 1) == 1
        with pytest.raises(ValueError):
            execution.run(
                "Failed", lambda: (_ for _ in ()).throw(ValueError("bad"))
            )
    output = _plain_terminal(stream)
    assert "✓" in output
    assert "Successful" in output
    assert "Failed" in output
    assert "step " not in output


def test_rich_renderer_escapes_dynamic_markup():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.input_status(
        "IoT Hub",
        "hub[value]",
        "Blocked",
        "bad [/]",
    )
    output = stream.getvalue()
    assert "[value]" in output
    assert "[/]" in output


def test_busy_status_is_transient_and_history_is_append_only():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.phase("Resource group")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.busy("validating resource group…")
    workspace = renderer._workspace()
    output = workspace.plain
    assert "⠋ validating resource group" in output
    history = _plain_terminal(stream)
    assert "✓ subscription      sub · Found" in history
    assert "step " not in history and "○" not in history
    offset = output.index("⠋")
    assert any(
        span.start <= offset < span.end and span.style == "active"
        for span in workspace.spans
    )
    # Unattended runs have no keys to advertise.
    assert ":back" not in output and ":quit" not in output
    renderer.close()
    assert renderer._hold_live is None


def test_summary_deduplicates_and_marks_staged_input():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.input_status(
        "Namespace", "new", "Planned", "Will be created"
    )
    renderer.input_status(
        "Namespace", "new", "Planned", "Will be created"
    )
    renderer.input_status("Other", "value", "Planned")
    output = _plain_terminal(stream)
    assert output.count("namespace         new") == 1
    assert "Will be created · nothing written yet" in output
    assert "other             value · nothing written yet" in output


def test_plain_renderer_close_is_noop():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    renderer.close()


def test_workspace_plan_is_bounded():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.phase("Review")
    plan = {
        "summary": {"Planned": 10},
        "items": [
            {
                "state": "Planned",
                "action": "create",
                "target": f"item-{index}",
            }
            for index in range(10)
        ],
    }
    renderer.plan(plan)
    output = stream.getvalue()
    assert "╭" not in output
    assert "item-7" in output
    assert "item-9" in output
    assert "10 actions · awaiting confirmation" in output


def test_dense_plan_tags_confirmation_and_elapsed():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    plan = {
        "summary": {"Planned": 1},
        "items": [{
            "id": "namespace",
            "state": "Planned",
            "action": "create",
            "target": "factory",
            "details": {
                "location": "eastus",
                "tags": {"env": "prod", "team": "devices"},
            },
        }],
    }
    renderer.plan(plan)
    renderer.confirmed()
    renderer._execution_started = subject.time.monotonic() - 2
    renderer.receipt({
        "namespace": "factory",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Succeeded": 1},
        "items": [],
    })
    output = _plain_terminal(stream)
    assert "create      namespace" in output
    assert "tags" in output
    assert "env=prod, team=devices" in output
    assert "1 actions · awaiting confirmation" in output
    assert "1 actions · confirmed" in output
    assert "Elapsed:" in output


@pytest.mark.parametrize(
    "item_id, subject_name",
    [
        ("namespace-outbound-identity", "outbound identity"),
        ("namespace-tags", "namespace tags"),
        ("resource-hub-main", "target resource"),
        ("link-hub-main", "hub link"),
        ("role-hub-main", "access"),
        ("skip-dps", "target"),
        ("namespace-status", "namespace status"),
        ("other", "target"),
    ],
)
def test_dense_plan_column_mapping(item_id, subject_name):
    _, actual_subject, _ = subject.WorkflowRenderer._plan_columns({
        "id": item_id,
        "state": "Planned",
        "action": "configure",
        "target": "target",
        "details": {"identityType": "SystemAssigned"},
    })
    assert actual_subject == subject_name


def test_structured_failure_metadata_and_partial_count():
    class ServiceError(RuntimeError):
        error_code = "AuthorizationFailed"
        status_code = 403
        retry_count = 3

    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer._plan_actions = 5
    renderer.error(
        ServiceError("access denied"),
        {
            "items": [
                {"state": "Succeeded", "target": f"kept-{index}"}
                for index in range(4)
            ] + [{"state": "Failed", "target": "access"}],
        },
    )
    output = _plain_terminal(stream)
    assert "1 of 5 actions failed · 4 of 5 kept" in output
    assert "code          AuthorizationFailed" in output
    assert "status        403" in output
    assert "retries       3" in output


def test_failure_includes_step_elapsed_and_response_status():
    error = RuntimeError("failed")
    error.response = MagicMock(status_code=429)
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer._failure = {
        "label": "Configure access",
        "elapsed": 1.25,
        "error": error,
    }
    renderer.error(error)
    output = _plain_terminal(stream)
    assert "step          Configure access" in output
    assert "elapsed       1.2s" in output
    assert "status        429" in output


def test_active_workspace_variants():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer._tasks[:] = [{"target": "task"}]
    renderer._execution_started = subject.time.monotonic()
    renderer._execution_total = 2
    renderer._execution_completed = 1
    renderer._busy = "busy"
    output = renderer._workspace().plain
    assert output.startswith("Applying  1/2 · ")
    assert "⠋ task\n\n⠋ busy" in output


def test_repeated_busy_updates_one_transient_line_and_quiet_details():
    stream = StringIO()
    renderer = subject.WorkflowRenderer("Namespace setup", console=_console(stream, force_terminal=True))
    renderer.busy("reading DPS…")
    live = renderer._hold_live
    renderer.busy("reading IoT Hub…")
    assert renderer._hold_live is live and "⠋ reading IoT Hub…" in renderer._workspace().plain
    renderer.close()
    renderer.account({"subscriptionId": "sub"})  # no user name: nothing to show
    renderer.receipt({"namespace": "ns", "state": "Succeeded", "items": [
        {"state": "Manual", "action": "assign", "target": "role"}]})
    output = _plain_terminal(stream)
    assert "✓ account" not in output and "Manual: Assign role\nResume:" in output


def test_check_reports_access_without_setup_approval_language():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(stream, force_terminal=True),
    )
    report = {
        "state": "Warning",
        "items": [{
            "state": "Manual",
            "action": "grant",
            "target": "/scope",
            "details": {"role": "Contributor"},
        }],
    }
    renderer.receipt(report)
    output = _plain_terminal(stream)
    assert "resolved at apply" not in output
    assert "0 writes" in output
    assert "Contributor" in output


def test_execution_exit_stops_active_live():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    execution = subject.WorkflowExecution(renderer)
    live = MagicMock()
    execution.live = live
    assert not execution.__exit__(None, None, None)
    live.stop.assert_called_once()


def test_failure_scope_and_retry_timing_are_cumulative(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    execution = subject.WorkflowExecution(renderer)

    clock = mocker.patch.object(
        subject.time, "monotonic", side_effect=[10.0, 20.0]
    )
    execution.__enter__()  # pylint: disable=unnecessary-dunder-call
    renderer._execution_completed = 4
    execution.__enter__()  # pylint: disable=unnecessary-dunder-call
    assert renderer._execution_started == 10.0
    assert renderer._execution_completed == 0
    assert clock.call_count == 1


def test_execution_records_explicit_failure_scope():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    execution = subject.WorkflowExecution(renderer)
    with pytest.raises(RuntimeError):
        execution.run(
            "Wait for updates",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
            workflow_scope="software-updates",
        )
    assert renderer._failure["scope"] == "software-updates"


@pytest.mark.parametrize("rich", [False, True])
def test_execution_suppresses_expected_branch_failure(mocker, rich):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=not rich,
        console=_console(stream, force_terminal=rich),
    )
    assert renderer.rich is rich
    error = ValueError("missing")
    handled_error = mocker.Mock(return_value=True)
    stops = []

    def find_resource():
        if rich:
            stops.append(mocker.spy(execution.live, "stop"))
        raise error

    original_quiet = subject.provider_console.quiet
    with renderer.execution() as execution:
        with pytest.raises(ValueError) as raised:
            execution.run(
                "Find optional resource", find_resource,
                workflow_scope="software-updates", handled_error=handled_error,
            )
        assert raised.value is error
        assert execution.live is None
        assert not renderer._tasks
        assert renderer._execution_completed == 0
    assert renderer._failure is None
    assert subject.provider_console.quiet is original_quiet
    handled_error.assert_called_once_with(error)
    for stop in stops:
        stop.assert_called_once_with()
    assert "failed" not in _plain_terminal(stream).lower()


@pytest.mark.parametrize(
    "item_id, action, expected",
    [
        ("namespace", "reuse", "Use namespace"),
        (
            "namespace-outbound-identity",
            "configure",
            "Configure namespace outbound identity",
        ),
        (
            "resource-software-updates-main",
            "create",
            "Create Update Instance",
        ),
        (
            "resource-software-updates-main",
            "validate",
            "Validate Update Instance",
        ),
        ("resource-dps-main", "validate", "Validate DPS"),
        ("resource-hub-main", "validate", "Validate IoT Hub"),
        ("link-dps-main", "link", "Configure DPS link"),
        ("link-hub-main", "link", "Configure IoT Hub link"),
        (
            "link-software-updates-main",
            "link",
            "Configure Software Updates link",
        ),
        ("roles-hub-main", "grant", "Configure access"),
        ("hub-prerequisite", "validate", "Check Hub prerequisite"),
        ("skip-dps", "skip", "Skip target"),
        ("namespace-status", "check", "Check namespace status"),
        ("other", "update", "Update target"),
    ],
)
def test_workspace_plan_labels(item_id, action, expected):
    assert expected in subject.WorkflowRenderer._plan_label({
        "id": item_id,
        "action": action,
        "target": "target",
    })


def test_workspace_plan_details_and_empty_sections():
    item = {
        "id": "link-hub-main",
        "state": "Planned",
        "action": "link",
        "target": "main",
        "message": "needed",
        "details": {
            "resourceId": "/hub",
            "userAssignedIdentity": "/uami",
            "role": "Contributor",
            "principalId": "principal",
            "location": "eastus",
        },
    }
    details = subject.WorkflowRenderer._plan_details(item)
    assert details == [
        ("Target", "/hub"),
        ("Identity", "/uami"),
        ("Role", "Contributor"),
        ("Principal", "principal"),
        ("Location", "eastus"),
        ("Reason", "needed"),
    ]
    content = subject.WorkflowRenderer._plan_row(item)
    assert "hub link" in content.plain
    assert "principal" in content.plain

    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.account({
        "subscriptionId": "sub",
        "userName": "user@example.com",
        "tenantId": "tenant",
    })
    renderer.phase("Unknown")
    output = _plain_terminal(renderer.console.file)
    assert "user@example.com" in output
    assert renderer._account["subscriptionId"] == "sub"
    assert renderer._account["tenantId"] == "tenant"


def test_manual_receipt_includes_rbac_and_resume():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.header("sub", "rg", "ns")
    renderer.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Manual",
        "summary": {"Manual": 1},
        "items": [{
            "id": "role-hub",
            "state": "Manual",
            "action": "grant",
            "target": "/hub",
            "command": "az role assignment create",
        }],
        "receipt": "/tmp/receipt.json",
    })
    output = stream.getvalue()
    assert "az role assignment create" in output
    assert "Resume: az iot adr ns setup" in output
    assert "Receipt: /tmp/receipt.json" in output


def test_receipts_render_check_and_link_details():
    check_stream = StringIO()
    check = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(check_stream, force_terminal=True),
    )
    check.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Satisfied": 1},
        "items": [{
            "state": "Satisfied",
            "target": "namespace",
            "message": "ready",
        }],
    })
    assert "namespace · ready" in _plain_terminal(check_stream)

    setup_stream = StringIO()
    setup = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(setup_stream, force_terminal=True),
    )
    setup.header("sub", "rg", "ns")
    setup.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Succeeded": 1},
        "items": [{
            "id": "link-hub-main",
            "state": "Succeeded",
            "action": "link",
            "target": "main",
            "details": {"principalId": "principal"},
        }],
    })
    output = setup_stream.getvalue()
    assert "Configure IoT Hub link: main" in output
    assert "Identity principal: principal" in output
    assert "Resource ID:" in output

    error_stream = StringIO()
    error_renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(error_stream, force_terminal=True),
    )
    error_renderer.error(
        RuntimeError("failed"),
        {
            "receipt": "/tmp/failure.json",
            "receiptError": "secondary write failed",
            "items": [{
                "state": "Succeeded",
                "target": "namespace",
            }],
        },
    )
    error_output = error_stream.getvalue()
    assert "1 of 2 kept" in error_output
    assert "Receipt: /tmp/failure.json" in error_output
    assert "Receipt write failed: secondary write failed" in error_output


def test_plain_account_summary():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup", plain=True, console=_console(stream)
    )
    renderer.account({
        "userName": "user@example.com",
        "tenantId": "tenant",
    })
    output = stream.getvalue()
    assert "account" in output
    assert "user@example.com · tenant" in output


def test_renderer_creates_default_console():
    renderer = subject.WorkflowRenderer("Namespace check", plain=True)
    assert renderer.console


def test_redirected_stdin_disables_rich(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=False)
    renderer = subject.WorkflowRenderer("Namespace check")
    assert not renderer.rich
