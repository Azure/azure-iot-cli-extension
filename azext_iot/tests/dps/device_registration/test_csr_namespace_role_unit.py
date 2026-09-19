# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exact, test-owned namespace SAMI grant, native wire contract and quarantine."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from azure.cli.command_modules.role import custom as role_commands
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import HttpTransport
from azure.mgmt.authorization import AuthorizationManagementClient

from azext_iot.tests.adr import test_adr_validation_scenarios_unit as cli_tests
from azext_iot.tests.dps import _csr_issuance as csr, _csr_registry as registry
from azext_iot.tests.dps.device_registration import test_csr_issuance_fixture_unit as fixture_tests
from azext_iot.tests.dps.device_registration.test_registry_assertions_unit import _Response

scope = fixture_tests.scope
resource = fixture_tests.resource
namespace_commands = fixture_tests.namespace_commands
offline_cli = cli_tests.offline_cli


@pytest.fixture
def owned(namespace_commands, resource, scope, mocker):
    name = resource["namespace"]
    csr.receipts.before_create(name, "rg", fixture_tests.UID, "csrns")
    record = csr.receipts._owned(name)
    namespace_commands.resources["namespace"] = {
        "id": record["id"], "name": name, "tags": record["tags"], "properties": {"provisioningState": "Succeeded"},
        "identity": {"type": "SystemAssigned", "principalId": fixture_tests.NAMESPACE_PRINCIPAL},
    }
    original_wait = csr.wait_for_condition

    def wait(fetch, success, **kwargs):
        kwargs["timeout"] = 0
        return original_wait(fetch, success, **kwargs)

    mocker.patch.object(csr, "wait_for_condition", side_effect=wait)
    return SimpleNamespace(
        backend=namespace_commands, name=name, record=record,
        receipt=scope / csr.NAMESPACE_ROLE_RECEIPT,
    )


def claim(owned):
    return json.loads(owned.receipt.read_text(encoding="utf-8"))


def test_native_cli_preserves_prejournaled_guid_scope_principal_and_exact_delete(
    owned, offline_cli, mocker,
):
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline-token", 4102444800)))
    transport, calls, state = MagicMock(spec=HttpTransport), [], {}
    mocker.patch("azext_iot.common.embedded_cli.get_default_cli", return_value=offline_cli)
    embedded = csr.EmbeddedCLI(cli_ctx=offline_cli)
    mocker.patch.object(csr.fixtures, "cli", embedded)
    mocker.patch.object(
        csr, "invoke", side_effect=lambda command: csr.invoke_checked(embedded, command, description="Owned CSR role"),
    )
    mocker.patch.object(role_commands, "_get_object_stubs", side_effect=AssertionError("Graph lookup is forbidden"))
    mocker.patch.object(role_commands, "_gen_guid", side_effect=AssertionError("Do not replace the owned GUID"))

    def send(request, **_kwargs):
        parsed = urlsplit(request.url)
        calls.append((request.method, parsed.path))
        assert parsed.hostname == "centraluseuap.management.azure.com"
        assert parse_qs(parsed.query) == {"api-version": ["2022-04-01"]}
        assert parsed.path.startswith(owned.record["id"] + "/providers/Microsoft.Authorization/roleAssignments/")
        status, payload = 200, state.get(parsed.path)
        if request.method == "PUT":
            journal = claim(owned)
            assert journal["id"] == parsed.path and journal["verified"] is False
            assert str(UUID(journal["name"])) == parsed.path.rsplit("/", 1)[-1]
            properties = json.loads(request.body)["properties"]
            assert properties == {
                "principalId": fixture_tests.NAMESPACE_PRINCIPAL, "principalType": "ServicePrincipal",
                "roleDefinitionId": (
                    f"/subscriptions/{fixture_tests.SUB}/providers/Microsoft.Authorization/roleDefinitions/"
                    "b24988ac-6180-42a0-ab88-20f7382dd24c"
                ),
            }
            payload = {
                "id": parsed.path, "name": journal["name"], "type": "Microsoft.Authorization/roleAssignments",
                "properties": {**properties, "scope": owned.record["id"]},
            }
            state[parsed.path] = payload
            status = 201
        elif request.method == "DELETE":
            assert claim(owned)["delete_attempted"] is True
            del state[parsed.path]
            status = 204
        else:
            assert request.method == "GET"
            if payload is None:
                status, payload = 404, {"error": {"code": "RoleAssignmentNotFound", "message": "Not found"}}
        response = _Response(request, payload)
        response.status_code = status
        return response

    transport.send.side_effect = send
    with csr.runtime.activate(fixture_tests.SUB, existing=(embedded,)):
        with AuthorizationManagementClient(credential, fixture_tests.SUB, transport=transport) as client:
            mocker.patch.object(csr, "_auth_client_factory", return_value=client)
            mocker.patch.object(role_commands, "_auth_client_factory", return_value=client)
            csr._grant_namespace_self_role(owned.name)
            csr._remove_namespace_self_role(owned.name)
    journal = claim(owned)
    assert journal["verified"] and journal["deleted"]
    assert [method for method, _ in calls] == ["GET", "PUT", "GET", "GET", "DELETE", "GET"]
    assert {path for _, path in calls} == {journal["id"]}
    assert len(list(owned.receipt.parent.glob("mutation-*.json"))) == 2
    assert not state
    assert offline_cli.cloud.endpoints.resource_manager == "https://management.azure.com/"


