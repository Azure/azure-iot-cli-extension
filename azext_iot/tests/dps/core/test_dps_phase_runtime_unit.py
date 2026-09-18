# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""No Azure: real SDK HTTP pipelines and real tox/xdist with local-only fixtures."""

from contextlib import nullcontext
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import requests
import responses
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ServiceResponseError
from azure.core.pipeline import Pipeline
from azure.core.pipeline.policies import HTTPPolicy
from azure.core.pipeline.transport import RequestsTransport
from azure.core.pipeline.transport import HttpRequest
from filelock import FileLock, Timeout as LockTimeout

from azext_iot import _factory
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.dps import _phase_receipts as receipts, _phase_runtime as runtime
from azext_iot.tests.dps._phase_manifest import resource_type

ROOT = Path(__file__).resolve().parents[4]
RUNNER = runpy.run_path(str(ROOT / "azext_iot/tests/_dps_phase_runner.py"))
SUB_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
UID = "b" * 32
ARM = "https://centraluseuap.management.azure.com"


@pytest.fixture
def scope(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv(receipts.DIRECTORY_ENV, str(tmp_path))
    monkeypatch.setenv(receipts.RUN_UID_ENV, UID)
    monkeypatch.setenv(receipts.SUBSCRIPTION_ENV, SUB_B)
    monkeypatch.setenv(receipts.RESOURCE_GROUP_ENV, "group")
    monkeypatch.setenv("azext_iot_dps_test_phase", "regular")
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("fake-unit-token", 9999999999))
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    return tmp_path


def _client(factory_name):
    cli = EmbeddedCLI()
    return getattr(_factory, factory_name)(cli.az_cli, subscription_id=SUB_B)


def _owned(kind):
    receipts.before_create("owned", "group", UID, kind)
    return ARM + f"/subscriptions/{SUB_B}/resourceGroups/group/providers/{resource_type(kind)}/owned"


@pytest.mark.parametrize("determinant", [False, True])
def test_cleanup_progress_survives_closed_pytest_capture(scope, monkeypatch, determinant):
    from io import StringIO
    from azure.cli.core.commands import progress

    captured = (scope / "captured-stderr").open("w+", encoding="utf-8")
    captured.close()
    current = StringIO()
    original = progress.get_progress_view
    # Azure CLI binds stderr in this function's default argument at import.
    monkeypatch.setattr(original, "__defaults__", (False, captured, None))
    monkeypatch.setattr(sys, "stderr", current)
    assert captured.closed
    assert progress.get_progress_view().out is captured
    with pytest.raises(ValueError, match="closed file"):
        progress.get_progress_view().flush()
    cli = EmbeddedCLI().az_cli
    stale = cli.get_progress_controller(det=determinant)
    assert stale.active_progress.out is captured

    with runtime.activate(SUB_B):
        controller = cli.get_progress_controller(det=determinant)
        assert controller is stale
        view = controller.active_progress
        assert view.out is current
        view.flush()
        explicit = (scope / "explicit-output").open("w+", encoding="utf-8")
        view = progress.get_progress_view(outstream=explicit)
        assert view.out is explicit
        view.flush()
        explicit.close()
        # Explicitly invalid streams remain errors; the scope must not swallow them.
        with pytest.raises(ValueError, match="closed file"):
            view.flush()
    assert progress.get_progress_view is original
    assert not current.closed


@responses.activate
@pytest.mark.parametrize("factory_name,kind", [
    ("iot_hub_service_factory", "hub"), ("adr_iot_hub_service_factory", "hub"),
    ("iot_service_provisioning_factory", "nh"), ("adr_iot_service_provisioning_factory", "nh"),
    ("adr_service_factory", "csrns"),
])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_real_factory_pipeline_never_resends_uncertain_owned_mutation(scope, factory_name, kind, method, failure):
    url = _owned(kind)
    if failure == "read-timeout":
        responses.add(method, url, body=requests.exceptions.ReadTimeout("synthetic timeout after acceptance"))
    else:
        responses.add(method, url, status=504, json={"error": {"code": "GatewayTimeout"}})
    responses.add(method, url, status=200, json={})  # A forbidden retry would consume this and appear successful.
    with runtime.activate(SUB_B):
        client = _client(factory_name)
        with runtime.owned_write("owned", method):
            if failure == "read-timeout":
                with pytest.raises(ServiceResponseError):
                    client.send_request(HttpRequest(method, url))
            else:
                assert client.send_request(HttpRequest(method, url)).status_code == 504
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("command,method,child,allowed", [
    ("iot adr ns link add", "PATCH", "", True),
    ("iot adr ns link dps update", "PATCH", "", True),
    ("iot adr ns link hub add", "PATCH", "", True),
    ("iot adr ns update", "PATCH", "", False),
    ("iot adr ns link add", "PUT", "", False),
    ("iot adr ns link add", "PATCH", "/certificateAuthorities/ca", False),
])
def test_native_link_can_submit_distinct_namespace_updates_without_allowing_other_command_replay(
    scope, mocker, command, method, child, allowed,
):
    url = _owned("csrns") + child
    responses.add(method, url, json={})
    responses.add(method, url, json={})

    def native_invoke(self, _command, **_kwargs):
        client = _factory.adr_service_factory(self.az_cli, subscription_id=SUB_B)
        client.send_request(HttpRequest(method, url))
        client.send_request(HttpRequest(method, url))

    mocker.patch.object(EmbeddedCLI, "invoke", native_invoke)
    with runtime.activate(SUB_B):
        with nullcontext() if allowed else pytest.raises(runtime.ScopeError, match="replay"):
            EmbeddedCLI().invoke(command)
    assert len(responses.calls) == (2 if allowed else 1)
    assert not runtime._LINK_COMMAND.get()


@responses.activate
def test_transport_fence_blocks_policy_resends_but_allows_distinct_later_updates(scope):
    url = _owned("nh")
    responses.add(responses.PUT, url, json={})
    responses.add(responses.PUT, url, status=504)
    responses.add(responses.PUT, url, json={})
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        with runtime.owned_write("owned", "PUT"):
            client.send_request(HttpRequest("PUT", url))
            with pytest.raises(runtime.ScopeError, match="replay"):
                client.send_request(HttpRequest("PUT", url))
        assert len(responses.calls) == 1
        # A later logical operation is fenced too: 504 must NOT consume the 200.
        assert client.send_request(HttpRequest("PUT", url)).status_code == 504
        assert len(responses.calls) == 2
        # Only an explicitly separate operation may consume the next response.
        assert client.send_request(HttpRequest("PUT", url)).status_code == 200
    assert len(responses.calls) == 3


