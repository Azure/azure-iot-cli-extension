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
from azext_iot.adr.workflows.models import (
    EndpointSpec,
    SetupRequest,
    WorkflowExecutionError,
)
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
    assert "tags" in loader.records["iot adr ns setup"]
    setup = loader.records["iot adr ns setup"]
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
    mocker.patch.object(
        command_subject,
        "_select_subscription",
        return_value=("sub", services),
    )
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
    renderer.action.return_value = "y"
    renderer.execution.return_value.__enter__.return_value = MagicMock()
    return workflow, renderer


def test_resource_choice_loading_clears_busy_state():
    renderer = MagicMock()

    assert command_subject._load_resource_choices(
        renderer, "namespaces", lambda: ["ns"]
    ) == ["ns"]
    renderer.busy.assert_called_once_with(
        "loading accessible namespaces…"
    )
    renderer.idle.assert_called_once_with()

    renderer.reset_mock()
    assert not command_subject._load_resource_choices(
        renderer, "namespaces", lambda: []
    )
    renderer.clear_search_context.assert_called_once_with()


def test_resource_choice_loading_clears_busy_state_on_error():
    renderer = MagicMock()

    with pytest.raises(RuntimeError, match="denied"):
        command_subject._load_resource_choices(
            renderer,
            "resource groups",
            lambda: (_ for _ in ()).throw(RuntimeError("denied")),
        )
    renderer.idle.assert_called_once_with()
    renderer.clear_search_context.assert_called_once_with()


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

    services.show_namespace.return_value = {"name": "ns"}
    command_subject._validate_namespace(
        services, renderer, "ns", "rg", False
    )
    services.show_namespace.return_value = None
    command_subject._validate_namespace(
        services, renderer, "new-ns", "rg", True
    )
    with pytest.raises(ResourceNotFoundError, match="Namespace"):
        command_subject._validate_namespace(
            services, renderer, "missing", "rg", False
        )

    endpoint = SimpleNamespace(
        kind="hub",
        endpoint_name="hub",
        resource_id="/hub",
        identity_type="system-assigned",
        user_assigned_identity=None,
    )
    services.resolve_resource.return_value = {"id": "/hub"}
    command_subject._validate_endpoint(
        services, renderer, endpoint, False
    )
    services.principal_for_identity.assert_called_once()

    services.resolve_uami.return_value = {"id": "/uami"}
    command_subject._validate_identity(
        services, renderer, "/uami"
    )
    services.resolve_uami.assert_called_once_with("/uami")

    services.show_namespace.return_value = {"name": "ns"}
    services.namespace_outbound_principal.return_value = "principal"
    assert command_subject._can_reuse_identity(services, "ns", "rg")
    services.namespace_outbound_principal.side_effect = (
        InvalidArgumentValueError("missing")
    )
    assert not command_subject._can_reuse_identity(
        services, "ns", "rg"
    )
    services.show_namespace.return_value = None
    assert not command_subject._can_reuse_identity(
        services, "ns", "rg"
    )

    assert "Found" in command_subject._resource_metadata({
        "properties": "invalid",
        "sku": "invalid",
    })


def test_missing_namespace_create_confirmation():
    services = MagicMock()
    renderer = MagicMock()
    services.show_namespace.return_value = None
    renderer.prompt.return_value = ""
    command_subject._validate_namespace(
        services, renderer, "new", "rg", True, confirm_create=True
    )
    renderer.prompt.assert_called_once()
    renderer.prompt.return_value = "n"
    with pytest.raises(command_subject.BackRequested):
        command_subject._validate_namespace(
            services,
            renderer,
            "new",
            "rg",
            True,
            confirm_create=True,
        )

    renderer.prompt.side_effect = ["invalid", "y"]
    command_subject._validate_namespace(
        services, renderer, "new", "rg", True, confirm_create=True
    )
    renderer.write.assert_called_with(
        "Enter y or n. Use :back, :help, or :quit."
    )


