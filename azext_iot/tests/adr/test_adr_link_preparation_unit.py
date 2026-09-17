# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock, call
import shlex

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, RequiredArgumentMissingError
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.adr.rbac import LinkRbacManager
from azext_iot.tests.adr import test_adr_link_int as subject
from azext_iot.tests.adr._helpers import ADRFullInfraHelper


SU_ID = (
    "/subscriptions/fixture-sub/resourceGroups/fixture-rg/providers/"
    "Microsoft.DeviceUpdate/updateInstances/fixture"
)


@pytest.fixture()
def preparation(monkeypatch):
    test = ADRFullInfraHelper()
    test.cmd = Mock()
    test.assign_role = Mock()
    test.cli_ctx = SimpleNamespace()
    network = Mock(side_effect=AssertionError("Unexpected network/Graph request"))
    monkeypatch.setattr("requests.sessions.Session.request", network)
    manager = LinkRbacManager(test.cli_ctx, cli=Mock())
    manager._current_assignee_object_id = Mock(return_value="caller")
    manager.ensure = Mock()
    monkeypatch.setattr(subject, "LinkRbacManager", Mock(return_value=manager))
    monkeypatch.setattr(subject, "TEST_SUBSCRIPTION", "configured-sub")
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", "")
    monkeypatch.setattr(subject, "_SU_READER_PROBE", False)
    return test, manager, network


@pytest.mark.parametrize("fixture_id,subscription", [("", "configured-sub"), (SU_ID, "fixture-sub")])
def test_su_caller_identity_failure_precedes_all_resource_and_role_mutations(
    preparation, monkeypatch, fixture_id, subscription,
):
    test, manager, network = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", fixture_id)
    error = AzureResponseError("Could not resolve caller ARM identity")
    manager._current_assignee_object_id.side_effect = error

    with pytest.raises(AzureResponseError, match="caller ARM identity") as failure:
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert failure.value is error
    manager._current_assignee_object_id.assert_called_once_with(subscription)
    network.assert_not_called()
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    manager.cli.invoke.assert_not_called()


def test_su_prepares_caller_arm_identity_without_graph_before_provisioning(preparation):
    test, manager, network = preparation
    events = []

    def caller(subscription):
        events.append("caller " + subscription)
        return "caller"

    def command(value):
        events.append(value)
        if value.startswith("identity show "):
            raise CLIError("ResourceNotFound (404)")
        if value.startswith("identity create "):
            raise RuntimeError("Stop at the first provisioning command")
        return Mock(get_output_in_json=lambda: [])

    manager._current_assignee_object_id.side_effect = caller
    test.cmd.side_effect = command

    with pytest.raises(RuntimeError, match="Stop at the first provisioning command"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert events[0] == "caller configured-sub"
    assert events[1].startswith("identity show ")
    assert events[2].startswith("identity create ")
    network.assert_not_called()


def test_su_borrowed_fixture_is_not_deleted_on_setup_failure(preparation, monkeypatch):
    test, manager, network = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID)
    manager._current_assignee_object_id = Mock(return_value="caller")

    test.cmd.side_effect = RuntimeError("fixture lookup failed")
    with pytest.raises(RuntimeError, match="fixture lookup failed"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    network.assert_not_called()
    assert test.cmd.call_count == 1
    assert test.cmd.call_args.args[0] == f"resource show --ids {SU_ID}"
    assert test._owned_resources == {}


def test_reader_experiment_rejects_borrowed_fixture_before_identity_or_mutations(preparation, monkeypatch):
    test, manager, network = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID)
    monkeypatch.setattr(subject, "_SU_READER_PROBE", True)
    with pytest.raises(AssertionError, match="fresh owned"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)
    manager._current_assignee_object_id.assert_not_called()
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    network.assert_not_called()