def _real_cli(mocker, loader_cls=None):
    from azure.cli.core import MainCommandsLoader
    from azure.cli.core._profile import Profile
    from azext_iot import IoTExtCommandsLoader

    mocker.patch.object(Profile, "get_subscription", autospec=True, side_effect=lambda _self, subscription=None: {
        "id": subscription or SUB_A, "name": "offline", "tenantId": SUB_A,
        "user": {"name": SUB_A, "type": "servicePrincipal"}, "environmentName": "AzureCloud",
    })
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("fake-unit-token", 9999999999))
    mocker.patch.object(Profile, "get_login_credentials", return_value=(credential, SUB_B, SUB_A))

    class LocalExtensionLoader(MainCommandsLoader):
        def load_command_table(self, args):
            extension = (loader_cls or IoTExtCommandsLoader)(cli_ctx=self.cli_ctx)
            self.command_table.update(extension.load_command_table(args))
            self.cmd_to_loader_map.update({name: [extension] for name in self.command_table})
            return self.command_table

    cli = EmbeddedCLI(capture_stderr=True)
    # Deterministic local discovery; the main loader's argument reflection,
    # parser, validators, handlers, factories and SDK transports are all real.
    cli.az_cli.commands_loader_cls = LocalExtensionLoader
    cli.az_cli.data["subscription_id"] = SUB_A
    cli.user_subscription = SUB_A
    return cli


@responses.activate
@pytest.mark.parametrize("receipt_mode,outcome", [
    (mode, outcome) for mode in (False, True)
    for outcome in ("ready", "exists", "denied", "conflict", "read-denied")
] + [(True, "uncertain")])
def test_native_known_object_role_grant_never_queries_graph(scope, mocker, monkeypatch, receipt_mode, outcome):
    from azure.cli.command_modules.role import RoleCommandsLoader, custom as role_commands
    from azure.cli.command_modules.role._msgrpah import GraphClient
    from azext_iot.tests import helpers
    from azext_iot.tests.dps import conftest as fixtures

    owned = _owned("hub").removeprefix(ARM)
    if not receipt_mode:
        for name in (receipts.DIRECTORY_ENV, receipts.RUN_UID_ENV, receipts.SUBSCRIPTION_ENV, receipts.RESOURCE_GROUP_ENV):
            monkeypatch.delenv(name)
    cli = _real_cli(mocker, RoleCommandsLoader)
    cli.user_subscription = SUB_B
    mocker.patch.object(helpers, "cli", cli)
    mocker.patch.object(helpers, "sleep")
    mocker.patch.object(runtime, "sleep")
    graph = mocker.patch.object(GraphClient, "_send", side_effect=AssertionError("Graph must not be queried"))
    resolve = mocker.patch.object(
        role_commands, "_resolve_object_id_and_type", side_effect=AssertionError("Known object ID must not be resolved"),
    )
    resolve_type = mocker.patch.object(
        role_commands, "_get_principal_type_from_object_id", side_effect=AssertionError("Known type must not be resolved"),
    )
    assignment_name = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    role_id = f"/subscriptions/{SUB_B}/providers/Microsoft.Authorization/roleDefinitions/dddddddd-dddd-dddd-dddd-dddddddddddd"
    mocker.patch.object(role_commands, "_gen_guid", return_value=assignment_name)
    base = ARM if receipt_mode else "https://management.azure.com"
    assignments = base + owned + "/providers/Microsoft.Authorization/roleAssignments"
    target = assignments + "/" + assignment_name
    resource = {
        "id": target.removeprefix(base), "name": assignment_name,
        "properties": {"scope": owned, "principalId": SUB_A, "principalType": "ServicePrincipal",
                       "roleDefinitionId": role_id},
    }
    responses.add("GET", base + owned + "/providers/Microsoft.Authorization/roleDefinitions", json={
        "value": [{"id": role_id, "properties": {"roleName": fixtures.HUB_USER_ROLE}}],
    })
    if outcome == "read-denied":
        responses.add("GET", assignments, status=403, json={"error": {"code": "AuthorizationFailed"}})
    else:
        responses.add("GET", assignments, json={"value": []})
        if outcome == "ready":
            responses.add("PUT", target, json=resource)
            responses.add("GET", assignments, json={"value": []})
        elif outcome == "uncertain":
            responses.add("PUT", target, status=504, json={"error": {"code": "GatewayTimeout"}})
            responses.add("PUT", target, json=resource)  # An illicit SDK retry would consume this.
        else:
            code = {"exists": "RoleAssignmentExists", "denied": "AuthorizationFailed", "conflict": "Conflict"}[outcome]
            responses.add("PUT", target, status=403 if outcome == "denied" else 409, json={
                "error": {"code": code, "message": "synthetic role response"},
            })
        responses.add("GET", assignments, json={"value": [resource]})
    original_list = role_commands.list_role_assignments
    with runtime.activate(SUB_B, existing=(cli,)) if receipt_mode else nullcontext():
        with pytest.raises(HttpResponseError) if outcome in ("denied", "conflict", "read-denied", "uncertain") else nullcontext():
            fixtures._assign_fixture_role(
                role=fixtures.HUB_USER_ROLE, scope=owned, assignee_object_id=SUB_A,
                assignee_principal_type="ServicePrincipal", max_tries=3, wait=0,
            )
    assert role_commands.list_role_assignments is original_list  # No leaked override, including error exits.
    graph.assert_not_called()
    resolve.assert_not_called()
    resolve_type.assert_not_called()
    puts = [call for call in responses.calls if call.request.method == "PUT"]
    assert len(puts) == (0 if outcome == "read-denied" else 1)
    if puts:
        properties = json.loads(puts[0].request.body)["properties"]
        assert properties["principalId"] == SUB_A
        assert properties["principalType"] == "ServicePrincipal"
        assert properties["roleDefinitionId"] == role_id
        assert puts[0].request.url.startswith(target + "?")
    if outcome == "ready":
        assert len([call for call in responses.calls if call.request.url.startswith(assignments)
                    and call.request.method == "GET"]) == 3  # One create, then read-only visibility retries.
    assert all(call.request.url.startswith(base + f"/subscriptions/{SUB_B}/") for call in responses.calls)