@pytest.mark.parametrize("elapsed,remaining", [(0, 60), (45, 15), (60, 0), (90, 0)])
def test_existing_setup_consumes_propagation_floor(namespace_commands, resource, mocker, elapsed, remaining):
    mocker.patch.object(csr, "monotonic", side_effect=[100, 100 + elapsed])
    csr._create_namespace(fixture_tests.UID, "csrns", resource["dps"], resource["hub"])
    if remaining:
        csr.sleep.assert_called_once_with(remaining)
    else:
        csr.sleep.assert_not_called()
    assert sum(command.startswith("role assignment create ") for command in namespace_commands.commands) == 1


def test_grant_reads_fresh_owned_namespace_identity_and_cannot_replay(owned, mocker):
    principal = "12345678-1234-1234-1234-123456789abc"
    owned.backend.resources["namespace"]["identity"]["principalId"] = principal
    read = mocker.patch.object(
        csr, "find_namespace", side_effect=lambda _name: owned.backend.resources.get("namespace"),
    )
    csr._grant_namespace_self_role(owned.name)
    assert claim(owned)["principalId"] == principal
    read.assert_called_once_with(owned.name)
    with pytest.raises(RuntimeError, match="repeat recorded mutation"):
        csr._grant_namespace_self_role(owned.name)
    assert len(owned.backend.commands) == 1
    csr._remove_namespace_self_role(owned.name)
    assert not owned.backend.roles


@pytest.mark.parametrize("change", ["type", "principal", "tags", "state"])
def test_invalid_namespace_cannot_authorize_grant(owned, change):
    namespace = owned.backend.resources["namespace"]
    if change == "type":
        namespace["identity"]["type"] = "UserAssigned"
    elif change == "principal":
        namespace["identity"]["principalId"] = "not-a-principal-uuid"
    elif change == "tags":
        namespace["tags"] = {}
    else:
        namespace["properties"]["provisioningState"] = "Accepted"
    with pytest.raises((AssertionError, ValueError)):
        csr._grant_namespace_self_role(owned.name)
    assert not owned.receipt.exists() and not owned.backend.commands


def test_preexisting_assignment_guid_is_not_adopted(owned, mocker):
    guid = "12345678-1234-1234-1234-123456789abc"
    mocker.patch.object(csr, "uuid4", return_value=UUID(guid))
    assignment_id = owned.record["id"] + "/providers/Microsoft.Authorization/roleAssignments/" + guid
    owned.backend.roles[assignment_id] = {
        **csr._namespace_role_binding(owned.record, fixture_tests.NAMESPACE_PRINCIPAL), "name": guid, "id": assignment_id,
    }
    with pytest.raises(AssertionError, match="existing namespace role"):
        csr._grant_namespace_self_role(owned.name)
    assert not owned.receipt.exists() and not owned.backend.commands


