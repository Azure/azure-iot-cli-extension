# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, call, patch

import pytest

from azext_iot.tests.adr import _helpers as subject
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    CleanupLedger,
    is_retryable_resource_error,
    is_resource_not_found_error,
    wait_for_condition,
    wait_for_listed_resource,
    wait_for_materialized_resources,
    wait_for_resource_succeeded,
)
from azext_iot.tests.adr.conftest import RoleAssignmentHelper


def test_wait_for_resource_succeeded_retries_initial_not_found():
    test = Mock()
    response = Mock()
    response.get_output_in_json.return_value = {
        "properties": {"provisioningState": "Succeeded"}
    }
    test.cmd.side_effect = [RuntimeError("ResourceNotFound (404)"), response]

    with patch.object(subject.time, "sleep") as sleep:
        result = wait_for_resource_succeeded(
            test, "show resource", max_polls=2, poll_interval=0
        )

    assert result["properties"]["provisioningState"] == "Succeeded"
    sleep.assert_called_once_with(0)


def test_wait_for_resource_succeeded_raises_terminal_failure():
    response = Mock()
    response.get_output_in_json.return_value = {
        "properties": {"provisioningState": "Failed"}
    }
    test = Mock()
    test.cmd.return_value = response

    with pytest.raises(
        AssertionError,
        match="terminal failure.*provisioningState='Failed'",
    ):
        wait_for_resource_succeeded(
            test, "show resource", max_polls=1, poll_interval=0
        )


def test_wait_for_resource_succeeded_times_out_with_last_error():
    test = Mock()
    test.cmd.side_effect = RuntimeError("ResourceNotFound: still missing")

    with patch.object(subject.time, "sleep"), pytest.raises(
        AssertionError, match="still missing"
    ):
        wait_for_resource_succeeded(
            test, "show resource", max_polls=2, poll_interval=0
        )


def test_wait_for_resource_succeeded_propagates_non_retryable_error():
    test = Mock()
    test.cmd.side_effect = RuntimeError("invalid command argument")

    with patch.object(subject.time, "sleep") as sleep, pytest.raises(
        RuntimeError, match="invalid command argument"
    ):
        wait_for_resource_succeeded(
            test, "show resource", max_polls=2, poll_interval=0
        )

    sleep.assert_not_called()


@pytest.mark.parametrize(
    "status_code",
    [404, 408, 409, 429, 500, 502, 503, 504],
)
def test_retryable_resource_error_uses_structured_status(status_code):
    error = RuntimeError("structured ARM error")
    error.status_code = status_code
    assert is_retryable_resource_error(error)


@pytest.mark.parametrize(
    "message",
    [
        "Code: Conflict",
        "Code: InternalServerError",
        "Code: BadGateway",
        "Code: ServiceUnavailable",
        "Code: GatewayTimeout",
    ],
)
def test_retryable_resource_error_uses_symbolic_code(message):
    assert is_retryable_resource_error(RuntimeError(message))


def test_resource_not_found_error_is_specific():
    missing = RuntimeError("ResourceNotFound (404)")
    forbidden = RuntimeError("403 Forbidden")
    assert is_resource_not_found_error(missing)
    assert not is_resource_not_found_error(forbidden)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("An IotHub 'hub' under resource group 'rg' was not found.", True),
        ("AuthorizationFailed: an assignment was not found.", False),
        ("Required configuration was not found.", False),
    ],
)
def test_resource_not_found_error_recognizes_only_hub_show_absence(message, expected):
    assert is_resource_not_found_error(RuntimeError(message)) is expected


def test_wait_for_condition_uses_bounded_clock_and_sanitized_observation():
    observations = iter([{"state": "Creating"}, {"state": "Succeeded"}])
    sleeps = []
    clock_values = iter([0, 0, 1, 1])

    result = wait_for_condition(
        lambda: next(observations),
        lambda value: value["state"] == "Succeeded",
        description="test condition",
        timeout=5,
        interval=1,
        describe=lambda value: f"state={value['state']}",
        clock=lambda: next(clock_values),
        sleeper=sleeps.append,
    )

    assert result == {"state": "Succeeded"}
    assert sleeps == [1]


def test_wait_for_condition_reports_terminal_failure():
    with pytest.raises(
        AssertionError, match="terminal failure.*state=Failed"
    ):
        wait_for_condition(
            lambda: {"state": "Failed"},
            lambda value: False,
            description="test condition",
            is_terminal_failure=lambda value: value["state"] == "Failed",
            timeout=None,
            max_attempts=1,
            describe=lambda value: f"state={value['state']}",
        )


def test_wait_for_condition_reports_last_retryable_error():
    with pytest.raises(AssertionError, match="still creating"):
        wait_for_condition(
            lambda: (_ for _ in ()).throw(
                RuntimeError("ResourceNotFound: still creating")
            ),
            lambda value: False,
            description="test condition",
            timeout=None,
            interval=0,
            max_attempts=2,
            sleeper=lambda _: None,
        )