def test_subscription_selection_paths(mocker):
    cmd = _cmd()
    renderer = MagicMock()
    services = MagicMock()
    services.subscription_id = "sub"
    services.account_context.return_value = {
        "subscriptionId": "sub",
        "subscriptionName": "Default",
    }
    renderer.prompt.return_value = ""
    assert command_subject._select_subscription(
        cmd, renderer, services, True, True
    ) == ("sub", services)

    renderer.prompt.return_value = "n"
    services.list_subscriptions.return_value = [{
        "id": "other",
        "name": "Other",
        "state": "Enabled",
    }]
    mocker.patch.object(
        command_subject, "select_value", return_value="other"
    )
    replacement = MagicMock()
    replacement.account_context.return_value = {
        "subscriptionId": "other"
    }
    mocker.patch.object(
        command_subject, "WorkflowServices", return_value=replacement
    )
    selected, selected_services = command_subject._select_subscription(
        cmd, renderer, services, True, True
    )
    assert selected == "other"
    assert selected_services is replacement
    assert cmd.cli_ctx.data["subscription_id"] == "other"

    denied = MagicMock()
    denied.subscription_id = "sub"
    denied.account_context.return_value = {
        "subscriptionId": "sub",
        "subscriptionName": "Default",
    }
    denied.list_subscriptions.side_effect = RuntimeError("denied")
    denied.resolve_subscription.return_value = {
        "id": "exact-sub",
        "name": "Exact",
    }
    renderer.prompt.side_effect = ["n", "exact-sub"]
    exact_services = MagicMock()
    exact_services.account_context.return_value = {
        "subscriptionId": "exact-sub"
    }
    command_subject.WorkflowServices.side_effect = [exact_services]
    selected, selected_services = command_subject._select_subscription(
        cmd, renderer, denied, True, True
    )
    assert selected == "exact-sub"
    assert selected_services is exact_services
    renderer.write.assert_called()


def test_subscription_selection_quit_and_noninteractive():
    renderer = MagicMock()
    services = MagicMock(subscription_id="sub")
    services.account_context.return_value = {"subscriptionId": "sub"}
    assert command_subject._select_subscription(
        _cmd(), renderer, services, False, True
    ) == ("sub", services)
    renderer.prompt.return_value = "q"
    with pytest.raises(command_subject.WorkflowCancelled):
        command_subject._select_subscription(
            _cmd(), renderer, services, True, True
        )

    renderer.prompt.side_effect = ["n", "missing"]
    services.list_subscriptions.side_effect = RuntimeError("denied")
    services.resolve_subscription.return_value = {}
    with pytest.raises(ResourceNotFoundError, match="inaccessible"):
        command_subject._select_subscription(
            _cmd(), renderer, services, True, True
        )


def test_subscription_escape_transitions(mocker):
    services = MagicMock(subscription_id="sub")
    services.account_context.return_value = {
        "subscriptionId": "sub",
        "subscriptionName": "Default",
    }

    renderer = MagicMock()
    renderer.prompt.side_effect = [
        command_subject.BackRequested(),
        "",
    ]
    assert command_subject._select_subscription(
        _cmd(), renderer, services, True, True
    ) == ("sub", services)
    assert "first step" in renderer.write.call_args.args[0]

    renderer = MagicMock()
    renderer.prompt.side_effect = ["n", ""]
    services.list_subscriptions.return_value = [{
        "id": "other", "name": "Other", "state": "Enabled"
    }]
    select = mocker.patch.object(
        command_subject,
        "select_value",
        side_effect=command_subject.BackRequested(),
    )
    assert command_subject._select_subscription(
        _cmd(), renderer, services, True, True
    ) == ("sub", services)
    select.assert_called_once()

    renderer = MagicMock()
    renderer.prompt.side_effect = [
        "n",
        command_subject.BackRequested(),
        "",
    ]
    services.list_subscriptions.side_effect = RuntimeError("denied")
    assert command_subject._select_subscription(
        _cmd(), renderer, services, True, True
    ) == ("sub", services)