@pytest.mark.parametrize("probe_reader", [False, True])
def test_su_keeps_normal_reader_fixture_but_omits_it_before_opt_in_discovery(preparation, monkeypatch, probe_reader):
    test, manager, _ = preparation
    monkeypatch.setattr(subject, "_SU_READER_PROBE", probe_reader)
    identity_id = "/subscriptions/configured-sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id"
    su_id = "/subscriptions/configured-sub/resourceGroups/rg/providers/Microsoft.DeviceUpdate/updateInstances/su"
    ns_id = "/subscriptions/configured-sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
    test.create_owned_resource = Mock(side_effect=[
        Mock(get_output_in_json=lambda: {"id": identity_id, "principalId": "uami"}),
        Mock(get_output_in_json=lambda: {
            "id": ns_id, "identity": {"type": "SystemAssigned", "principalId": "namespace"},
        }),
        Mock(),
    ])
    waits = []

    def wait(*_args, **_kwargs):
        waits.append(True)
        if len(waits) == 2:
            if probe_reader:
                test.assign_role.assert_not_called()
            else:
                test.assign_role.assert_called_once_with("caller", "Device Update Reader", su_id, assignee_type=None)
        return {"id": su_id}

    monkeypatch.setattr(subject, "wait_for_condition", wait)
    test.cmd.side_effect = RuntimeError("stop at Update Instance identity inspection")
    with pytest.raises(RuntimeError, match="identity inspection"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)
    if probe_reader:
        test.assign_role.assert_not_called()
    else:
        test.assign_role.assert_called_once_with("caller", "Device Update Reader", su_id, assignee_type=None)
    manager.ensure.assert_not_called()


@pytest.mark.parametrize("failure", [None, "failed", "timeout", "preauthorized"])
def test_owned_su_waits_only_for_resource_and_leaves_fresh_roles_to_native_link(monkeypatch, failure):
    from azext_iot.tests.adr._helpers import wait_for_condition

    test = Mock()
    manager = Mock()
    manager._current_assignee_object_id.return_value = "caller"
    monkeypatch.setattr(subject, "LinkRbacManager", Mock(return_value=manager))
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", "")
    monkeypatch.setattr(subject, "_SU_READER_PROBE", True)
    names = iter(["ns", "denied"])
    monkeypatch.setattr(subject, "generate_adr_namespace_name", lambda: next(names))
    now = [0]
    created = []
    prefix = "/subscriptions/sub/resourceGroups/rg/providers/"
    identity_id = prefix + "Microsoft.ManagedIdentity/userAssignedIdentities/id"
    namespace_id = prefix + "Microsoft.DeviceRegistry/namespaces/ns"
    su_id = prefix + "Microsoft.DeviceUpdate/updateInstances/su"

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(
        subject, "wait_for_condition",
        lambda *args, **kwargs: wait_for_condition(*args, **kwargs, clock=lambda: now[0], sleeper=sleep),
    )

    def create(command, *, kind, **_kwargs):
        created.append(kind)
        if kind == "identity":
            value = {"id": identity_id, "principalId": "uami"}
        elif kind == "namespace":
            value = {"id": namespace_id, "identity": {"type": "SystemAssigned", "principalId": "namespace"}}
        else:
            assert kind == "su" and "--no-wait" in command
            value = None
        return Mock(get_output_in_json=lambda: value)

    def invoke(command):
        if command.startswith("iot adr ns su instance show "):
            state = {"failed": "Failed", "timeout": "Creating"}.get(failure, "Succeeded")
            value = {"id": su_id, "properties": {"provisioningState": state}}
        elif command.startswith("resource show --ids "):
            assert now[0] == 0
            value = {"identity": {"principalId": "su-sami", "userAssignedIdentities": {identity_id: {}}}}
        elif command.startswith("identity show --ids "):
            value = {"principalId": "uami"}
        elif command.startswith("iot adr ns link su add --ns denied "):
            raise RequiredArgumentMissingError(subject.MI_REQUIRED_MSG)
        elif command.startswith("iot adr ns link su add --ns ns "):
            assert now[0] == 0
            assert subject._NATIVE_LINK_OPTIONS in command
            manager.ensure.assert_not_called()
            raise RuntimeError("stop at actual UAMI link")
        elif command.startswith("role assignment list "):
            value = [{"id": "preexisting"}] if failure == "preauthorized" else []
        else:
            raise AssertionError(f"Unexpected command: {command}")
        return Mock(get_output_in_json=lambda: value)

    test.create_owned_resource.side_effect = create
    test.cmd.side_effect = invoke
    with pytest.raises(AssertionError if failure else RuntimeError):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)
    assert now[0] <= 3600
    if failure:
        assert not any("link su add --ns ns " in item.args[0] for item in test.cmd.call_args_list)
    else:
        assert now[0] == 0
    manager.ensure.assert_not_called()
    manager.ensure_many.assert_not_called()
    test.assign_role.assert_not_called()
    test.cleanup_full_infra.assert_called_once()