@responses.activate
@pytest.mark.parametrize("known_principal", [False, True])
@pytest.mark.parametrize("confirmation", [
    "visible", "empty", "wrong-principal", "wrong-role", "parent-scope", "child-scope", "read-denied",
])
def test_native_duplicate_empty_fallback_requires_exact_bounded_confirmation(scope, mocker, known_principal, confirmation):
    from azure.cli.command_modules.role import RoleCommandsLoader, custom as role_commands
    from azure.cli.command_modules.role._msgrpah import GraphClient
    from azext_iot.tests import helpers
    from azext_iot.tests.dps import conftest as fixtures

    owned = _owned("hub").removeprefix(ARM)
    cli = _real_cli(mocker, RoleCommandsLoader)
    mocker.patch.object(helpers, "cli", cli)
    pause = mocker.patch.object(runtime, "sleep")
    graph = mocker.patch.object(GraphClient, "_send", side_effect=AssertionError("No principal-name hydration"))
    resolve = mocker.patch.object(role_commands, "_resolve_object_id_and_type", return_value=(SUB_A, "ServicePrincipal"))
    alias_read = mocker.patch.object(role_commands, "_resolve_object_id", return_value=SUB_A)
    assignment_name = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    role_id = f"/subscriptions/{SUB_B}/providers/Microsoft.Authorization/roleDefinitions/dddddddd-dddd-dddd-dddd-dddddddddddd"
    mocker.patch.object(role_commands, "_gen_guid", return_value=assignment_name)
    assignments = ARM + owned + "/providers/Microsoft.Authorization/roleAssignments"
    target = assignments + "/" + assignment_name
    resource = {
        "id": target.removeprefix(ARM), "name": assignment_name,
        "properties": {"scope": owned, "principalId": SUB_A, "principalType": "ServicePrincipal",
                       "roleDefinitionId": role_id},
    }
    responses.add("GET", ARM + owned + "/providers/Microsoft.Authorization/roleDefinitions", json={
        "value": [{"id": role_id, "properties": {"roleName": fixtures.HUB_USER_ROLE}}],
    })
    # Worker preflight and native CLI's immediate fallback both miss the grant.
    responses.add("GET", assignments, json={"value": []})
    responses.add("PUT", target, status=409, json={
        "error": {"code": "RoleAssignmentExists", "message": "synthetic existing assignment"},
    })
    responses.add("GET", assignments, json={"value": []})
    responses.add("GET", assignments, json={"value": []})  # First read-only confirmation is still too early.
    properties = resource["properties"]
    if confirmation == "wrong-principal":
        properties["principalId"] = SUB_B
    elif confirmation == "wrong-role":
        properties["roleDefinitionId"] = role_id.replace("dddddddd", "eeeeeeee")
    elif confirmation == "parent-scope":
        properties["scope"] = owned.split("/providers/")[0]
    elif confirmation == "child-scope":
        properties["scope"] = owned + "/children/child"
    if confirmation == "read-denied":
        responses.add("GET", assignments, status=403, json={"error": {"code": "AuthorizationFailed"}})
    else:
        responses.add("GET", assignments, json={"value": [] if confirmation == "empty" else [resource]})
    arguments = {"assignee_object_id": SUB_A, "assignee_principal_type": "ServicePrincipal"} if known_principal else {
        "assignee": "caller-app-id",
    }
    original_list = role_commands.list_role_assignments
    expected = HttpResponseError if confirmation == "read-denied" else runtime.ScopeError
    with runtime.activate(SUB_B, existing=(cli,)):
        with nullcontext() if confirmation == "visible" else pytest.raises(expected) as raised:
            runtime.assign_role_assignment_once(
                role=fixtures.HUB_USER_ROLE, scope=owned, max_tries=2, wait=3, **arguments,
            )
    if confirmation not in ("visible", "read-denied"):
        assert isinstance(raised.value.__cause__, runtime._RoleAssignmentPending)
        duplicate = raised.value.__cause__.__cause__
        assert duplicate.status_code == 409
        assert duplicate.error.code == "RoleAssignmentExists"
    assert role_commands.list_role_assignments is original_list
    assert resolve.call_count == (0 if known_principal else 1)
    assert alias_read.call_count == (0 if known_principal else 1)
    graph.assert_not_called()
    assert pause.call_args_list == [mocker.call(3), mocker.call(3)]
    puts = [call for call in responses.calls if call.request.method == "PUT"]
    assert len(puts) == 1
    assert json.loads(puts[0].request.body)["properties"]["principalId"] == SUB_A
    assert len([call for call in responses.calls if call.request.url.startswith(assignments)
                and call.request.method == "GET"]) == 4  # Original bound plus native fallback, not an extra retry loop.
    assert all(call.request.url.startswith(ARM + f"/subscriptions/{SUB_B}/") for call in responses.calls)
    assert len(list(scope.glob("mutation-*.json"))) == 1


def _arm_resources(url):
    hub_url = _owned("hub")
    host = "owned.azure-devices.net"
    resource = {
        "id": url.removeprefix(ARM), "name": "owned", "location": "centraluseuap",
        "sku": {"name": "S1", "capacity": 1}, "identity": {"type": "SystemAssigned"},
        "properties": {"provisioningState": "Succeeded", "disableLocalAuth": False, "iotHubs": [
            {"name": host, "hostName": host, "authenticationType": "KeyBased", "connectionString": "synthetic"},
        ]},
    }
    responses.add("GET", url, json=resource)
    responses.add("HEAD", ARM + f"/subscriptions/{SUB_B}/resourcegroups/group", status=204)
    responses.add("POST", ARM + f"/subscriptions/{SUB_B}/providers/Microsoft.Devices/checkNameAvailability",
                  json={"nameAvailable": False, "reason": "AlreadyExists"})
    responses.add("GET", hub_url, json={
        "id": hub_url.removeprefix(ARM), "name": "owned", "location": "centraluseuap",
        # The ADR branch's existing KeyBased helper requires this legacy field.
        # This synthetic response exercises the write guard, not RP response capability.
        "resourcegroup": "group",
        "properties": {"hostName": host, "deviceHostName": host},
    })
    responses.add("POST", hub_url + "/IotHubKeys/iothubowner/listkeys", json={
        "keyName": "iothubowner", "primaryKey": "eA==",
    })
    return resource


@responses.activate
@pytest.mark.parametrize("command", [
    "identity assign --system-assigned",
    "linked-hub create --hub-name owned --hub-resource-group group --authentication-type KeyBased",
    "linked-hub create --hub-name owned --hub-resource-group group --authentication-type SystemAssigned",
    "linked-hub update --hub-name owned --authentication-type SystemAssigned",
    "linked-hub delete --linked-hub owned.azure-devices.net",
])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_real_cli_later_identity_and_link_writes_are_not_replayed(scope, mocker, command, failure):
    url = _owned("nh")
    resource = _arm_resources(url)
    cli = _real_cli(mocker)
    if failure == "read-timeout":
        responses.add("PUT", url, body=requests.exceptions.ReadTimeout("synthetic accepted write timeout"))
    else:
        responses.add("PUT", url, status=504, json={"error": {"code": "GatewayTimeout", "message": "synthetic"}})
    responses.add("PUT", url, json=resource)
    with runtime.activate(SUB_B, existing=(cli,)):
        name_option = "--name" if command.startswith("identity") else "--dps-name"
        with pytest.raises((HttpResponseError, ServiceResponseError)):
            cli.invoke(f"iot dps {command} {name_option} owned -g group")
        writes = [call for call in responses.calls if call.request.method == "PUT"]
        assert len(writes) == 1
        body = json.loads(writes[0].request.body)
        if command.startswith("identity"):
            assert body["identity"]["type"] == "SystemAssigned"
        elif command.startswith("linked-hub delete"):
            assert body["properties"]["iotHubs"] == []
        else:
            link = body["properties"]["iotHubs"][-1]
            if "SystemAssigned" in command:
                assert link["authenticationType"] == "SystemAssigned"
            else:
                assert link["connectionString"].startswith("HostName=")
        # No leaked boundary on exception, even on a separate CLI instance. The
        # new explicit command is NOT an automatic retry of the failed command.
        other = EmbeddedCLI(capture_stderr=True)
        other.az_cli.commands_loader_cls = cli.az_cli.commands_loader_cls
        other.invoke("iot dps identity assign --name owned -g group --system-assigned")
        assert other.success()
    assert len([call for call in responses.calls if call.request.method == "PUT"]) == 2
    assert all(call.request.url.startswith(ARM + f"/subscriptions/{SUB_B}/") for call in responses.calls)
    assert len(list(scope.glob("mutation-*.json"))) == 2
    assert cli.user_subscription == SUB_A