def test_namespace_create_escape_returns_to_name():
    services = MagicMock()
    services.show_namespace.return_value = None
    renderer = MagicMock()
    renderer.prompt.side_effect = [
        command_subject.BackRequested(),
        "",
    ]
    names = iter(["first", "second"])

    namespace, group = command_subject.resolve_scope_inputs(
        None,
        "rg",
        interactive=True,
        prompt=lambda _: next(names),
        write=lambda _: None,
        validate_namespace=lambda name, rg: (
            command_subject._validate_namespace(
                services,
                renderer,
                name,
                rg,
                True,
                confirm_create=True,
            )
        ),
    )
    assert (namespace, group) == ("second", "rg")
    assert renderer.prompt.call_count == 2


def test_namespace_create_decline_returns_to_name():
    services = MagicMock()
    services.show_namespace.return_value = None
    renderer = MagicMock()
    renderer.prompt.side_effect = ["n", ""]
    names = iter(["first", "second"])

    namespace, group = command_subject.resolve_scope_inputs(
        None,
        "rg",
        interactive=True,
        prompt=lambda _: next(names),
        write=lambda _: None,
        validate_namespace=lambda name, rg: (
            command_subject._validate_namespace(
                services,
                renderer,
                name,
                rg,
                True,
                confirm_create=True,
            )
        ),
    )

    assert (namespace, group) == ("second", "rg")
    assert renderer.prompt.call_count == 2


def test_probe_status_for_staged_and_existing_namespace(mocker):
    services = MagicMock()
    renderer = MagicMock()
    services.show_namespace.return_value = None
    assert command_subject._probe_namespace_status(
        services, renderer, "new", "rg"
    ) is None
    renderer.input_status.assert_called_with(
        "Namespace status",
        "new",
        "Planned",
        "Namespace is staged; readiness will run after apply.",
    )

    services.show_namespace.return_value = {"name": "ns"}
    workflow = mocker.patch.object(
        command_subject, "NamespaceWorkflow"
    ).return_value
    workflow.check.return_value = {"state": "Succeeded"}
    assert command_subject._probe_namespace_status(
        services, renderer, "ns", "rg"
    )["state"] == "Succeeded"


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
    command_subject._validate_endpoint(
        services, renderer, endpoint, True
    )
    renderer.input_status.assert_called_once_with(
        "Update Instance",
        "/updates",
        "Planned",
        "Not found; setup will create it.",
    )
    with pytest.raises(ResourceNotFoundError):
        command_subject._validate_endpoint(
            services, renderer, endpoint, False
        )


def test_no_input_config_does_not_prompt_for_namespace_create(mocker):
    services = MagicMock()
    renderer = MagicMock()
    services.show_namespace.return_value = None
    workflow = mocker.patch.object(
        command_subject, "NamespaceWorkflow"
    ).return_value
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )

    def build(**kwargs):
        kwargs["validate_namespace"]("ns", "rg")
        return SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        )

    mocker.patch.object(
        command_subject, "build_setup_request", side_effect=build
    )
    command_subject._prepare_namespace_setup(
        renderer,
        services,
        "sub",
        True,
        {
            "namespace_name": None,
            "resource_group_name": None,
            "location": None,
            "namespace_outbound_identity": None,
            "dps": None,
            "hubs": None,
            "software_updates": None,
            "complete_connectivity": False,
            "config": "setup.yaml",
            "no_input": True,
        },
    )
    renderer.prompt.assert_not_called()


