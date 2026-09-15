# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
import requests
from azure.cli.core.azclierror import AzureResponseError, RequiredArgumentMissingError
from knack.util import CLIError

from azext_iot.adr.rbac import (
    ADU_FIRST_PARTY_APP_ID,
    GRAPH_SERVICE_PRINCIPALS_URL,
    LinkRbacManager,
)
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
    test.cli_ctx = SimpleNamespace(cloud=SimpleNamespace(
        endpoints=SimpleNamespace(microsoft_graph_resource_id="https://graph.microsoft.com"),
    ))
    response = Mock()
    response.json.return_value = {"value": [{"id": "adu-principal"}]}
    manager = LinkRbacManager(test.cli_ctx, cli=Mock(), graph_get=Mock(return_value=response))
    manager._access_token = Mock(return_value="test-token")
    monkeypatch.setattr(subject, "LinkRbacManager", Mock(return_value=manager))
    monkeypatch.setattr(subject, "TEST_SUBSCRIPTION", "configured-sub")
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", "")
    return test, manager, response


@pytest.mark.parametrize("fixture_id,subscription", [("", "configured-sub"), (SU_ID, "fixture-sub")])
@pytest.mark.parametrize("error_type", [requests.HTTPError, requests.Timeout])
def test_su_graph_failure_precedes_all_resource_and_role_mutations(
    preparation, monkeypatch, fixture_id, subscription, error_type,
):
    test, manager, response = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", fixture_id)
    if error_type is requests.HTTPError:
        response.status_code = 403
        error = error_type("403 Client Error: Forbidden", response=response)
        response.raise_for_status.side_effect = error
    else:
        error = error_type("Graph request timed out")
        manager._graph_get.side_effect = error

    with pytest.raises(AzureResponseError, match="Could not query Microsoft Graph") as failure:
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert failure.value.__cause__ is error
    manager._access_token.assert_called_once_with(
        subscription, resource="https://graph.microsoft.com",
    )
    assert manager._graph_get.call_args.args == (GRAPH_SERVICE_PRINCIPALS_URL,)
    assert manager._graph_get.call_args.kwargs["params"] == {
        "$filter": f"appId eq '{ADU_FIRST_PARTY_APP_ID}'", "$select": "id",
    }
    assert manager._graph_get.call_args.kwargs["timeout"] == 30
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    manager.cli.invoke.assert_not_called()


def test_su_missing_adu_principal_fails_before_resources(preparation):
    test, manager, response = preparation
    response.json.return_value = {"value": []}

    with pytest.raises(AzureResponseError, match="Could not resolve the ADU first-party"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()
    manager.cli.invoke.assert_not_called()


def test_su_token_failure_fails_before_graph_or_resources(preparation):
    test, manager, _ = preparation
    manager._access_token.side_effect = AzureResponseError("Could not acquire an access token")

    with pytest.raises(AzureResponseError, match="Could not acquire an access token"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    manager._graph_get.assert_not_called()
    test.cmd.assert_not_called()
    test.assign_role.assert_not_called()


def test_su_successful_graph_preparation_precedes_provisioning(preparation):
    test, manager, response = preparation
    events = []

    def graph_get(*_args, **_kwargs):
        events.append("graph")
        return response

    def command(value):
        events.append(value)
        if value.startswith("identity show "):
            raise CLIError("ResourceNotFound (404)")
        if value.startswith("identity create "):
            raise RuntimeError("Stop at the first provisioning command")
        return Mock(get_output_in_json=lambda: [])

    manager._graph_get.side_effect = graph_get
    test.cmd.side_effect = command

    with pytest.raises(RuntimeError, match="Stop at the first provisioning command"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    assert events[0] == "graph"
    assert events[1].startswith("identity show ")
    assert events[2].startswith("identity create ")
    assert manager._adu_principal_ids == {"configured-sub": "adu-principal"}
    manager._graph_get.assert_called_once()


def test_su_borrowed_fixture_is_not_deleted_on_setup_failure(preparation, monkeypatch):
    test, manager, _ = preparation
    monkeypatch.setattr(subject, "_SU_UPDATE_INSTANCE_ID", SU_ID)
    manager._current_assignee_object_id = Mock(return_value="caller")

    test.cmd.side_effect = RuntimeError("fixture lookup failed")
    with pytest.raises(RuntimeError, match="fixture lookup failed"):
        subject.TestADRLinkSU.test_adr_link_su_lifecycle(test)

    manager._graph_get.assert_called_once()
    assert test.cmd.call_count == 1
    assert test.cmd.call_args.args[0] == f"resource show --ids {SU_ID}"
    assert test._owned_resources == {}


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
    monkeypatch.setattr(subject, "wait_for_resource_succeeded", provisioned)

    outputs = []
    commands = []
    if not supplied:
        outputs.extend([
            CLIError("ResourceNotFound (404)"), Mock(get_output_in_json=lambda: {"id": requested_id}),
            CLIError("ResourceNotFound (404)"), Mock(),
        ])
        commands.extend([
            call("identity show -n owned-uami -g rg"),
            call(f"identity create -n owned-uami -g rg --location {subject.TEST_LOCATION}"),
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
        outputs.extend(Mock() for _ in range(4))
        commands.extend([
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
        provisioned.assert_called_once_with(
            test, "iot adr ns su instance show -n testsuowned123 -g rg",
            max_polls=subject.SU_PROVISIONING_MAX_POLLS,
            poll_interval=subject.SU_PROVISIONING_POLL_INTERVAL,
        )


def test_owned_identity_regression_rejects_unexpected_scenario_skip(preparation, monkeypatch):
    def incorrect_skip(_self):
        pytest.skip("supplied-fixture skip")

    monkeypatch.setattr(subject.TestADRLinkSU, "test_adr_link_su_lifecycle", incorrect_skip)
    with pytest.raises(pytest.fail.Exception, match="Owned update instance identity failure was incorrectly skipped"):
        test_su_identity_prerequisites_distinguish_owned_resources(
            preparation, monkeypatch, False, "missing_sami",
        )