@responses.activate
@pytest.mark.parametrize("method", ["PUT", "DELETE", "POST"])
def test_pipeline_context_fence_rejects_policy_reentry_above_retry_policy(scope, method):
    class ReenterPolicy(HTTPPolicy):
        def send(self, request):
            self.next.send(request)
            return self.next.send(request)

    url = _owned("nh") + "/certificates/unit"
    responses.add(method, url, json={})
    transport = runtime.ScopedTransport(RequestsTransport(), SUB_B)
    pipeline = Pipeline(transport, policies=[ReenterPolicy(), runtime.OwnedRetryPolicy()])
    with pytest.raises(runtime.ScopeError, match="repeated ARM mutation"):
        pipeline.run(HttpRequest(method, url))
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_actual_cli_authorization_factory_fences_owned_role_assignment_writes(scope, mocker, method, failure):
    from azure.cli.command_modules.role._client_factory import _auth_client_factory
    from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
    owned = _owned("nh").removeprefix(ARM)
    url = ARM + owned + f"/providers/Microsoft.Authorization/roleAssignments/{SUB_A}"
    cli = _real_cli(mocker)
    if failure == "read-timeout":
        responses.add(method, url, body=requests.exceptions.ReadTimeout("synthetic accepted role write timeout"))
    else:
        responses.add(method, url, status=504, json={"error": {"code": "GatewayTimeout"}})
    responses.add(method, url, json={"id": url.removeprefix(ARM), "properties": {"principalId": SUB_A}})
    with runtime.activate(SUB_B, existing=(cli,)):
        client = _auth_client_factory(cli.az_cli, scope=owned)

        def operation():
            if method == "DELETE":
                return client.role_assignments.delete(owned, SUB_A)
            return client.role_assignments.create(owned, SUB_A, RoleAssignmentCreateParameters(
                role_definition_id=f"/subscriptions/{SUB_B}/providers/Microsoft.Authorization/roleDefinitions/{SUB_A}",
                principal_id=SUB_A,
            ))

        with pytest.raises((HttpResponseError, ServiceResponseError)):
            operation()
        assert len(responses.calls) == 1
        operation()
    assert len(responses.calls) == 2
    assert cli.az_cli.cloud.endpoints.resource_manager == "https://management.azure.com/"
    assert all(call.request.url.startswith(url) for call in responses.calls)


@responses.activate
@pytest.mark.parametrize("method,suffix", [
    ("PUT", "/certificates/unit"), ("DELETE", "/certificates/unit"),
    ("POST", "/certificates/unit/generateVerificationCode"), ("POST", "/certificates/unit/verify"),
    ("PATCH", ""),
])
def test_owned_children_and_actions_each_have_fresh_no_retry_boundary(scope, method, suffix):
    url = _owned("nh") + suffix
    responses.add(method, url, status=504)
    responses.add(method, url, json={})
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        assert client.send_request(HttpRequest(method, url)).status_code == 504
        assert len(responses.calls) == 1
        assert client.send_request(HttpRequest(method, url)).status_code == 200
    assert len(responses.calls) == 2


def test_fixture_role_visibility_never_submits_a_second_create(scope, mocker):
    from azext_iot.tests import helpers
    from azext_iot.tests.dps import conftest as fixtures
    owned = _owned("nh").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", side_effect=[[], [], [{"principalId": SUB_A}]])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}
    mocker.patch.object(runtime, "sleep")
    fallback = mocker.patch.object(fixtures, "assign_role_assignment")
    fixtures._assign_fixture_role(role="IoT DPS Data Contributor", scope=owned, assignee="unit")
    assert reads.call_count == 3
    create.assert_called_once()
    fallback.assert_not_called()


@pytest.mark.parametrize("failure", ["not-visible", "uncertain-create"])
def test_fixture_role_visibility_fails_without_repeating_create(scope, mocker, failure):
    from azext_iot.tests import helpers
    owned = _owned("nh").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}
    if failure == "uncertain-create":
        create.side_effect = ServiceResponseError("synthetic timeout")
    mocker.patch.object(runtime, "sleep")
    with pytest.raises((runtime.ScopeError, ServiceResponseError)):
        runtime.assign_role_assignment_once(role="role", scope=owned, assignee="unit", max_tries=2)
    create.assert_called_once()
    assert reads.call_count == (1 if failure == "uncertain-create" else 3)


@pytest.mark.parametrize("origin", ["create", "fallback-list", "response-json", "cancel"])
def test_fixture_role_confirmation_does_not_hide_unrelated_errors(scope, mocker, origin):
    from azure.cli.command_modules.role import custom as role_commands
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    pause = mocker.patch.object(runtime, "sleep")
    error = KeyboardInterrupt() if origin == "cancel" else IndexError("unrelated indexing failure")
    create = mocker.patch.object(helpers, "invoke_checked")
    if origin == "fallback-list":
        duplicate = HttpResponseError(message="synthetic duplicate")
        duplicate.status_code = 409
        duplicate.error = SimpleNamespace(code="RoleAssignmentExists")
        mocker.patch.object(role_commands, "_create_role_assignment", side_effect=duplicate)
        mocker.patch.object(role_commands, "list_role_assignments", side_effect=error)
        create.side_effect = lambda *_args, **_kwargs: role_commands.create_role_assignment(
            SimpleNamespace(cli_ctx=None), "role", owned,
            assignee_object_id=SUB_A, assignee_principal_type="ServicePrincipal",
        )
    elif origin == "response-json":
        create.return_value.as_json.side_effect = error
    else:
        create.side_effect = error
    with pytest.raises(type(error)) as raised:
        runtime.assign_role_assignment_once(
            role="role", scope=owned, assignee_object_id=SUB_A, assignee_principal_type="ServicePrincipal", max_tries=2,
        )
    assert raised.value is error
    create.assert_called_once()
    reads.assert_called_once()
    pause.assert_not_called()