def test_su_borrowed_targets_survive_cleanup_after_namespace_creation(preparation, monkeypatch):
    import shlex

    test, manager, _ = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID)
    manager._current_assignee_object_id = Mock(return_value="caller")
    namespaces = set()

    def invoke(command):
        args = shlex.split(command)
        if command == f"resource show --ids {SU_ID}":
            return Mock(get_output_in_json=lambda: {
                "identity": {"principalId": "sami", "userAssignedIdentities": {"borrowed-uami": {}}},
            })
        if command == "identity show --ids borrowed-uami":
            return Mock(get_output_in_json=lambda: {"principalId": "uami"})
        if command.startswith("iot adr ns link su add"):
            if "su-no-identity" in args:
                raise RequiredArgumentMissingError(subject.MI_REQUIRED_MSG)
            raise RuntimeError("link failed after creating test namespaces")
        name = args[args.index("-n") + 1]
        if command.startswith("iot adr ns show"):
            if name not in namespaces:
                raise CLIError("ResourceNotFound (404)")
        elif command.startswith("iot adr ns create"):
            namespaces.add(name)
        elif command.startswith("iot adr ns delete"):
            namespaces.remove(name)
        else:
            raise AssertionError(f"Unexpected command: {command}")
        return Mock(get_output_in_json=lambda: {"id": name, "identity": {"principalId": "namespace-sami"}})

    test.cmd.side_effect = invoke
    with pytest.raises(RuntimeError, match="link failed after creating test namespaces"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)
    assert not namespaces
    deletes = [call.args[0] for call in test.cmd.call_args_list if " delete " in call.args[0]]
    assert len(deletes) == 2
    assert all(command.startswith("iot adr ns delete ") for command in deletes)


