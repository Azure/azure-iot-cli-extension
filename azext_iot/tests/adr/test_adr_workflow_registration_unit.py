# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# pylint: disable=no-member

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from knack.help_files import helps

from azext_iot.adr.workflows import commands as command_subject
from azext_iot.adr.workflows.command_map import load_adr_workflow_commands
from azext_iot.adr.workflows.help import load_adr_workflow_help
from azext_iot.adr.workflows.models import WorkflowExecutionError
from azext_iot.adr.workflows.params import load_adr_workflow_arguments


class _CommandGroup:
    def __init__(self, name, records):
        self.name = name
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def command(self, name, operation, **kwargs):
        self.records.append((self.name, name, operation, kwargs))


class _CommandLoader:
    def __init__(self):
        self.records = []
        self.groups = []

    def command_group(self, name, **kwargs):
        self.groups.append((name, kwargs))
        return _CommandGroup(name, self.records)


class _ArgumentContext:
    def __init__(self, name, records):
        self.name = name
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def argument(self, name, **kwargs):
        self.records.setdefault(self.name, {})[name] = kwargs


class _ArgumentLoader:
    def __init__(self):
        self.cli_ctx = MagicMock()
        self.records = {}

    def argument_context(self, name):
        return _ArgumentContext(name, self.records)


def test_workflow_registration_is_separate_and_preview():
    loader = _CommandLoader()
    load_adr_workflow_commands(loader, None)
    assert loader.records == [
        ("iot adr ns", "check", "adr_namespace_check", {}),
        ("iot adr ns", "setup", "adr_namespace_setup", {}),
    ]
    assert loader.groups[0][1]["is_preview"] is True


def test_workflow_arguments_are_registered():
    loader = _ArgumentLoader()
    load_adr_workflow_arguments(loader, None)
    assert {"namespace_name", "resource_group_name"} <= set(
        loader.records["iot adr ns check"]
    )
    assert {"no_input", "plain"} <= set(
        loader.records["iot adr ns check"]
    )
    assert loader.records["iot adr ns check"]["namespace_name"]["required"]
    assert loader.records["iot adr ns check"]["resource_group_name"]["required"]
    assert "tags" in loader.records["iot adr ns setup"]
    setup = loader.records["iot adr ns setup"]
    assert not setup["namespace_name"]["required"]
    assert not setup["resource_group_name"]["required"]
    assert {
        "namespace_outbound_identity",
        "dps",
        "hubs",
        "software_updates",
        "plan_only",
        "yes",
    } <= set(setup)
    assert setup["hubs"]["action"] == "append"
    assert setup["namespace_outbound_identity"]["options_list"][0] == (
        "--outbound-identity"
    )
    assert "--su" in setup["software_updates"]["options_list"]
    assert "--complete" in setup["complete_connectivity"]["options_list"]


def test_workflow_help_is_valid_yaml():
    load_adr_workflow_help()
    for command in ("iot adr ns check", "iot adr ns setup"):
        assert isinstance(yaml.safe_load(helps[command]), dict)
    check = yaml.safe_load(helps["iot adr ns check"])
    assert "never prompts" in check["long-summary"]
    assert all("-n " in example["text"] and "-g " in example["text"] for example in check["examples"])


def _cmd():
    return SimpleNamespace(
        cli_ctx=SimpleNamespace(
            data={"subscription_id": "sub"},
            cloud=SimpleNamespace(
                endpoints=SimpleNamespace(
                    resource_manager="https://management.azure.com"
                )
            ),
        )
    )


def _workflow_mocks(mocker):
    workflow = mocker.patch.object(
        command_subject, "NamespaceWorkflow"
    ).return_value
    services = mocker.patch.object(
        command_subject, "WorkflowServices"
    ).return_value
    services.account_context.return_value = {"subscriptionId": "sub"}
    mocker.patch.object(
        command_subject,
        "write_receipt_file",
        return_value="/tmp/receipt.json",
    )
    mocker.patch.object(
        command_subject, "get_subscription_id", return_value="sub"
    )
    renderer = mocker.patch.object(
        command_subject, "WorkflowRenderer"
    ).return_value
    renderer.execution.return_value.__enter__.return_value = MagicMock()
    return workflow, renderer