@pytest.mark.parametrize("other_target", [
    {"role": "other-role"}, {"scope": "/other-scope"},
    {"assignee_object_id": SUB_B}, {"assignee": "other-alias", "assignee_object_id": None},
])
def test_fixture_role_confirmation_rejects_duplicate_from_another_native_target(scope, mocker, other_target):
    from azure.cli.command_modules.role import custom as role_commands
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    arguments = {"role": "role", "scope": owned, "assignee_object_id": SUB_A}
    arguments.update(other_target)
    duplicate = HttpResponseError(message="synthetic duplicate")
    duplicate.status_code = 409
    duplicate.error = SimpleNamespace(code="RoleAssignmentExists")
    mocker.patch.object(role_commands, "_resolve_object_id_and_type", return_value=(SUB_B, "ServicePrincipal"))
    mocker.patch.object(role_commands, "_get_principal_type_from_object_id", return_value="ServicePrincipal")
    mocker.patch.object(role_commands, "_create_role_assignment", side_effect=duplicate)
    mocker.patch.object(role_commands, "list_role_assignments", return_value=[])
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked", side_effect=lambda *_args, **_kwargs: (
        role_commands.create_role_assignment(SimpleNamespace(cli_ctx=None), **arguments)
    ))
    pause = mocker.patch.object(runtime, "sleep")
    with pytest.raises(IndexError) as raised:
        runtime.assign_role_assignment_once(
            role="role", scope=owned, assignee_object_id=SUB_A, assignee_principal_type="ServicePrincipal", max_tries=2,
        )
    assert raised.value.__context__ is duplicate
    create.assert_called_once()
    reads.assert_called_once()
    pause.assert_not_called()


def test_fixture_role_zero_budget_never_creates_or_sleeps(scope, mocker):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked")
    pause = mocker.patch.object(runtime, "sleep")
    with pytest.raises(runtime.ScopeError, match="verification bound"):
        runtime.assign_role_assignment_once(role="role", scope=owned, assignee="unit", max_tries=0)
    reads.assert_called_once()
    create.assert_not_called()
    pause.assert_not_called()


@pytest.mark.parametrize("create_attempted", [False, True])
def test_role_grant_slow_lookup_reports_the_actual_failure_stage(scope, mocker, create_attempted):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    clock = [0]
    mocker.patch.object(runtime, "monotonic", side_effect=lambda: clock[0])

    def read(**_kwargs):
        if not create_attempted or create.called:
            clock[0] += 130
        return []

    def advance(duration):
        clock[0] += duration

    reads = mocker.patch.object(helpers, "get_role_assignments", side_effect=read)
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}
    pause = mocker.patch.object(runtime, "sleep", side_effect=advance)

    with pytest.raises(runtime.ScopeError) as raised:
        runtime.assign_role_assignment_once("role", owned, "synthetic-private-alias")

    message = str(raised.value)
    assert "last_lookup_seconds=130.000" in message
    assert "returned_assignments=0" in message
    assert f"create_attempted={create_attempted}" in message
    for private_value in ("synthetic-private-alias", SUB_A, owned):
        assert private_value not in message
    if create_attempted:
        assert "was not visible before its read-only verification bound" in message
        assert "lookups=2" in message
        assert "elapsed_seconds=140.000" in message
        assert reads.call_count == 2
        create.assert_called_once()
        pause.assert_called_once_with(10)
        record = json.loads(next(scope.glob("role-grant-*.json")).read_text(encoding="utf-8"))
        assert record["create_attempted"] is True
        assert record["verified"] is False
        assert record["principal_id"] == SUB_A
    else:
        assert "preflight" in message
        assert "before any create attempt" in message
        assert "lookups=1" in message
        assert "elapsed_seconds=130.000" in message
        reads.assert_called_once()
        create.assert_not_called()
        pause.assert_not_called()
        assert not list(scope.glob("role-grant-*.json"))


@pytest.mark.parametrize("unlink_on_release", [False, True])
def test_shared_hub_callers_reuse_verified_role_grant(scope, mocker, unlink_on_release):
    from azext_iot.tests import helpers
    from azext_iot.tests.dps import conftest as fixtures

    owned = _owned("hub").removeprefix(ARM)
    resource = {"name": "owned", "id": owned, "location": fixtures.HUB_TEST_LOCATION}
    lock = scope / "shared.lock"
    state = scope / "shared.json"

    class SharedLock(FileLock):
        def release(self, *args, **kwargs):
            super().release(*args, **kwargs)
            if unlink_on_release and not self.is_locked:
                lock.unlink(missing_ok=True)

    mocker.patch.object(fixtures, "FileLock", SharedLock)
    mocker.patch.object(fixtures, "_state_paths", return_value=(str(lock), str(state)))
    mocker.patch.object(fixtures, "_get_run_uid", return_value=UID)
    mocker.patch.object(fixtures.settings.env, "azext_iot_testdps_hub", None)
    mocker.patch.object(fixtures, "_assert_local_auth_policy")

    def create_owned_hub(run_uid, kind):
        assert run_uid == UID and kind == "hub"
        with pytest.raises(LockTimeout):
            with FileLock(str(lock), timeout=0):
                pass
        return "owned", resource

    create_hub = mocker.patch.object(fixtures, "_create_managed_hub", side_effect=create_owned_hub)
    mocker.patch.object(fixtures, "_find_hub_by_name", return_value=resource)
    mocker.patch.object(fixtures, "sleep")
    mocker.patch.object(runtime, "sleep")
    mocker.patch.object(fixtures.cli, "invoke").return_value.as_json.return_value = {"user": {"name": SUB_A}}
    reads = mocker.patch.object(helpers, "get_role_assignments", side_effect=[
        [], [{"principalId": SUB_A}], [], [{"principalId": SUB_A}],
    ])
    create_role = mocker.patch.object(helpers, "invoke_checked")
    create_role.return_value.as_json.return_value = {"principalId": SUB_A}
    # Hub acquire/refcount locking remains unchanged. The separate grant receipt
    # prevents even a stale second preflight from issuing another role create.
    first = fixtures._iot_hubs_provisioner(None)
    second = fixtures._iot_hubs_provisioner(None)
    assert first == second
    create_hub.assert_called_once()
    create_role.assert_called_once()
    assert reads.call_count == 2
    assert json.loads(state.read_text())["refcount"] == 3  # Controller plus both callers.
    with FileLock(str(lock), timeout=0):
        pass