def test_wait_for_condition_reports_elapsed_timeout():
    clock_values = iter([0, 2])
    with pytest.raises(AssertionError, match="last observation: state=Creating"):
        wait_for_condition(
            lambda: {"state": "Creating"},
            lambda value: False,
            description="test condition",
            timeout=1,
            interval=1,
            describe=lambda value: f"state={value['state']}",
            clock=lambda: next(clock_values),
            sleeper=lambda _: None,
        )


def test_wait_for_materialized_resources_retries_empty_collection():
    test = Mock()
    empty = Mock()
    empty.get_output_in_json.return_value = []
    populated = Mock()
    populated.get_output_in_json.return_value = [{"name": "child"}]
    test.cmd.side_effect = [empty, populated]

    resources = wait_for_materialized_resources(
        test,
        "list children",
        description="children",
        timeout=None,
        interval=0,
    )

    assert resources == [{"name": "child"}]
    assert test.cmd.call_count == 2


def test_wait_for_listed_resource_retries_missing_name_and_transient_read():
    test = Mock()
    stale = Mock()
    stale.get_output_in_json.return_value = [{"name": "older-resource"}]
    ready = Mock()
    ready.get_output_in_json.return_value = [{"name": "new-resource"}]
    error = RuntimeError("ProviderError: failed to return collection response")
    error.status_code = 502
    test.cmd.side_effect = [stale, error, ready]

    assert wait_for_listed_resource(
        test, "list resources", "new-resource", timeout=10, interval=0
    ) == [{"name": "new-resource"}]
    assert test.cmd.call_count == 3


def test_wait_for_listed_resource_times_out_without_skipping():
    test = Mock()
    test.cmd.return_value.get_output_in_json.return_value = [{"name": "old"}]

    with pytest.raises(AssertionError, match="expected resource absent"):
        wait_for_listed_resource(test, "list resources", "new", timeout=0)
    test.cmd.assert_called_once_with("list resources")


def test_wait_for_listed_resource_does_not_retry_authorization_failure():
    test = Mock()
    test.cmd.side_effect = RuntimeError("403 AuthorizationFailed")

    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        wait_for_listed_resource(test, "list resources", "new")
    test.cmd.assert_called_once_with("list resources")


def test_cleanup_ledger_runs_callbacks_in_reverse_and_supports_dismiss():
    calls = []
    with CleanupLedger() as cleanup:
        cleanup.register("parent", lambda: calls.append("parent"))
        cleanup.register("dismissed", lambda: calls.append("dismissed"))
        cleanup.register("child", lambda: calls.append("child"))
        cleanup.dismiss("dismissed")

    assert calls == ["child", "parent"]


def test_cleanup_ledger_reports_failures_without_masking_original_error():
    def fail_cleanup():
        raise RuntimeError("cleanup error")

    with pytest.raises(RuntimeError, match="original error"):
        with CleanupLedger() as cleanup:
            cleanup.register("resource", fail_cleanup)
            raise RuntimeError("original error")


def test_cleanup_ledger_raises_when_only_cleanup_fails():
    def fail_cleanup():
        raise RuntimeError("cleanup error")

    with pytest.raises(AssertionError, match="resource: cleanup error"):
        with CleanupLedger() as cleanup:
            cleanup.register("resource", fail_cleanup)


def test_full_infra_cleanup_removes_links_before_namespace_and_identity():
    helper = ADRFullInfraHelper()
    commands = []

    def invoke(command):
        commands.append(command)
        if "link dps list" in command:
            response = Mock()
            response.get_output_in_json.return_value = [{"name": "dps-primary"}]
            return response
        if command.startswith("iot dps show"):
            raise RuntimeError("ResourceNotFound (404)")
        return Mock()

    helper.cmd = Mock(side_effect=invoke)
    helper.cleanup_full_infra(
        resource_group="rg",
        namespace_name="ns",
        identity_name="identity",
        dps_name="dps",
        linked_endpoints=[("dps", "dps-primary")],
    )

    link_delete = next(
        index
        for index, command in enumerate(commands)
        if "link dps delete" in command
    )
    namespace_delete = next(
        index
        for index, command in enumerate(commands)
        if command.startswith("iot adr ns delete")
    )
    identity_delete = next(
        index
        for index, command in enumerate(commands)
        if command.startswith("identity delete")
    )
    assert link_delete < namespace_delete < identity_delete
    assert not any(command.startswith("iot dps delete") for command in commands)


def test_full_infra_cleanup_reports_probe_failures():
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=RuntimeError("403 Forbidden"))

    with pytest.raises(AssertionError, match="lookup: 403 Forbidden"):
        helper.cleanup_full_infra(
            resource_group="rg",
            namespace_name="ns",
            identity_name="identity",
            dps_name="dps",
            linked_endpoints=[("dps", "dps-primary")],
        )


def test_full_infra_cleanup_continues_after_show_not_found_exit():
    helper = ADRFullInfraHelper()

    def invoke(command):
        if command.startswith("iot hub show"):
            raise SystemExit(3)
        return Mock()

    helper.cmd = Mock(side_effect=invoke)
    helper.cleanup_full_infra(
        resource_group="rg",
        hub_name="hub",
        namespace_name="ns",
        identity_name="identity",
    )

    assert helper.cmd.call_args_list == [
        call("iot hub show -n hub -g rg"),
        call("iot adr ns show -n ns -g rg"),
        call("iot adr ns delete -n ns -g rg -y"),
        call("identity show -n identity -g rg"),
        call("identity delete -n identity -g rg"),
    ]