def test_progressive_resource_validators(mocker):
    services = MagicMock()
    renderer = MagicMock()
    services.show_subscription.return_value = {"id": "sub"}
    command_subject._validate_subscription(services, renderer, "sub")
    services.show_subscription.return_value = None
    with pytest.raises(ResourceNotFoundError, match="Subscription"):
        command_subject._validate_subscription(services, renderer, "sub")

    services.show_resource_group.return_value = {"name": "rg"}
    command_subject._validate_resource_group(services, renderer, "rg")
    services.show_resource_group.return_value = None
    with pytest.raises(ResourceNotFoundError, match="Resource group"):
        command_subject._validate_resource_group(services, renderer, "rg")

    services.show_namespace.return_value = {
        "name": "ns", "location": "eastus",
        "properties": {"provisioningState": "Succeeded"},
        "systemData": {"createdBy": "me"},
    }
    command_subject._validate_namespace(services, renderer, "ns", "rg")
    renderer.input_status.assert_called_with(
        "Namespace", "ns", "Satisfied", "Found · eastus · Succeeded · me"
    )
    services.show_namespace.return_value = None
    command_subject._validate_namespace(services, renderer, "new-ns", "rg")
    renderer.input_status.assert_called_with(
        "Namespace", "new-ns", "Planned", "Not found; setup will create it."
    )

    endpoint = SimpleNamespace(
        kind="hub",
        endpoint_name="hub",
        resource_id="/hub",
        identity_type="system-assigned",
        user_assigned_identity=None,
    )
    services.resolve_resource.return_value = {"id": "/hub"}
    resource = command_subject._validate_endpoint_resource(
        services, renderer, endpoint, False
    )
    command_subject._validate_endpoint_identity(
        services, renderer, endpoint, resource
    )
    services.principal_for_identity.assert_called_once_with(
        "system-assigned", None, {"id": "/hub"}
    )

    services.resolve_uami.return_value = {"id": "/uami"}
    command_subject._validate_identity(
        services, renderer, "/uami"
    )
    services.resolve_uami.assert_called_once_with("/uami")

    assert "Found" in command_subject._resource_metadata({
        "properties": "invalid",
        "sku": "invalid",
    })


def test_structured_output_detection(mocker):
    stdout = MagicMock()
    stdout.isatty.return_value = True
    mocker.patch.object(command_subject.sys, "__stdout__", stdout)
    mocker.patch.object(
        command_subject.sys, "argv", ["az", "iot", "adr", "ns", "setup"]
    )
    assert not command_subject._structured_output_requested(_cmd())

    command_subject.sys.argv = ["az", "iot", "adr", "ns", "setup", "-o", "json"]
    assert command_subject._structured_output_requested(_cmd())
    command_subject.sys.argv = [
        "az", "iot", "adr", "ns", "setup", "--output=json"
    ]
    assert command_subject._structured_output_requested(_cmd())

    stdout.isatty.return_value = False
    command_subject.sys.argv = ["az", "iot", "adr", "ns", "setup"]
    assert command_subject._structured_output_requested(_cmd())


def test_persist_receipt_is_nonfatal(mocker):
    result = {"state": "Succeeded"}
    receipt = mocker.patch.object(
        command_subject,
        "write_receipt_file",
        side_effect=OSError("read only"),
    )
    assert command_subject._persist_receipt(result) == {
        "state": "Succeeded",
        "receiptError": "read only",
    }
    receipt.side_effect = None
    receipt.return_value = "/tmp/receipt.json"
    result = {"state": "Succeeded"}
    command_subject._persist_receipt(result)
    assert result["receipt"] == "/tmp/receipt.json"


def test_progressive_validator_allows_planned_update_instance(mocker):
    services = MagicMock()
    renderer = MagicMock()
    endpoint = SimpleNamespace(
        kind="software-updates",
        endpoint_name="updates",
        resource_id="/updates",
    )
    services.resolve_resource.side_effect = ResourceNotFoundError("missing")
    command_subject._validate_endpoint_resource(
        services, renderer, endpoint, True
    )
    services.validate_update_instance_creation.assert_called_once_with(endpoint)
    renderer.input_status.assert_called_once_with(
        "Update Instance",
        "/updates",
        "Planned",
        "Not found; setup will create it.",
    )
    with pytest.raises(ResourceNotFoundError):
        command_subject._validate_endpoint_resource(
            services, renderer, endpoint, False
        )