@pytest.mark.skipif(sys.platform != "linux", reason="Receipt-enabled DPS workers require Linux.")
@pytest.mark.timeout(15)
@pytest.mark.parametrize("outcome", ["success", "uncertain-visible", "uncertain", "cancelled", "terminated"])
@pytest.mark.parametrize("release_delay", [0.05, 0.75], ids=["normal", "delayed-release"])
@pytest.mark.parametrize("preflight_delay", [0, 0.75], ids=["fast-preflight", "slow-preflight"])
def test_role_grant_real_workers_serialize_and_never_replay_attempt(
    scope, mocker, outcome, release_delay, preflight_delay,
):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    context = multiprocessing.get_context("fork")
    creating, release, waiter_started = (context.Event() for _ in range(3))
    creates, reads = context.Value("i", 0), context.Value("i", 0)
    visible = context.Value("b", False)
    results = context.Queue()

    def read(**kwargs):
        assert kwargs["role"] == "role" and kwargs["scope"] == owned
        assert kwargs.get("assignee") == "caller-alias" or kwargs.get("assignee_object_id") == SUB_A
        with reads.get_lock():
            reads.value += 1
            first_read = reads.value == 1
        if first_read:
            time.sleep(preflight_delay)
        return [{"principalId": SUB_A}] if visible.value else []

    def create(*_args, **_kwargs):
        with creates.get_lock():
            creates.value += 1
        creating.set()  # The durable attempt marker and real grant lock already exist.
        if outcome == "terminated":
            time.sleep(10)  # Do not kill a process holding a multiprocessing.Event's condition lock.
        else:
            assert release.wait(5)
        if outcome in ("success", "uncertain-visible"):
            visible.value = True
        if outcome == "cancelled":
            raise KeyboardInterrupt()
        if outcome != "success":
            raise ServiceResponseError("synthetic uncertain response")
        return SimpleNamespace(as_json=lambda: {"principalId": SUB_A})

    def worker(label):
        if label == "waiter":
            waiter_started.set()
        try:
            # Every owner must survive preflight long enough to exercise its create outcome.
            # Successful waiters tolerate scheduling; negative visibility deadlines stay short.
            max_tries = 100 if label == "owner" or outcome in ("success", "uncertain-visible") else 10
            runtime.assign_role_assignment_once("role", owned, "caller-alias", max_tries=max_tries, wait=0.05)
        except BaseException as error:  # pylint: disable=broad-except
            results.put((label, type(error).__name__))
        else:
            results.put((label, "verified"))

    mocker.patch.object(helpers, "get_role_assignments", side_effect=read)
    mocker.patch.object(helpers, "invoke_checked", side_effect=create)
    owner = context.Process(target=worker, args=("owner",))
    waiter = context.Process(target=worker, args=("waiter",))
    owner.start()
    try:
        assert creating.wait(5)
        waiter.start()
        assert waiter_started.wait(5)
        time.sleep(release_delay)
        assert reads.value == creates.value == 1  # Waiter is behind the real cross-process FileLock.
        if outcome == "terminated":
            os.kill(owner.pid, signal.SIGTERM)
        else:
            release.set()
        owner.join(3)
        waiter.join(3)
        assert not owner.is_alive() and not waiter.is_alive()
        statuses = dict(results.get(timeout=1) for _ in range(1 if outcome == "terminated" else 2))
        assert statuses["waiter"] == ("verified" if outcome in ("success", "uncertain-visible") else "ScopeError")
        if outcome != "terminated":
            assert statuses["owner"] == {
                "success": "verified", "uncertain-visible": "ServiceResponseError",
                "uncertain": "ServiceResponseError", "cancelled": "KeyboardInterrupt",
            }[outcome]
        assert creates.value == 1
        record = json.loads(next(scope.glob("role-grant-*.json")).read_text())
        assert record["create_attempted"] is True
        assert record["run_uid"] == UID and record["subscription"] == SUB_B and record["phase"] == "regular"
        if outcome in ("success", "uncertain-visible"):
            assert record["verified"] and record["principal_id"] == SUB_A
            assert reads.value == 2
    finally:
        release.set()
        for process in (owner, waiter):
            if process.pid:
                if process.is_alive():
                    os.kill(process.pid, signal.SIGTERM)
                process.join(3)
        results.close()


@pytest.mark.parametrize("coarse_clock", [False, True])
def test_role_grant_lock_wait_is_bounded_and_does_not_replay(scope, mocker, coarse_clock):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked", side_effect=ServiceResponseError("uncertain"))
    with pytest.raises(ServiceResponseError):
        runtime.assign_role_assignment_once("role", owned, "alias", max_tries=1, wait=0)
    receipt = next(scope.glob("role-grant-*.json"))
    clock = mocker.Mock(side_effect=[749.406, 749.5]) if coarse_clock else time.monotonic
    resolution = 0.015625 if coarse_clock else time.get_clock_info("monotonic").resolution
    started = clock()
    with FileLock(str(receipt) + ".grant.lock"):
        with pytest.raises(runtime.ScopeError, match="cross-worker verification bound") as raised:
            runtime.assign_role_assignment_once("role", owned, "alias", max_tries=2, wait=0.05)
    assert max(0, 0.1 - resolution) <= clock() - started < 2
    assert isinstance(raised.value.__cause__, LockTimeout)
    create.assert_called_once()
    reads.assert_called_once()


def test_role_grant_lock_wait_consumes_existing_visibility_budget(scope, mocker):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    clock = [0]
    mocker.patch.object(runtime, "monotonic", side_effect=lambda: clock[0])

    class DelayedLock(FileLock):
        def acquire(self, *args, **kwargs):
            assert kwargs["timeout"] == 10
            clock[0] += 7
            return super().acquire(*args, **kwargs)

    mocker.patch.object(runtime, "FileLock", DelayedLock)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}

    def advance(duration):
        clock[0] += duration

    pause = mocker.patch.object(runtime, "sleep", side_effect=advance)
    with pytest.raises(runtime.ScopeError, match="read-only verification bound"):
        runtime.assign_role_assignment_once("role", owned, "alias", max_tries=1, wait=10)
    assert clock[0] == 10  # Seven seconds waiting leaves three, not another ten.
    pause.assert_called_once_with(3)
    create.assert_called_once()
    assert reads.call_count == 2


def test_role_grant_uuid_alias_reuses_resolved_principal_after_unverified_attempt(scope, mocker):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", side_effect=[
        [], [], [{"principalId": SUB_B}],
    ])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_B}  # App ID != object ID.
    with pytest.raises(runtime.ScopeError, match="read-only verification bound"):
        runtime.assign_role_assignment_once("role", owned, SUB_A, max_tries=1, wait=0)
    runtime.assign_role_assignment_once("role", owned, SUB_A, max_tries=1, wait=0)
    runtime.assign_role_assignment_once("role", owned, SUB_A, max_tries=1, wait=0)
    create.assert_called_once()
    assert f'--assignee "{SUB_A}"' in create.call_args.args[1]
    assert "--assignee-object-id" not in create.call_args.args[1]
    assert reads.call_args_list[0].kwargs["assignee"] == SUB_A
    assert all(call.kwargs["assignee_object_id"] == SUB_B for call in reads.call_args_list[1:])
    record = json.loads(next(scope.glob("role-grant-*.json")).read_text())
    assert record["target_kind"] == "alias" and record["target"] == SUB_A
    assert record["principal_id"] == SUB_B and record["verified"]


@pytest.mark.parametrize("existing", [False, True])
def test_role_grant_known_id_case_does_not_change_logical_grant(scope, mocker, existing):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(
        helpers, "get_role_assignments",
        side_effect=[[{"principalId": SUB_A.upper()}]] if existing else [[], [{"principalId": SUB_A}]],
    )
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A.upper()}
    for role, target_scope, principal in (("role", owned, SUB_A), ("ROLE", owned.upper(), SUB_A.upper())):
        runtime.assign_role_assignment_once(
            role, target_scope, assignee_object_id=principal, assignee_principal_type="ServicePrincipal",
            max_tries=1, wait=0,
        )
    assert reads.call_count == (1 if existing else 2)
    assert create.call_count == (0 if existing else 1)
    assert len(list(scope.glob("role-grant-*.json"))) == 1