def test_full_infra_cleanup_accepts_deleted_hub_show_error():
    helper = ADRFullInfraHelper()

    def invoke(command):
        if command.startswith("iot hub show"):
            raise RuntimeError("An IotHub 'hub' under resource group 'rg' was not found.")
        return Mock()

    helper.cmd = Mock(side_effect=invoke)
    helper.cleanup_full_infra(
        resource_group="rg", hub_name="hub", namespace_name="ns",
    )

    assert helper.cmd.call_args_list == [
        call("iot hub show -n hub -g rg"),
        call("iot adr ns show -n ns -g rg"),
        call("iot adr ns delete -n ns -g rg -y"),
    ]


@pytest.mark.parametrize("exit_code", [1, 2, 130])
def test_full_infra_cleanup_does_not_ignore_other_cli_exits(exit_code):
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=SystemExit(exit_code))

    with pytest.raises(SystemExit) as error:
        helper.cleanup_full_infra(resource_group="rg", hub_name="hub")

    assert error.value.code == exit_code
    helper.cmd.assert_called_once_with("iot hub show -n hub -g rg")


@pytest.mark.parametrize(
    "device_delete_error",
    [None, RuntimeError("ResourceNotFound (404)"), RuntimeError("403 Forbidden")],
)
def test_registry_cleanup_attempts_device_before_namespace(device_delete_error, caplog):
    from azext_iot.tests.adr.test_adr_registry_device_int import (
        TEST_RG,
        _cleanup_namespace,
    )

    test = Mock()
    test.cmd.side_effect = [device_delete_error, None]
    _cleanup_namespace(test, "ns", "device")

    assert test.cmd.call_args_list == [
        call(
            "iot adr ns registry-device delete -n device "
            f"--ns ns -g {TEST_RG} --yes"
        ),
        call(f"iot adr ns delete -n ns -g {TEST_RG} --yes"),
    ]
    if device_delete_error is not None:
        expected = "already absent" if "404" in str(device_delete_error) else "Cleanup failed"
        assert expected in caplog.text


def test_known_object_role_assignment_bypasses_graph_resolution():
    helper = RoleAssignmentHelper()
    absent = Mock()
    absent.get_output_in_json.return_value = []
    created = Mock()
    created.get_output_in_json.return_value = {"id": "assignment"}
    helper.cmd = Mock(side_effect=[absent, created])

    assert helper.assign_role(
        "principal",
        "role",
        "scope",
        assignee_type="ServicePrincipal",
    ) == "assignment"

    list_command, create_command = [
        item.args[0] for item in helper.cmd.call_args_list
    ]
    assert "--assignee-object-id 'principal'" in list_command
    assert "--fill-principal-name false" in list_command
    assert "--assignee-object-id 'principal'" in create_command
    assert "--assignee-principal-type ServicePrincipal" in create_command
    assert "--assignee " not in list_command
    assert "--assignee " not in create_command


def test_existing_caller_object_role_assignment_lets_arm_resolve_principal_type():
    helper = RoleAssignmentHelper()
    absent = Mock()
    absent.get_output_in_json.return_value = []
    created = Mock()
    created.get_output_in_json.return_value = {"id": "assignment"}
    helper.cmd = Mock(side_effect=[absent, created])

    assert helper.assign_role(
        "caller", "Device Update Reader", "scope", assignee_type=None
    ) == "assignment"
    commands = [item.args[0] for item in helper.cmd.call_args_list]
    assert all("--assignee-object-id 'caller'" in command for command in commands)
    assert all("--assignee-principal-type" not in command for command in commands)
    assert all("--assignee " not in command for command in commands)


def test_auto_role_assignment_preserves_name_based_lookup():
    helper = RoleAssignmentHelper()
    existing = Mock()
    existing.get_output_in_json.return_value = [{"id": "assignment"}]
    helper.cmd = Mock(return_value=existing)

    assert helper.assign_role("assignee", "role", "scope") == "assignment"

    list_command = helper.cmd.call_args.args[0]
    assert "--assignee 'assignee'" in list_command
    assert "--assignee-object-id" not in list_command


def test_adr_uami_roles_use_object_id_and_fail_setup_if_missing():
    helper = RoleAssignmentHelper()
    helper.assign_role = Mock(side_effect=["contributor", "onboarding"])

    helper.assign_adr_roles_to_identity("principal", "scope")

    assert helper.assign_role.call_args_list == [
        call(
            "principal",
            "Azure Device Registry Contributor",
            "scope",
            assignee_type="ServicePrincipal",
        ),
        call(
            "principal",
            "Azure Device Registry Onboarding",
            "scope",
            assignee_type="ServicePrincipal",
        ),
    ]

    helper.assign_role = Mock(return_value=None)
    with pytest.raises(AssertionError, match="required ADR role"):
        helper.assign_adr_roles_to_identity("principal", "scope")