@pytest.mark.parametrize("reply", [None, {}, {"id": 123}, {"id": "/foreign/assignment"}])
def test_native_conflicting_reply_quarantines_without_foreign_deletion(owned, mocker, reply):
    invoke = mocker.patch.object(csr, "invoke", return_value=SimpleNamespace(as_json=lambda: reply))
    with pytest.raises(AssertionError, match="journaled binding"):
        csr._grant_namespace_self_role(owned.name)
    assert claim(owned)["conflicted"]
    with pytest.raises(AssertionError, match="Conflicting namespace role"):
        csr.delete_namespace(owned.name)
    assert "namespace" in owned.backend.resources
    invoke.assert_called_once()


@pytest.mark.parametrize("field,value", [
    ("id", "/foreign"), ("name", "12345678-1234-1234-1234-123456789abc"), ("scope", "/subscriptions/foreign"),
    ("principalId", "12345678-1234-1234-1234-123456789abc"), ("principalType", "User"),
    ("roleDefinitionId", "/providers/Microsoft.Authorization/roleDefinitions/foreign"),
    ("run_uid", "b" * 32), ("subscription", "other"), ("phase", "service-sas"),
    ("verified", "true"), ("delete_attempted", None), ("deleted", None), ("conflicted", True),
])
def test_damaged_receipt_never_authorizes_role_or_namespace_delete(owned, field, value):
    csr._grant_namespace_self_role(owned.name)
    csr.receipts.write(csr.NAMESPACE_ROLE_RECEIPT, {**claim(owned), field: value})
    with pytest.raises(AssertionError):
        csr.delete_namespace(owned.name)
    assert len(owned.backend.commands) == 1 and owned.backend.roles
    assert "namespace" in owned.backend.resources


@pytest.mark.parametrize("field", ["id", "name", "scope", "principalId", "principalType", "roleDefinitionId"])
def test_fresh_assignment_binding_change_is_not_deleted(owned, field):
    csr._grant_namespace_self_role(owned.name)
    owned.backend.roles[claim(owned)["id"]][field] = "foreign"
    with pytest.raises(AssertionError, match="binding changed"):
        csr.delete_namespace(owned.name)
    assert len(owned.backend.commands) == 1 and "namespace" in owned.backend.resources


def test_replaced_namespace_identity_blocks_cleanup(owned):
    csr._grant_namespace_self_role(owned.name)
    owned.backend.resources["namespace"]["identity"]["principalId"] = "12345678-1234-1234-1234-123456789abc"
    with pytest.raises(AssertionError, match="receipt scope/principal/role changed"):
        csr.delete_namespace(owned.name)
    assert len(owned.backend.commands) == 1


@pytest.mark.parametrize("stage", ["precreate", "grant-readback", "cleanup", "uncertain-create-cleanup"])
@pytest.mark.parametrize("status", [400, 401, 403, 409, 500])
def test_role_http_failures_propagate_without_mutation_retry(owned, stage, status):
    error = HttpResponseError("Role service failure")
    error.status_code = status
    if stage in ("cleanup", "uncertain-create-cleanup"):
        csr._grant_namespace_self_role(owned.name)
        if stage == "uncertain-create-cleanup":
            csr.receipts.write(csr.NAMESPACE_ROLE_RECEIPT, {**claim(owned), "verified": False})
    if stage == "grant-readback":
        original = owned.backend.role_client.role_assignments.get_by_id.side_effect

        def read(assignment_id):
            if assignment_id in owned.backend.roles:
                raise error
            return original(assignment_id)

        owned.backend.role_client.role_assignments.get_by_id.side_effect = read
    else:
        owned.backend.role_client.role_assignments.get_by_id.side_effect = error
    operation = csr._grant_namespace_self_role if stage in ("precreate", "grant-readback") else csr.delete_namespace
    with pytest.raises(HttpResponseError) as raised:
        operation(owned.name)
    assert raised.value is error
    assert not any(" delete " in command for command in owned.backend.commands)
    assert "namespace" in owned.backend.resources