@pytest.mark.parametrize("principal", [None, "", " ", 17, True, {}])
def test_role_grant_invalid_principal_read_cannot_verify_or_create(scope, mocker, principal):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    mocker.patch.object(helpers, "get_role_assignments", return_value=[{"principalId": principal}])
    create = mocker.patch.object(helpers, "invoke_checked")
    with pytest.raises(runtime.ScopeError):
        runtime.assign_role_assignment_once("role", owned, "alias", max_tries=1, wait=0)
    create.assert_not_called()
    assert not list(scope.glob("role-grant-*.json"))


def test_role_grant_requires_durable_attempt_receipt_before_create(scope, mocker):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked")
    mocker.patch.object(receipts, "write", side_effect=OSError("receipt write failed"))
    with pytest.raises(OSError, match="receipt write failed"):
        runtime.assign_role_assignment_once("role", owned, "alias")
    create.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("phase", "service-sas"), ("run_uid", "a" * 32), ("subscription", SUB_A),
    ("scope", "/other"), ("role", "other-role"), ("target", "other-alias"),
])
def test_role_grant_rejects_mismatched_receipt_before_cli(scope, mocker, field, value):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[{"principalId": SUB_A}])
    create = mocker.patch.object(helpers, "invoke_checked")
    runtime.assign_role_assignment_once("role", owned, "alias")
    receipt = next(scope.glob("role-grant-*.json"))
    record = json.loads(receipt.read_text())
    record[field] = value
    receipt.write_text(json.dumps(record))
    with pytest.raises(runtime.ScopeError, match="exact grant"):
        runtime.assign_role_assignment_once("role", owned, "alias")
    reads.assert_called_once()
    create.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("create_attempted", None), ("verified", "true"), ("principal_id", None),
    ("principal_id", 42), ("principal_id", ""), ("principal_id", False), ("principal_id", " "),
])
@pytest.mark.parametrize("known_principal", [False, True])
def test_role_grant_corrupt_receipt_cannot_authorize_success_or_recreation(scope, mocker, field, value, known_principal):
    from azext_iot.tests import helpers

    owned = _owned("hub").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[{"principalId": SUB_A}])
    create = mocker.patch.object(helpers, "invoke_checked")
    target = (
        {"assignee_object_id": SUB_A, "assignee_principal_type": "ServicePrincipal"}
        if known_principal else {"assignee": "alias"}
    )
    runtime.assign_role_assignment_once("role", owned, **target)
    receipt = next(scope.glob("role-grant-*.json"))
    record = json.loads(receipt.read_text())
    record[field] = value
    receipt.write_text(json.dumps(record))
    with pytest.raises(runtime.ScopeError):
        runtime.assign_role_assignment_once("role", owned, **target)
    reads.assert_called_once()
    create.assert_not_called()


@responses.activate
def test_unowned_arm_writes_are_rejected_but_unscoped_product_retries_unchanged(scope):
    url = _owned("nh")
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        with pytest.raises(runtime.ScopeError, match="owned resource"):
            client.send_request(HttpRequest("PUT", url + "-borrowed"))
    assert not responses.calls
    # No product policy modification: the normal client still retries its 504.
    responses.add("PUT", url, status=504)
    responses.add("PUT", url, json={})
    assert _client("iot_service_provisioning_factory").send_request(HttpRequest("PUT", url)).status_code == 200
    assert len(responses.calls) == 2


@responses.activate
@pytest.mark.parametrize("factory_name,kind", [
    ("iot_hub_service_factory", "hub"), ("adr_iot_hub_service_factory", "hub"),
    ("iot_service_provisioning_factory", "nh"), ("adr_iot_service_provisioning_factory", "nh"),
])
def test_real_delete_poller_keeps_get_polling_without_repeating_delete(scope, factory_name, kind):
    url = _owned(kind)
    poll = ARM + f"/subscriptions/{SUB_B}/providers/Microsoft.Devices/operations/unit"
    responses.add(responses.DELETE, url, status=202, body="null",
                  headers={"Azure-AsyncOperation": poll, "Retry-After": "0"})
    responses.add(responses.GET, poll, json={"status": "InProgress"}, headers={"Retry-After": "0"})
    responses.add(responses.GET, poll, json={"status": "Succeeded"})
    with runtime.activate(SUB_B):
        client = _client(factory_name)
        with runtime.owned_write("owned", "DELETE"):
            if kind == "hub":
                poller = client.iot_hub_resource.begin_delete(
                    resource_group_name="group", resource_name="owned", polling_interval=0)
            else:
                poller = client.iot_dps_resource.begin_delete(
                    resource_group_name="group", provisioning_service_name="owned", polling_interval=0)
            result = poller.result(timeout=5)
            assert poller.done()
            assert result == ({"status": "Succeeded"} if kind == "hub" else None)
    assert [call.request.method for call in responses.calls] == ["DELETE", "GET", "GET"]


def test_separate_real_embedded_clis_and_link_transition_are_pinned_without_profile_switch(scope, mocker):
    from azure.cli.core._profile import Profile
    from azext_iot.common.auth import get_aad_token
    from azext_iot.tests.dps.core import test_dps_linked_hub_int as linked

    token_subscriptions = []

    def token(_self, resource=None, scopes=None, subscription=None, tenant=None, credential_out=None):
        token_subscriptions.append(subscription)
        return ("Bearer", "fake-unit-token", {}), subscription, "unit-tenant"

    mocker.patch.object(Profile, "get_raw_token", token)
    default = mocker.patch.object(Profile, "get_subscription", autospec=True,
                                  side_effect=lambda _self, subscription=None: {"id": subscription or SUB_A})
    instance = linked.cli  # This instance predates activation and has a cached default A.
    mocker.patch.dict(instance.az_cli.data, {"subscription_id": SUB_A})
    mocker.patch.object(instance, "user_subscription", SUB_A)
    mocker.patch.object(instance.az_cli, "result", SimpleNamespace(error=None))
    calls = []
    mode = ["KeyBased"]

    def dispatch(arguments, out_file):
        calls.append(arguments)
        assert arguments[arguments.index("--subscription") + 1] == SUB_B
        assert instance.az_cli.data["subscription_id"] == SUB_B
        get_aad_token(instance.az_cli)
        if "update" in arguments:
            mode[0] = "SystemAssigned"
        out_file.write(json.dumps([{
            "name": "unit.device.azure-devices.net", "hostName": "unit.device.azure-devices.net",
            "authenticationType": mode[0], "connectionString": "",
        }]))
        return 0

    mocker.patch.object(instance.az_cli, "invoke", side_effect=dispatch)
    hub = {"name": "unit", "properties": {"deviceHostName": "unit.device.azure-devices.net"}}
    mocker.patch.object(linked, "_require_gwv2_hub", return_value=hub)
    with runtime.activate(SUB_B):
        linked.test_linked_hub_create_keybased_then_switch_to_mi(
            {"name": "owned", "resourceGroup": "group"}, {"rg": "group"},
        )
        another = EmbeddedCLI()
        invoked = mocker.patch.object(another.az_cli, "invoke", return_value=0)
        another.invoke("iot dps enrollment list --dps-name owned -g group")
        assert invoked.call_args.args[0][-2:] == ["--subscription", SUB_B]
        assert Profile(cli_ctx=another.az_cli).get_subscription()["id"] == SUB_B
        with pytest.raises(runtime.ScopeError):
            another.invoke(f"iot dps show -n owned --subscription {SUB_A}")
        with pytest.raises(runtime.ScopeError):
            another.invoke("account set --subscription " + SUB_B)
    assert instance.az_cli.data["subscription_id"] == SUB_A
    assert instance.user_subscription == SUB_A
    assert Profile(cli_ctx=instance.az_cli).get_subscription()["id"] == SUB_A
    assert default.call_args.kwargs.get("subscription") is None
    assert len(calls) == 5 and token_subscriptions == [SUB_B] * 5