def test_check_command_delegates(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        return_value=("ns", "rg"),
    )
    workflow.check.return_value = {
        "state": "Succeeded",
        "items": [],
        "summary": {},
    }
    result = command_subject.adr_namespace_check(_cmd(), "ns", "rg")
    assert result["state"] == "Succeeded"
    workflow.check.assert_called_once_with(
        namespace_name="ns", resource_group_name="rg"
    )
    renderer.receipt.assert_called_once_with(result)
    renderer.journey.assert_called_once_with(
        "Scope", "Resources", "Access", "Results"
    )


def test_check_command_collects_missing_scope(mocker):
    workflow, _ = _workflow_mocks(mocker)
    scope = mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        return_value=("ns", "rg"),
    )
    workflow.check.return_value = {
        "state": "Succeeded",
        "items": [],
        "summary": {},
    }
    command_subject.adr_namespace_check(_cmd())
    scope.assert_called_once()


def test_check_command_renders_scope_error(mocker):
    _, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        side_effect=ArgumentUsageError("scope missing"),
    )
    with pytest.raises(
        command_subject.RenderedWorkflowError, match="scope missing"
    ) as raised:
        command_subject.adr_namespace_check(_cmd())
    raised.value.print_error()
    renderer.error.assert_called_once()


def test_check_command_quit_is_graceful(mocker):
    _, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        side_effect=command_subject.WorkflowCancelled(),
    )

    assert command_subject.adr_namespace_check(_cmd()) is None
    renderer.cancelled.assert_called_once_with()