@pytest.mark.parametrize("state", ["Succeeded", "Warning"])
@pytest.mark.parametrize("no_input", [False, True])
def test_check_command_delegates_without_interaction(mocker, state, no_input):
    workflow, renderer = _workflow_mocks(mocker)
    scope = mocker.spy(
        command_subject,
        "resolve_scope_inputs",
    )
    workflow.check.return_value = {
        "state": state,
        "items": [],
        "summary": {},
    }
    mocker.patch.object(command_subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(command_subject.sys.stderr, "isatty", return_value=True)
    result = command_subject.adr_namespace_check(_cmd(), "ns", "rg", no_input=no_input)
    assert result is workflow.check.return_value
    workflow.check.assert_called_once_with(
        namespace_name="ns", resource_group_name="rg"
    )
    scope.assert_called_once_with("ns", "rg", subscription_id="sub")
    command_subject.NamespaceWorkflow.assert_called_once_with(
        command_subject.WorkflowServices.return_value,
    )
    assert not command_subject.WorkflowServices.return_value.method_calls
    renderer.header.assert_called_once_with("sub", "rg", "ns")
    renderer.receipt.assert_called_once_with(result)
    for method in ("account", "phase", "execution", "confirmed"):
        getattr(renderer, method).assert_not_called()


@pytest.mark.parametrize("scope", [(None, None), ("ns", None), (None, "rg"), (" ", "rg"), ("ns", " ")])
@pytest.mark.parametrize("interactive", [False, True])
def test_check_command_requires_scope_before_any_reads_or_prompts(mocker, scope, interactive):
    _workflow_mocks(mocker)
    mocker.patch.object(command_subject.sys.stdin, "isatty", return_value=interactive)
    mocker.patch.object(command_subject.sys.stderr, "isatty", return_value=interactive)
    with pytest.raises(ArgumentUsageError, match="Check never prompts"):
        command_subject.adr_namespace_check(_cmd(), *scope)
    command_subject.get_subscription_id.assert_not_called()
    command_subject.WorkflowRenderer.assert_not_called()
    command_subject.WorkflowServices.assert_not_called()
    command_subject.NamespaceWorkflow.assert_not_called()


def test_check_command_normalizes_resource_group_arm_id(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    workflow.check.return_value = {"state": "Succeeded", "items": []}
    command_subject.adr_namespace_check(
        _cmd(), " ns ", "/subscriptions/sub/resourceGroups/rg",
    )
    workflow.check.assert_called_once_with(namespace_name="ns", resource_group_name="rg")
    renderer.header.assert_called_once_with("sub", "rg", "ns")


def test_check_command_rejects_wrong_subscription_before_reads(mocker):
    _workflow_mocks(mocker)
    with pytest.raises(InvalidArgumentValueError, match="active subscription"):
        command_subject.adr_namespace_check(
            _cmd(), "ns", "/subscriptions/other/resourceGroups/rg",
        )
    command_subject.WorkflowRenderer.assert_not_called()
    command_subject.WorkflowServices.assert_not_called()


@pytest.mark.parametrize("provisioning_state, result_state", [
    ("Succeeded", "Succeeded"), ("Updating", "Warning"), ("Failed", "Blocked"),
])
def test_check_command_runs_real_diagnostics_without_scope_discovery(mocker, provisioning_state, result_state):
    mocker.patch.object(command_subject, "get_subscription_id", return_value="sub")
    services = mocker.patch.object(command_subject, "WorkflowServices").return_value
    namespace = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns",
        "name": "ns", "properties": {"provisioningState": provisioning_state},
    }
    services.show_namespace.return_value = namespace
    services.namespace_outbound_principal.return_value = "namespace-principal"
    renderer = mocker.patch.object(command_subject, "WorkflowRenderer").return_value
    if result_state == "Blocked":
        with pytest.raises(command_subject.RenderedWorkflowError) as raised:
            command_subject.adr_namespace_check(_cmd(), "ns", "rg")
        result = raised.value.result
    else:
        result = command_subject.adr_namespace_check(_cmd(), "ns", "rg")
        renderer.receipt.assert_called_once_with(result)
    assert result["state"] == result_state
    assert result["namespace"] == "ns" and result["resourceGroup"] == "rg"
    assert result["summary"]["NotConfigured"] == 3
    assert services.mock_calls == [
        mocker.call.show_namespace("ns", "rg"),
        mocker.call.namespace_outbound_principal(namespace),
    ]
    renderer.prompt.assert_not_called()
    renderer.execution.assert_not_called()


@pytest.mark.parametrize("state", ["Blocked", "Failed"])
def test_check_command_raises_for_blockers(mocker, state):
    workflow, renderer = _workflow_mocks(mocker)
    workflow.check.return_value = {
        "state": state,
        "items": [{
            "state": state,
            "target": "hub",
            "message": "missing role",
        }],
    }
    with pytest.raises(
        command_subject.RenderedWorkflowError,
        match="Namespace check found blockers",
    ) as raised:
        command_subject.adr_namespace_check(_cmd(), "ns", "rg")
    assert raised.value.result["items"][0]["target"] == "hub"
    raised.value.print_error()
    renderer.error.assert_called_once()


def test_check_command_renders_workflow_error(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    workflow.check.side_effect = RuntimeError("read failed")
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="read failed"
    ) as raised:
        command_subject.adr_namespace_check(_cmd(), "ns", "rg")
    raised.value.print_error()
    renderer.error.assert_called_once()


def test_setup_command_plan_only_and_script(mocker, tmp_path):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    items = [
        {"command": "az one", "state": "Planned", "action": "add"},
        {"command": "az skip", "state": "Satisfied", "action": "reuse"},
        {"command": None, "state": "Planned", "action": "role"},
    ]
    plan = {"state": "Planned", "items": items}
    workflow.plan_setup.return_value = (plan, [])
    output = tmp_path / "plan.sh"
    result = command_subject.adr_namespace_setup(
        _cmd(),
        "ns",
        "rg",
        plan_only=True,
        no_input=True,
        output_script=str(output),
    )
    assert result is plan
    assert "az one" in output.read_text(encoding="utf-8")
    assert "az skip" not in output.read_text(encoding="utf-8")
    workflow.setup.assert_not_called()


def test_setup_command_rejects_incomplete_script(mocker, tmp_path):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    item = {"command": "", "state": "Manual", "action": "add"}
    workflow.plan_setup.return_value = ({"state": "Manual", "items": [item]}, [])
    with pytest.raises(ArgumentUsageError, match="cannot be resolved"):
        command_subject.adr_namespace_setup(
            _cmd(),
            "ns",
            "rg",
            plan_only=True,
            no_input=True,
            output_script=str(tmp_path / "plan.sh"),
        )
    assert not (tmp_path / "plan.sh").exists()


def test_setup_command_renders_input_and_plan_errors(mocker):
    _, renderer = _workflow_mocks(mocker)
    builder = mocker.patch.object(
        command_subject,
        "build_setup_request",
        side_effect=InvalidArgumentValueError("invalid input"),
    )
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="invalid input"
    ) as raised:
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    raised.value.print_error()
    renderer.error.assert_called_once()

    request = SimpleNamespace(
        namespace_name="ns", resource_group_name="rg"
    )
    builder.side_effect = None
    builder.return_value = request
    workflow = command_subject.NamespaceWorkflow.return_value
    workflow.plan_setup.side_effect = RuntimeError("plan failed")
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="plan failed"
    ):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")