@pytest.mark.timeout(100)
@pytest.mark.skipif(sys.platform != "linux", reason="Real DPS orchestration requires Linux signals, process groups and /proc.")
def test_real_tox_xdist_timeout_allows_twelve_second_fixture_cleanup_and_ends_children(tmp_path, mocker):
    directory = tmp_path / "receipts"
    directory.mkdir()
    environment = dict(
        os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", VIRTUALENV_NO_PERIODIC_UPDATE="1",
        VIRTUALENV_DOWNLOAD="0", PIP_NO_INDEX="1",
        azext_iot_dps_phase_receipts=str(directory), azext_iot_dps_run_uid=UID,
        azext_iot_dps_test_subscription=SUB_B, azext_iot_dps_test_resource_group="group",
        azext_iot_dps_test_phase="regular",
    )
    config = tmp_path / "tox.ini"
    config.write_text(
        "[tox]\nenv_list=cleanup-proof\n[testenv:cleanup-proof]\npackage=skip\nsitepackages=false\n"
        "passenv=PYTHONPATH,PYTHONNOUSERSITE,PYTHONDONTWRITEBYTECODE,"
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD,AZURE_CONFIG_DIR,azext_*\n"
        # sitepackages=true exposes the base/user site, NOT the parent tox
        # venv's dependencies. Run the already-populated interpreter explicitly;
        # do not install dependencies or depend on global/user-site fallback.
        f"allowlist_externals={sys.executable}\n"
        f'commands="{sys.executable}" -m pytest -p xdist.plugin -n 2 --max-worker-restart=0 -q test_workers.py\n',
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        "import json,os,socket\nfrom pathlib import Path\n"
        "def deny(*args, **kwargs): raise AssertionError('offline process cannot connect')\n"
        "socket.socket.connect = deny\n"
        "from azext_iot.tests.dps import _phase_runtime\n"
        "def pytest_sessionstart(session):\n"
        "    _phase_runtime.start_worker(session)\n"
        "    if not hasattr(session.config, 'workerinput'):\n"
        "        Path('controller.json').write_text(json.dumps({'pid':os.getpid(),'parent_pid':os.getppid()}))\n",
        encoding="utf-8",
    )
    (tmp_path / "test_workers.py").write_text(
        "import json,os,sys,time,pytest\nfrom pathlib import Path\n"
        "@pytest.fixture(scope='session')\n"
        "def owned():\n"
        "    Path('started-'+str(os.getpid())).write_text(json.dumps({\n"
        "        'executable':sys.executable,'prefix':sys.prefix,'pytest':pytest.__file__}))\n"
        "    yield\n"
        "    started=time.monotonic()\n"
        "    time.sleep(12)\n"
        "    Path('cleaned-'+str(os.getpid())).write_text(json.dumps({'elapsed':time.monotonic()-started}))\n"
        "@pytest.mark.parametrize('case',[0,1])\n"
        "def test_wait(owned,case):\n"
        "    while True: time.sleep(.1)\n",
        encoding="utf-8",
    )
    # Outer tox exports TOX_WORK_DIR. Explicit CLI paths keep the nested
    # environment and its commands inside this test, never the repository's .tox.
    command = [
        sys.executable, "-m", "tox", "r", "-c", str(config), "-e", "cleanup-proof",
        "--root", str(tmp_path), "--workdir", str(tmp_path / ".tox"),
    ]
    setup = subprocess.run(command + ["--notest"], env=environment, capture_output=True, timeout=45, check=False)
    redactor = RUNNER["Redactor"]()
    setup_status = setup.returncode
    setup_diagnostic = "".join(
        redactor.line(line) for line in (setup.stdout + setup.stderr).decode("utf-8", errors="replace").splitlines(True)
    )[-4096:]
    del setup  # Assertion rewriting must not include an unbounded/raw CompletedProcess repr.
    assert setup_status == 0, setup_diagnostic
    venv_config = tmp_path / ".tox/cleanup-proof/pyvenv.cfg"
    assert "include-system-site-packages = false" in venv_config.read_text(encoding="utf-8")
    mocker.patch.dict(RUNNER["child"].__globals__, READ_SECONDS=1)
    started = time.monotonic()
    result = RUNNER["child"](command, environment, tmp_path / "log", runtime=10, cleanup=25)
    elapsed = time.monotonic() - started
    # The runner log is already redacted; bound assertion diagnostics even if
    # pytest exits during startup, before creating any worker/cleanup receipts.
    with (tmp_path / "log").open("rb") as stream:
        stream.seek(max(0, (tmp_path / "log").stat().st_size - 4096))
        diagnostic = f"{result}; elapsed={elapsed:.2f}s\n{stream.read().decode('utf-8', errors='replace')}"
    assert result["timed_out"] and result["interrupted"] and result["exit_code"] == 2, diagnostic
    assert 22 <= elapsed < 40, diagnostic
    markers = sorted(tmp_path.glob("started-*"))
    workers = [json.loads(path.read_text()) for path in directory.glob("worker-*.json")]
    assert len(markers) == len(workers) == 2, diagnostic
    assert {int(marker.name.partition("-")[2]) for marker in markers} == {worker["pid"] for worker in workers}, diagnostic
    for marker in markers:
        pid = int(marker.name.partition("-")[2])
        assert json.loads(marker.read_text()) == {
            "executable": sys.executable, "prefix": sys.prefix, "pytest": pytest.__file__,
        }, diagnostic
        cleaned = tmp_path / f"cleaned-{pid}"
        assert cleaned.is_file(), diagnostic
        assert json.loads(cleaned.read_text())["elapsed"] >= 12, diagnostic
        assert not Path(f"/proc/{pid}").exists(), diagnostic
    controller_path = tmp_path / "controller.json"
    assert controller_path.is_file(), diagnostic
    controller = json.loads(controller_path.read_text())
    assert {worker["parent_pid"] for worker in workers} == {controller["pid"]}, diagnostic
    assert not Path(f"/proc/{controller['pid']}").exists(), diagnostic
    assert not Path(f"/proc/{controller['parent_pid']}").exists(), diagnostic
    assert (directory / "stop-requested.json").is_file(), diagnostic