def test_check_command_raises_for_blockers(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        return_value=("ns", "rg"),
    )
    workflow.check.return_value = {
        "state": "Blocked",
        "items": [{
            "state": "Blocked",
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
    mocker.patch.object(
        command_subject,
        "resolve_scope_inputs",
        return_value=("ns", "rg"),
    )
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
        SimpleNamespace(command="az one", state="Planned"),
        SimpleNamespace(command="az skip", state="Satisfied"),
    ]
    workflow.plan_setup.return_value = ({"state": "Planned"}, items)
    output = tmp_path / "plan.sh"
    result = command_subject.adr_namespace_setup(
        _cmd(),
        "ns",
        "rg",
        plan_only=True,
        output_script=str(output),
    )
    assert result == {"state": "Planned"}
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
    item = SimpleNamespace(command="", state="Manual")
    workflow.plan_setup.return_value = ({"state": "Manual"}, [item])
    with pytest.raises(ArgumentUsageError, match="cannot be resolved"):
        command_subject.adr_namespace_setup(
            _cmd(),
            "ns",
            "rg",
            plan_only=True,
            output_script=str(tmp_path / "plan.sh"),
        )


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
    renderer.journey.assert_called_once_with(
        "Subscription",
        "Resource group",
        "Namespace",
        "Configuration",
    )


def test_setup_command_prompt_paths(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        return_value=SimpleNamespace(
            namespace_name="ns", resource_group_name="rg"
        ),
    )
    workflow.plan_setup.return_value = ({"state": "Planned"}, [])
    mocker.patch.object(command_subject.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(command_subject.sys.stderr, "isatty", return_value=True)

    renderer.action.return_value = "n"
    assert command_subject.adr_namespace_setup(
        _cmd(), "ns", "rg"
    ) is None
    renderer.cancelled.assert_called_once_with()
    renderer.action.return_value = "y"
    workflow.setup.return_value = {"state": "Succeeded"}
    assert command_subject.adr_namespace_setup(
        _cmd(), "ns", "rg"
    )["state"] == "Succeeded"


def test_setup_command_quit_is_graceful(mocker):
    _, renderer = _workflow_mocks(mocker)
    command_subject._select_subscription.side_effect = (
        command_subject.WorkflowCancelled()
    )

    assert command_subject.adr_namespace_setup(_cmd()) is None
    renderer.cancelled.assert_called_once_with()

    command_subject._select_subscription.side_effect = None
    services = command_subject.WorkflowServices.return_value
    command_subject._select_subscription.return_value = (
        "sub",
        services,
    )
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        side_effect=command_subject.WorkflowCancelled(),
    )

    assert command_subject.adr_namespace_setup(_cmd()) is None
    assert renderer.cancelled.call_count == 2


def test_setup_quit_after_resource_group_back_is_graceful(mocker):
    _, renderer = _workflow_mocks(mocker)
    services = command_subject.WorkflowServices.return_value
    command_subject._select_subscription.side_effect = [
        ("sub", services),
        command_subject.WorkflowCancelled(),
    ]
    mocker.patch.object(
        command_subject,
        "build_setup_request",
        side_effect=command_subject.BackRequested(),
    )

    assert command_subject.adr_namespace_setup(_cmd()) is None
    renderer.cancelled.assert_called_once_with()


def test_setup_confirmation_back_returns_to_plan(mocker):
    renderer = MagicMock()
    renderer.action.side_effect = command_subject.BackRequested()
    with pytest.raises(command_subject.ReconfigureRequested):
        command_subject._confirm_setup(
            renderer, {"items": [], "summary": {}}, "ns"
        )
    renderer.confirmation.assert_called_once()


def test_setup_confirmation_can_remain_in_review(mocker):
    renderer = MagicMock()
    renderer.action.return_value = "e"
    with pytest.raises(command_subject.ReconfigureRequested):
        command_subject._confirm_setup(
            renderer, {"items": [], "summary": {}}, "ns"
        )
    renderer.confirmation.assert_called_once()


def test_setup_command_back_reconfigures_and_replans(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    first = SimpleNamespace(
        namespace_name="ns",
        resource_group_name="rg",
        location="eastus",
    )
    second = SimpleNamespace(
        namespace_name="ns",
        resource_group_name="rg",
        location="eastus",
    )
    builder = mocker.patch.object(
        command_subject,
        "build_setup_request",
        side_effect=[first, second],
    )
    plan = {"state": "Planned", "items": [], "summary": {}}
    workflow.plan_setup.side_effect = [(plan, []), (plan, [])]
    workflow.setup.return_value = {"state": "Succeeded"}
    renderer.action.side_effect = ["e", "y"]
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    result = command_subject.adr_namespace_setup(_cmd())

    assert result["state"] == "Succeeded"
    assert builder.call_count == 2
    second_call = builder.call_args_list[1].kwargs
    assert second_call["namespace_name"] == "ns"
    assert second_call["resource_group_name"] == "rg"
    assert second_call["namespace_outbound_identity"] is None
    renderer.reset_setup.assert_called_once()


def test_setup_resource_group_back_returns_to_subscription(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SimpleNamespace(
        namespace_name="ns",
        resource_group_name="rg",
    )
    builder = mocker.patch.object(
        command_subject,
        "build_setup_request",
        side_effect=[command_subject.BackRequested(), request],
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.return_value = {"state": "Succeeded"}
    renderer.prompt.return_value = "yes"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    result = command_subject.adr_namespace_setup(_cmd())

    assert result["state"] == "Succeeded"
    assert builder.call_count == 2
    assert command_subject._select_subscription.call_count == 2
    assert renderer.reset_setup.call_count == 1


def test_setup_confirmation_reprompts_invalid_answer():
    renderer = MagicMock()
    renderer.action.return_value = "y"
    command_subject._confirm_setup(
        renderer, {"items": [], "summary": {}}, "ns"
    )
    renderer.confirmed.assert_called_once_with()


def test_setup_review_can_save_plan_json(tmp_path):
    renderer = MagicMock()
    renderer.action.side_effect = ["p", "y"]
    path = tmp_path / "plan.json"
    renderer.prompt.return_value = str(path)
    plan = {"state": "Planned", "items": []}

    command_subject._confirm_setup(renderer, plan, "ns")

    assert path.exists()
    assert path.read_text(encoding="utf-8").endswith("\n")
    renderer.notice.assert_called_with(f"Plan saved: {path}")
    renderer.confirmed.assert_called_once_with()


def test_setup_review_save_back_and_write_error(mocker):
    renderer = MagicMock()
    renderer.action.side_effect = ["p", "p", "y"]
    renderer.prompt.side_effect = [
        command_subject.BackRequested(),
        "plan.json",
    ]
    writer = mocker.patch.object(
        command_subject,
        "write_json_file",
        side_effect=OSError("read only"),
    )

    command_subject._confirm_setup(
        renderer, {"items": []}, "ns"
    )

    writer.assert_called_once_with("plan.json", {"items": []})
    renderer.write.assert_called_with(
        "! Plan not saved: read only"
    )
    renderer.confirmed.assert_called_once_with()


def test_optional_failure_can_continue_without_updates():
    request = SetupRequest(
        "ns",
        "rg",
        software_updates=EndpointSpec(
            "software-updates",
            "updates",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/accounts/a/instances/updates",
            "system-assigned",
        ),
        create_update_instance=True,
    )
    updated = command_subject._without_failed_optional(
        request, {"scope": "software-updates"}
    )
    assert updated.software_updates is None
    assert not updated.create_update_instance
    assert "software-updates" in updated.skipped
    assert command_subject._without_failed_optional(
        request, {"scope": None}
    ) is None


def test_setup_retries_failed_apply_in_session(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest("ns", "rg")
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = [
        RuntimeError("temporary"),
        {"state": "Succeeded"},
    ]
    renderer.recovery.return_value = "r"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    result = command_subject.adr_namespace_setup(_cmd(), "ns", "rg")

    assert result["state"] == "Succeeded"
    assert workflow.setup.call_count == 2
    renderer.recovery.assert_called_once_with(can_continue=False)


def test_successful_retry_preserves_prior_succeeded_items(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest("ns", "rg")
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    partial = {
        "state": "Failed",
        "items": [{
            "id": "namespace",
            "state": "Succeeded",
            "action": "create",
            "target": "ns",
        }],
        "summary": {"Succeeded": 1},
    }
    workflow.setup.side_effect = [
        WorkflowExecutionError(RuntimeError("temporary"), partial),
        {
            "state": "Succeeded",
            "items": [{
                "id": "namespace",
                "state": "Satisfied",
                "action": "reuse",
                "target": "ns",
            }],
            "summary": {"Satisfied": 1},
        },
    ]
    renderer.recovery.return_value = "r"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    result = command_subject.adr_namespace_setup(_cmd(), "ns", "rg")

    assert result["items"][0]["state"] == "Succeeded"
    assert result["summary"] == {"Succeeded": 1}


def test_setup_recovery_escape_preserves_original_failure(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest("ns", "rg")
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = RuntimeError("apply failed")
    renderer.recovery.side_effect = command_subject.BackRequested()
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(
        command_subject.RenderedWorkflowError,
        match="apply failed",
    ):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")


def test_setup_recovery_interrupt_persists_partial_receipt(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest("ns", "rg")
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    partial = {
        "state": "Failed",
        "items": [{
            "id": "namespace",
            "state": "Succeeded",
            "target": "ns",
        }],
        "summary": {"Succeeded": 1},
    }
    workflow.setup.side_effect = WorkflowExecutionError(
        RuntimeError("apply failed"), partial
    )
    renderer.recovery.side_effect = KeyboardInterrupt()
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(command_subject.RenderedWorkflowError):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    command_subject.write_receipt_file.assert_called_once()
    assert partial["keptActions"] == 1


def test_setup_interrupt_does_not_open_recovery(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest("ns", "rg")
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    error = RuntimeError("interrupted")
    error.__cause__ = KeyboardInterrupt()
    workflow.setup.side_effect = error
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(command_subject.RenderedWorkflowError):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    renderer.recovery.assert_not_called()


def test_setup_continues_without_failed_optional_updates(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest(
        "ns",
        "rg",
        software_updates=EndpointSpec(
            "software-updates",
            "updates",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/accounts/a/instances/updates",
            "system-assigned",
        ),
    )
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = [
        RuntimeError("optional failed"),
        {"state": "Succeeded"},
    ]
    renderer.failure = {
        "scope": "software-updates"
    }
    renderer.recovery.return_value = "c"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    result = command_subject.adr_namespace_setup(_cmd(), "ns", "rg")

    assert result["state"] == "Succeeded"
    second_request = workflow.setup.call_args_list[1].args[0]
    assert second_request.software_updates is None
    assert "software-updates" in second_request.skipped
    renderer.recovery.assert_called_once_with(can_continue=True)


def test_setup_continue_replan_failure_keeps_partial_receipt(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest(
        "ns",
        "rg",
        software_updates=EndpointSpec(
            "software-updates",
            "updates",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/accounts/a/instances/updates",
            "system-assigned",
        ),
    )
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    plan = {"state": "Planned", "items": [], "summary": {}}
    workflow.plan_setup.side_effect = [
        (plan, []),
        RuntimeError("replan failed"),
    ]
    partial = {
        "state": "Failed",
        "items": [{
            "id": "namespace",
            "state": "Succeeded",
            "target": "ns",
        }],
        "summary": {"Succeeded": 1},
    }
    workflow.setup.side_effect = WorkflowExecutionError(
        RuntimeError("optional failed"), partial
    )
    renderer.failure = {"scope": "software-updates"}
    renderer.recovery.return_value = "c"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(
        command_subject.RenderedWorkflowError,
        match="replan failed",
    ):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    command_subject.write_receipt_file.assert_called_once()
    assert partial["keptActions"] == 1


def test_setup_cannot_skip_updates_after_mutation(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest(
        "ns",
        "rg",
        software_updates=EndpointSpec(
            "software-updates",
            "updates",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/accounts/a/instances/updates",
            "system-assigned",
        ),
    )
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    partial = {
        "state": "Failed",
        "items": [{
            "id": "link-software-updates-updates",
            "state": "Succeeded",
            "action": "link",
            "target": "updates",
        }],
        "summary": {"Succeeded": 1},
    }
    workflow.setup.side_effect = WorkflowExecutionError(
        RuntimeError("wait failed"), partial
    )
    renderer.failure = {"scope": "software-updates"}
    renderer.recovery.return_value = "q"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(command_subject.RenderedWorkflowError):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    renderer.recovery.assert_called_once_with(can_continue=False)


def test_setup_cannot_skip_after_prior_scoped_mutation(mocker):
    workflow, renderer = _workflow_mocks(mocker)
    request = SetupRequest(
        "ns",
        "rg",
        software_updates=EndpointSpec(
            "software-updates",
            "updates",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/accounts/a/instances/updates",
            "system-assigned",
        ),
    )
    mocker.patch.object(
        command_subject, "build_setup_request", return_value=request
    )
    workflow.plan_setup.return_value = (
        {"state": "Planned", "items": [], "summary": {}},
        [],
    )
    workflow.setup.side_effect = WorkflowExecutionError(
        RuntimeError("role check failed"),
        {"state": "Failed", "items": [], "summary": {}},
    )
    renderer.failure = {
        "scope": "software-updates",
        "mutationAttempted": False,
    }
    renderer.mutated_scopes = frozenset({"software-updates"})
    renderer.recovery.return_value = "q"
    mocker.patch.object(
        command_subject.sys.stdin, "isatty", return_value=True
    )
    mocker.patch.object(
        command_subject.sys.stderr, "isatty", return_value=True
    )

    with pytest.raises(command_subject.RenderedWorkflowError):
        command_subject.adr_namespace_setup(_cmd(), "ns", "rg")
    renderer.recovery.assert_called_once_with(can_continue=False)


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