def test_setup_command_rejects_blocked_plan(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = (
        {"state": "Blocked", "items": [], "summary": {}},
        [],
    )
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="blocked"
    ) as raised:
        command_subject.adr_namespace_setup(
            _cmd(), "ns", "rg", yes=True
        )
    raised.value.print_error()
    renderer.error.assert_called_once()


def test_setup_command_confirmed(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = ({"state": "Planned"}, [])
    workflow.setup.return_value = {"state": "Succeeded"}
    result = command_subject.adr_namespace_setup(
        _cmd(), "ns", "rg", yes=True
    )
    assert result["state"] == "Succeeded"
    assert result["receipt"] == "/tmp/receipt.json"
    workflow.setup.assert_called_once()
    renderer.receipt.assert_called_once()


def test_setup_command_noninteractive_requires_yes(mocker):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = ({"state": "Planned"}, [])
    mocker.patch.object(command_subject.sys.stdin, "isatty", return_value=False)
    mocker.patch.object(command_subject.sys.stderr, "isatty", return_value=False)
    with pytest.raises(ArgumentUsageError, match="Pass --yes"):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")


def test_setup_command_renders_execution_error(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = RuntimeError("apply failed")
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="apply failed"
    ) as raised:
        command_subject.adr_namespace_setup(
            _cmd(), "ns", "rg", yes=True
        )
    raised.value.print_error()
    renderer.error.assert_called_once()


def test_setup_command_records_receipt_write_failure(mocker):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = RuntimeError("apply failed")
    command_subject.write_receipt_file.side_effect = OSError("disk full")
    with pytest.raises(
        command_subject.RenderedWorkflowError
    ) as raised:
        command_subject.adr_namespace_setup(
            _cmd(), "ns", "rg", yes=True
        )
    assert "receiptError" not in raised.value.result


def test_setup_command_raises_for_blocked_verification(mocker):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.return_value = {
        "state": "Blocked",
        "items": [],
        "summary": {},
    }
    with pytest.raises(
        command_subject.RenderedWorkflowError,
        match="readiness blockers",
    ) as raised:
        command_subject.adr_namespace_setup(
            _cmd(), "ns", "rg", yes=True
        )
    assert raised.value.result["receipt"] == "/tmp/receipt.json"


def _tty(mocker, stdin=True, stderr=True):
    mocker.patch.object(command_subject.sys.stdin, "isatty", return_value=stdin)
    mocker.patch.object(command_subject.sys.stderr, "isatty", return_value=stderr)


@pytest.mark.parametrize("state, plan_only, raises", [
    ("Succeeded", False, False),
    ("Planned", True, False),
    ("Blocked", True, False),
    ("Blocked", False, True),
    ("Failed", False, True),
    ("Stopped", False, True),
])
def test_setup_terminal_routes_to_guided_flow(mocker, state, plan_only, raises):
    _workflow_mocks(mocker)
    _tty(mocker)
    guided = mocker.patch("azext_iot.adr.workflows.guided.run_guided_setup", return_value={"state": state})
    if raises:
        with pytest.raises(command_subject.CLIError, match="Rerun setup"):
            command_subject.adr_namespace_setup(_cmd(), "ns", "rg", plan_only=plan_only, plain=True)
    else:
        assert command_subject.adr_namespace_setup(
            _cmd(), "ns", "rg", plan_only=plan_only, plain=True
        ) == {"state": state}
    args, kwargs = guided.call_args
    assert args == (command_subject.WorkflowServices.return_value, "sub")
    assert kwargs["plain"] is True and kwargs["plan_only"] is plan_only
    assert kwargs["config"] is None
    assert kwargs["persist"] is command_subject._persist_receipt
    assert kwargs["write_script"] is command_subject._write_plan_script
    assert kwargs["check_script"] is command_subject._check_plan_script
    assert kwargs["arguments"]["namespace_name"] == "ns"
    assert kwargs["arguments"]["resource_group_name"] == "rg"
    command_subject.WorkflowRenderer.assert_not_called()


def test_setup_guided_cancel_returns_none(mocker):
    _workflow_mocks(mocker)
    _tty(mocker)
    mocker.patch("azext_iot.adr.workflows.guided.run_guided_setup", return_value=None)
    assert command_subject.adr_namespace_setup(_cmd()) is None


def test_setup_guided_receives_validated_config(mocker):
    _workflow_mocks(mocker)
    _tty(mocker)
    loaded = {"namespace": {"name": "ns"}}
    load = mocker.patch("azext_iot.adr.workflows.configuration.load_config", return_value=loaded)
    guided = mocker.patch("azext_iot.adr.workflows.guided.run_guided_setup", return_value={"state": "Succeeded"})
    command_subject.adr_namespace_setup(_cmd(), config="@setup.json")
    load.assert_called_once_with("@setup.json")
    assert guided.call_args.kwargs["config"] is loaded


@pytest.mark.parametrize("flags, stdin, stderr", [
    ({"yes": True}, True, True),
    ({"no_input": True}, True, True),
    ({}, False, True),
    ({}, True, False),
])
def test_setup_unattended_never_enters_guided_flow(mocker, flags, stdin, stderr):
    workflow, _ = _workflow_mocks(mocker)
    _tty(mocker, stdin, stderr)
    guided = mocker.patch("azext_iot.adr.workflows.guided.run_guided_setup")
    mocker.patch.object(
        command_subject, "build_setup_request",
        return_value=SimpleNamespace(namespace_name="ns", resource_group_name="rg"),
    )
    workflow.plan_setup.return_value = ({"state": "Planned", "items": []}, [])
    workflow.setup.return_value = {"state": "Succeeded"}
    if flags.get("yes"):
        assert command_subject.adr_namespace_setup(_cmd(), "ns", "rg", **flags)["state"] == "Succeeded"
    else:
        with pytest.raises(ArgumentUsageError, match="Pass --yes"):
            command_subject.adr_namespace_setup(_cmd(), "ns", "rg", **flags)
        workflow.setup.assert_not_called()
    guided.assert_not_called()


def test_setup_unattended_requires_capabilities_without_creating_defaults(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    _tty(mocker, False, False)
    services = command_subject.WorkflowServices.return_value
    services.show_subscription.return_value = {"displayName": "Sub"}
    services.show_resource_group.return_value = {"name": "rg"}
    services.show_namespace.return_value = None
    with pytest.raises(command_subject.RenderedWorkflowError, match="--outbound-identity, --dps") as raised:
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg", yes=True)
    raised.value.print_error()
    renderer.error.assert_called_once()
    workflow.plan_setup.assert_not_called()
    workflow.setup.assert_not_called()


def test_setup_unattended_subscription_failure_is_rendered(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    services = command_subject.WorkflowServices.return_value
    services.show_subscription.return_value = None
    with pytest.raises(command_subject.RenderedWorkflowError, match="Subscription 'sub' was not found") as raised:
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg", yes=True)
    raised.value.print_error()
    renderer.error.assert_called_once_with(raised.value, None)
    workflow.plan_setup.assert_not_called()
    command_subject.write_receipt_file.assert_not_called()


def test_setup_unattended_failure_persists_partial_receipt(mocker):
    workflow, _ = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject, "build_setup_request",
        return_value=SimpleNamespace(namespace_name="ns", resource_group_name="rg"),
    )
    workflow.plan_setup.return_value = ({"state": "Planned", "items": []}, [])
    partial = {"state": "Failed", "items": [{"state": "Succeeded"}]}
    workflow.setup.side_effect = WorkflowExecutionError(RuntimeError("hub failed"), partial)
    with pytest.raises(command_subject.RenderedWorkflowError, match="hub failed") as raised:
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg", yes=True)
    assert raised.value.result is partial
    assert partial["receipt"] == "/tmp/receipt.json"
    assert partial["keptActions"] == 0


def test_setup_unattended_interrupt_reports_without_retry(mocker):
    workflow, _ = _workflow_mocks(mocker)
    plan = {"state": "Planned", "items": []}
    mocker.patch.object(
        command_subject, "build_setup_request",
        return_value=SimpleNamespace(namespace_name="ns", resource_group_name="rg"),
    )
    workflow.plan_setup.return_value = (plan, [])
    error = RuntimeError("interrupted")
    error.__cause__ = KeyboardInterrupt()
    workflow.setup.side_effect = error
    with pytest.raises(command_subject.RenderedWorkflowError) as raised:
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg", yes=True)
    assert raised.value.result is plan
    assert workflow.setup.call_count == 1
    command_subject.write_receipt_file.assert_not_called()


def test_write_plan_script_skips_roles_and_satisfied(tmp_path):
    path = tmp_path / "plan.sh"
    command_subject._write_plan_script(str(path), [
        {"action": "role", "state": "Planned"},
        {"action": "add", "state": "Manual", "command": "az manual"},
        {"action": "add", "state": "Satisfied", "command": "az done"},
    ])
    text = path.read_text(encoding="utf-8")
    assert "az manual" in text and "az done" not in text


def test_check_plan_script_renders_and_checks_destination_without_writing(tmp_path):
    path = tmp_path / "plan.sh"
    command_subject._check_plan_script(str(path), [{"action": "add", "state": "Planned", "command": "az add"}])
    assert not path.exists()
    with pytest.raises(command_subject.ArgumentUsageError, match="cannot be resolved yet"):
        command_subject._check_plan_script(str(path), [{"action": "create", "state": "Planned"}])
    with pytest.raises(command_subject.ArgumentUsageError, match="is a folder"):
        command_subject._check_plan_script(str(tmp_path), [])