@pytest.mark.parametrize(
    "supplied,case",
    [
        (False, "missing_sami"), (True, "missing_sami"),
        (False, "missing_uami"), (True, "missing_uami"),
        (False, "missing_principal"), (True, "missing_principal"),
        (False, "different_uami"), (False, "case_varied_uami"),
    ],
)
def test_su_identity_prerequisites_distinguish_owned_resources(preparation, monkeypatch, supplied, case):
    test, manager, _ = preparation
    manager._current_assignee_object_id = Mock(return_value="caller")
    monkeypatch.setattr(subject, "TEST_RG", "rg")
    monkeypatch.setattr(subject, "generate_identity_name", lambda: "owned-uami")
    monkeypatch.setattr(subject, "generate_generic_id", lambda: "owned123")
    monkeypatch.setattr(subject, "generate_adr_namespace_name", lambda: "owned-ns")
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID if supplied else "")
    requested_id = (
        "/subscriptions/configured-sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/owned-uami"
    )
    owned_su_id = (
        "/subscriptions/configured-sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceUpdate/updateInstances/testsuowned123"
    )
    namespace_id = (
        "/subscriptions/configured-sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/namespaces/owned-ns"
    )
    su_id = SU_ID if supplied else owned_su_id
    identity = {"principalId": "sami", "userAssignedIdentities": {requested_id: {}}}
    if case == "missing_sami":
        identity.pop("principalId")
    elif case == "missing_uami":
        identity.pop("userAssignedIdentities")
    elif case == "different_uami":
        identity["userAssignedIdentities"] = {"different-uami": {}}
    elif case == "case_varied_uami":
        identity["userAssignedIdentities"] = {"different-uami": {}, requested_id.upper(): {}}
    provisioned = Mock(return_value={"id": su_id})
    monkeypatch.setattr(subject, "wait_for_condition", provisioned)

    outputs = []
    commands = []
    if not supplied:
        outputs.extend([
            CLIError("ResourceNotFound (404)"),
            Mock(get_output_in_json=lambda: {"id": requested_id, "principalId": "uami"}),
            CLIError("ResourceNotFound (404)"),
            Mock(get_output_in_json=lambda: {
                "id": namespace_id, "identity": {"type": "SystemAssigned", "principalId": "namespace"},
            }),
            CLIError("ResourceNotFound (404)"), Mock(),
        ])
        commands.extend([
            call("identity show -n owned-uami -g rg"),
            call(f"identity create -n owned-uami -g rg --location {subject.TEST_LOCATION}"),
            call("iot adr ns show -n owned-ns -g rg"),
            call(f"iot adr ns create -n owned-ns -g rg --location {subject.TEST_LOCATION}"),
            call("iot adr ns su instance show -n testsuowned123 -g rg"),
            call(
                "iot adr ns su instance create -n testsuowned123 -g rg "
                f"--location {subject.TEST_LOCATION} --system-assigned-mi "
                f"--user-assigned-mi {requested_id} --no-wait"
            ),
        ])
    outputs.append(Mock(get_output_in_json=lambda: {"identity": identity}))
    commands.append(call(f"resource show --ids {su_id}"))
    expected_exception = pytest.skip.Exception if supplied else AssertionError
    if case == "missing_sami":
        expected_message = (
            f"Created update instance '{su_id}' is missing the requested "
            "system-assigned identity principalId after provisioning succeeded."
        )
    elif case in {"missing_uami", "different_uami"}:
        expected_message = (
            f"Created update instance '{su_id}' is missing the requested "
            f"user-assigned identity '{requested_id}' after provisioning succeeded."
        )
    else:
        resolved_id = requested_id.upper() if case == "case_varied_uami" else requested_id
        outputs.append(Mock(get_output_in_json=lambda: {} if case == "missing_principal" else {"principalId": "uami"}))
        commands.append(call(f"identity show --ids {resolved_id}"))
        expected_message = f"Created update instance UAMI '{resolved_id}' has no principalId."
    if supplied:
        expected_message = (
            "The supplied update instance UAMI has no principalId." if case == "missing_principal" else
            "The supplied update instance must have both system-assigned and user-assigned identities."
        )
    if case == "case_varied_uami":
        expected_exception = RuntimeError
        expected_message = "Identity prerequisites accepted"
        outputs.append(RuntimeError(expected_message))
        commands.append(call("iot adr ns show -n owned-ns -g rg"))
    if not supplied:
        outputs.extend(Mock() for _ in range(6))
        commands.extend([
            call("iot adr ns show -n owned-ns -g rg"),
            call("iot adr ns delete -n owned-ns -g rg --yes"),
            call("iot adr ns su instance show -n testsuowned123 -g rg"),
            call("iot adr ns su instance delete -n testsuowned123 -g rg --yes"),
            call("identity show -n owned-uami -g rg"),
            call("identity delete -n owned-uami -g rg"),
        ])
    test.cmd.side_effect = outputs

    try:
        with pytest.raises(expected_exception) as raised:
            subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)
    except pytest.skip.Exception as error:
        pytest.fail(f"Owned update instance identity failure was incorrectly skipped: {error}")

    # Pytest appends assertion introspection after the scenario's message.
    assert str(raised.value).splitlines()[0] == expected_message
    assert test.cmd.call_args_list == commands
    assert not test._owned_resources
    if supplied:
        provisioned.assert_not_called()
    else:
        assert provisioned.call_count == 2
        assert provisioned.call_args_list[0].kwargs["timeout"] == 120
        assert provisioned.call_args.kwargs["max_attempts"] == subject.SU_PROVISIONING_MAX_POLLS
        assert provisioned.call_args.kwargs["interval"] == subject.SU_PROVISIONING_POLL_INTERVAL
        manager.ensure.assert_not_called()