@pytest.mark.parametrize("materialized", [False, True])
def test_uncertain_create_requires_positive_identity_before_cleanup(owned, mocker, materialized):
    error = HttpResponseError("Lost create response")

    def create(command):
        if materialized:
            owned.backend(command)
        raise error

    mocker.patch.object(csr, "invoke", side_effect=create)
    with pytest.raises(HttpResponseError) as raised:
        csr._grant_namespace_self_role(owned.name)
    assert raised.value is error and not claim(owned)["verified"]
    mocker.patch.object(csr, "invoke", side_effect=owned.backend)
    if materialized:
        csr.delete_namespace(owned.name)
        assert claim(owned)["deleted"] and not owned.backend.roles and not owned.backend.resources
    else:
        with pytest.raises(AssertionError, match="uncertain namespace role creation"):
            csr.delete_namespace(owned.name)
        assert "namespace" in owned.backend.resources


def test_grant_visibility_timeout_is_not_registration_permission(owned, mocker):
    missing = HttpResponseError("RoleAssignmentNotFound")
    missing.status_code = 404
    owned.backend.role_client.role_assignments.get_by_id.side_effect = missing
    with pytest.raises(AssertionError, match="Contributor visibility"):
        csr._grant_namespace_self_role(owned.name)
    assert owned.backend.roles and not claim(owned)["verified"]
    assert len(owned.backend.commands) == 1


@pytest.mark.parametrize("materialized", [False, True])
def test_uncertain_delete_is_journaled_and_never_replayed(owned, mocker, materialized):
    csr._grant_namespace_self_role(owned.name)
    error = HttpResponseError("Lost delete response")

    def delete(command):
        assert claim(owned)["delete_attempted"]
        if materialized:
            owned.backend(command)
        raise error

    invoke = mocker.patch.object(csr, "invoke", side_effect=delete)
    with pytest.raises(HttpResponseError) as raised:
        csr._remove_namespace_self_role(owned.name)
    assert raised.value is error
    if materialized:
        csr._remove_namespace_self_role(owned.name)
        assert claim(owned)["deleted"]
    else:
        with pytest.raises(AssertionError, match="role absence"):
            csr.delete_namespace(owned.name)
        assert "namespace" in owned.backend.resources
        owned.backend.roles.clear()
        csr._remove_namespace_self_role(owned.name)
    invoke.assert_called_once()


def test_registration_quarantine_blocks_role_and_namespace_deletion(owned, mocker):
    csr._grant_namespace_self_role(owned.name)
    mocker.patch.object(registry, "cleanup_registry_devices", side_effect=AssertionError("quarantined registration"))
    with pytest.raises(AssertionError, match="quarantined registration"):
        csr.delete_namespace(owned.name)
    assert len(owned.backend.commands) == 1 and owned.backend.roles


@pytest.mark.parametrize("completed", [False, True])
def test_missing_namespace_does_not_abandon_uncompleted_role_cleanup(owned, completed):
    csr._grant_namespace_self_role(owned.name)
    if completed:
        csr._remove_namespace_self_role(owned.name)
    owned.backend.resources.clear()
    if completed:
        csr.delete_namespace(owned.name)
    else:
        with pytest.raises(AssertionError, match="orphan reconciliation"):
            csr.delete_namespace(owned.name)
        assert owned.backend.roles


@pytest.mark.parametrize("namespace_present", [False, True])
def test_reappearing_completed_assignment_cannot_be_deleted_again(owned, namespace_present):
    csr._grant_namespace_self_role(owned.name)
    assignments = deepcopy(owned.backend.roles)
    csr._remove_namespace_self_role(owned.name)
    owned.backend.roles.update(assignments)
    if not namespace_present:
        owned.backend.resources.clear()
    with pytest.raises(AssertionError, match="reappeared|orphan reconciliation"):
        csr.delete_namespace(owned.name)
    assert sum("role assignment delete" in command for command in owned.backend.commands) == 1