def test_owned_identity_regression_rejects_unexpected_scenario_skip(preparation, monkeypatch):
    def incorrect_skip(_self):
        pytest.skip("supplied-fixture skip")

    monkeypatch.setattr(subject.TestADRLinkSU, "test_adr_link_su_lifecycle", incorrect_skip)
    with pytest.raises(pytest.fail.Exception, match="Owned update instance identity failure was incorrectly skipped"):
        test_su_identity_prerequisites_distinguish_owned_resources(
            preparation, monkeypatch, False, "missing_sami",
        )


@pytest.mark.parametrize("failure", [
    None, "add", "update", "pending-add", "pending-update", "preauthorized-sami", "role-read", "discovery",
])
def test_owned_su_lifecycle_native_commands_own_fresh_roles_recovery_and_terminal_results(monkeypatch, failure):
    from copy import deepcopy
    from azext_iot.tests.adr._helpers import wait_for_condition

    scenario = Mock()
    manager = Mock()
    manager._current_assignee_object_id.return_value = "caller"
    manager.ensure.side_effect = manager.ensure_many.side_effect = AssertionError("Fixture service-role grants forbidden")
    monkeypatch.setattr(subject, "LinkRbacManager", Mock(return_value=manager))
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", "")
    monkeypatch.setattr(subject, "_SU_READER_PROBE", False)
    names = iter(["ns", "denied"])
    monkeypatch.setattr(subject, "generate_adr_namespace_name", lambda: next(names))
    waits = Mock(side_effect=AssertionError("No test-side link wait/repair"))
    monkeypatch.setattr(subject, "_wait_for_linking_succeeded", waits)
    monkeypatch.setattr(subject, "link_dps_with_readiness", waits)
    monkeypatch.setattr(subject, "link_hub_with_readiness", waits)
    sleep = Mock(side_effect=AssertionError("No preauthorization delay for ready resources"))
    monkeypatch.setattr(
        subject, "wait_for_condition",
        lambda *args, **kwargs: wait_for_condition(*args, **kwargs, clock=lambda: 0, sleeper=sleep),
    )
    prefix = "/subscriptions/sub/resourceGroups/rg/providers/"
    identity_id = prefix + "Microsoft.ManagedIdentity/userAssignedIdentities/uami"
    namespace_id = prefix + "Microsoft.DeviceRegistry/namespaces/ns"
    su_id = prefix + "Microsoft.DeviceUpdate/updateInstances/su"
    namespace = {
        "id": namespace_id, "identity": {"type": "SystemAssigned", "principalId": "namespace-sami"},
        "properties": {"provisioningState": "Succeeded"},
    }
    native_commands, role_observations = [], []
    endpoint = None

    def output(value):
        return Mock(get_output_in_json=lambda: deepcopy(value))

    def create(command, *, kind, **_):
        if kind == "identity":
            return output({"id": identity_id, "principalId": "su-uami"})
        if kind == "namespace":
            return output(namespace)
        assert kind == "su" and "--no-wait" in command
        return output(None)

    def invoke(command, expect_failure=False):
        nonlocal endpoint
        if command.startswith("iot adr ns su instance show "):
            return output({"id": su_id, "properties": {"provisioningState": "Succeeded"}})
        if command.startswith("resource show --ids "):
            return output({"identity": {"principalId": "su-sami", "userAssignedIdentities": {identity_id: {}}}})
        if command.startswith("identity show --ids "):
            return output({"principalId": "su-uami"})
        if command.startswith("role assignment list "):
            if failure == "role-read":
                raise HttpResponseError("role-read failed")
            args = shlex.split(command)
            principal = args[args.index("--assignee-object-id") + 1]
            role = args[args.index("--role") + 1]
            scope = args[args.index("--scope") + 1]
            present = bool(native_commands) if principal != "su-sami" else len(native_commands) == 2
            if principal == "su-sami" and failure == "preauthorized-sami":
                present = True
            role_observations.append((principal, role, scope, present))
            return output([{"id": "native-created"}] if present else [])
        if command.startswith("iot adr ns link su add "):
            if "--ns denied " in command:
                raise RequiredArgumentMissingError(subject.MI_REQUIRED_MSG)
            if "su-cap-rejected-link" in command:
                raise ArgumentUsageError(subject.SU_CAP_EXCEEDED_MSG)
            if expect_failure:
                assert endpoint is not None
                return output(None)
            action = "add"
            inbound = {"type": "UserAssigned", "userAssignedIdentity": identity_id}
            assert not native_commands
        elif command.startswith("iot adr ns link su update "):
            action = "update"
            inbound = {"type": "SystemAssigned"}
            assert len(native_commands) == 1
        else:
            if command.startswith("iot adr ns link su show "):
                return output({"name": "su-primary", **endpoint})
            if command.startswith("iot adr ns link su list "):
                return output([{"name": "su-primary", **endpoint}])
            if command.startswith("iot adr ns link su wait "):
                assert endpoint["linkingState"] == "Succeeded"
                return output(None)
            if command.startswith(("iot adr ns su instance update ", "iot adr ns su instance create ")):
                raise ArgumentUsageError("identity is used by an active ADR link")
            if command.startswith(("iot adr ns su software-update ", "iot adr ns su device-class ")):
                if failure == "discovery":
                    raise HttpResponseError("discovery failed")
                return output([])
            raise AssertionError(f"Unexpected command: {command}")
        native_commands.append(command)
        assert subject._NATIVE_LINK_OPTIONS in command and "--no-wait" not in command
        if failure == action:
            raise HttpResponseError(f"{action} failed")
        endpoint = {
            "endpointType": "Microsoft.DeviceUpdate/updateInstances", "resourceId": su_id,
            "inboundCallerIdentity": inbound,
            "linkingState": "InProgress" if failure == "pending-" + action else "Succeeded",
            "serviceAddress": "owned.api.adu.microsoft.com",
        }
        return output({**namespace, "properties": {
            "provisioningState": "Succeeded", "updating": {"endpoints": {"su-primary": endpoint}},
        }})

    scenario.create_owned_resource.side_effect = create
    scenario.cmd.side_effect = invoke
    if failure:
        with pytest.raises(AssertionError if failure.startswith(("pending-", "preauthorized")) else HttpResponseError):
            subject.TestADRLinkSU.test_adr_link_su_lifecycle(scenario)
    else:
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(scenario)
    expected_calls = 0 if failure == "role-read" else 1 if failure in {
        "add", "pending-add", "preauthorized-sami", "discovery",
    } else 2
    assert len(native_commands) == expected_calls
    if failure is None:
        assert role_observations == [
            ("namespace-sami", "Contributor", su_id, False),
            ("su-uami", "Azure Device Registry Contributor", namespace_id, False),
            ("namespace-sami", "Contributor", su_id, True),
            ("su-uami", "Azure Device Registry Contributor", namespace_id, True),
            ("su-sami", "Azure Device Registry Contributor", namespace_id, False),
            ("namespace-sami", "Contributor", su_id, True),
            ("su-sami", "Azure Device Registry Contributor", namespace_id, True),
        ]
    scenario.assign_role.assert_called_once_with("caller", "Device Update Reader", su_id, assignee_type=None)
    manager.ensure.assert_not_called()
    manager.ensure_many.assert_not_called()
    waits.assert_not_called()
    sleep.assert_not_called()
    scenario.cleanup_full_infra.assert_called_once()


@pytest.mark.parametrize("scenario", [
    subject.TestADRLinkSequentialAdd.test_adr_link_sequential_add,
    subject.TestADRLinkSU.test_adr_link_su_lifecycle,
])
def test_fresh_link_scenarios_do_not_import_fixture_service_role_recovery(scenario):
    import inspect

    source = inspect.getsource(scenario)
    assert ".ensure(" not in source and ".ensure_many(" not in source
    assert "_ROLE_SETTLE_SECONDS" not in source
    assert "link_dps_with_readiness(" not in source and "link_hub_with_readiness(" not in source
    assert "_NATIVE_LINK_OPTIONS" in source
