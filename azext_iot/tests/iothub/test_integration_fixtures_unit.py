# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import shlex
from contextlib import nullcontext
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock
from requests import Response

import pytest
import yaml
from azure.cli.core.azclierror import CLIInternalError, RequiredArgumentMissingError
from azure.core.exceptions import HttpResponseError

from azext_iot.tests import CaptureOutputLiveScenarioTest, iothub
from azext_iot.tests.iothub import IoTLiveScenarioTest, conftest as fixtures
from azext_iot.tests.iothub import _integration_helpers as integration_helpers
from azext_iot.tests.iothub._integration_helpers import (
    assert_hub_policy,
    device_receiver,
    get_or_create_hub,
    scope_known_hub,
    skip_hub_list_provider_error,
)
from azext_iot.tests.settings import HUB_TEST_LOCATION


def service_error(status, code, api_version="2026-10-01-preview"):
    error = HttpResponseError(message="Service error")
    error.status_code = status
    error.error = SimpleNamespace(code=code)
    error.response = SimpleNamespace(request=SimpleNamespace(
        method="GET",
        url=(
            "https://centraluseuap.management.azure.com/subscriptions/sub/resourceGroups/rg/"
            f"providers/Microsoft.Devices/IotHubs?api-version={api_version}&$skiptoken=next"
        ),
    ))
    return error


ROLE_ARGS = {
    "role": "IoT Hub Data Contributor",
    "scope": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub",
    "assignee": "principal",
    "max_tries": 3,
    "wait": iothub.ROLE_ASSIGNMENT_REFRESH_TIME,
}


def test_new_data_role_waits_after_the_assignment_is_observed(mocker):
    calls = []
    assignments = iter([[], [{"principalId": "principal"}]])

    def get_assignments(**kwargs):
        assert kwargs == {
            "scope": ROLE_ARGS["scope"], "role": ROLE_ARGS["role"], "fill_role_definition_name": False,
        }
        calls.append("list")
        return next(assignments)

    mocker.patch.object(integration_helpers, "get_role_assignments", side_effect=get_assignments)
    assign = mocker.patch.object(
        integration_helpers, "assign_role_assignment", side_effect=lambda **kwargs: calls.append("assign")
    )
    wait = mocker.patch.object(integration_helpers, "sleep", side_effect=lambda seconds: calls.append(("sleep", seconds)))
    integration_helpers.assign_role_with_propagation(**ROLE_ARGS)
    assert calls == ["list", "assign", "list", ("sleep", 120)]
    assign.assert_called_once_with(
        role=ROLE_ARGS["role"], scope=ROLE_ARGS["scope"], assignee="principal", max_tries=3
    )
    wait.assert_called_once_with(iothub.ROLE_ASSIGNMENT_REFRESH_TIME)


@pytest.mark.parametrize("principal_key", ["name", "principalId", "principalName"])
def test_existing_data_role_does_not_repeat_assignment_or_propagation_wait(mocker, principal_key):
    get_assignments = mocker.patch.object(
        integration_helpers, "get_role_assignments", return_value=[{principal_key: "principal"}]
    )
    assign = mocker.patch.object(integration_helpers, "assign_role_assignment")
    wait = mocker.patch.object(integration_helpers, "sleep")
    integration_helpers.assign_role_with_propagation(**ROLE_ARGS)
    get_assignments.assert_called_once_with(
        scope=ROLE_ARGS["scope"], role=ROLE_ARGS["role"], fill_role_definition_name=False,
    )
    assign.assert_not_called()
    wait.assert_not_called()


@pytest.mark.parametrize("error_stage", ["before", "assignment", "after"])
def test_data_role_authorization_errors_propagate_without_retry_or_sleep(mocker, error_stage):
    error = service_error(403, "AuthorizationFailed")
    get_assignments = mocker.patch.object(integration_helpers, "get_role_assignments", return_value=[])
    assign = mocker.patch.object(integration_helpers, "assign_role_assignment")
    wait = mocker.patch.object(integration_helpers, "sleep")
    if error_stage == "before":
        get_assignments.side_effect = error
    elif error_stage == "assignment":
        assign.side_effect = error
    else:
        get_assignments.side_effect = [[], error]
    with pytest.raises(HttpResponseError) as raised:
        integration_helpers.assign_role_with_propagation(**ROLE_ARGS)
    assert raised.value is error
    wait.assert_not_called()
    assert get_assignments.call_count == (2 if error_stage == "after" else 1)
    assert assign.call_count == (0 if error_stage == "before" else 1)


def test_unobserved_data_role_fails_instead_of_assuming_the_grant_succeeded(mocker):
    mocker.patch.object(integration_helpers, "get_role_assignments", return_value=[])
    mocker.patch.object(integration_helpers, "assign_role_assignment", return_value=None)
    wait = mocker.patch.object(integration_helpers, "sleep")
    with pytest.raises(CLIInternalError, match="was not assigned"):
        integration_helpers.assign_role_with_propagation(**ROLE_ARGS)
    wait.assert_not_called()


def test_missing_data_role_principal_fails_without_querying_or_waiting(mocker):
    get_assignments = mocker.patch.object(integration_helpers, "get_role_assignments")
    wait = mocker.patch.object(integration_helpers, "sleep")
    with pytest.raises(CLIInternalError, match="principal is required"):
        integration_helpers.assign_role_with_propagation(**{**ROLE_ARGS, "assignee": None})
    get_assignments.assert_not_called()
    wait.assert_not_called()


def test_scenario_role_setup_uses_the_existing_propagation_budget(mocker):
    assign = mocker.patch.object(iothub, "assign_role_with_propagation")
    scenario = SimpleNamespace(cmd=Mock())
    scenario.cmd.return_value.get_output_in_json.return_value = {"user": {"name": "principal"}}
    IoTLiveScenarioTest._add_data_contributor(scenario, {"id": ROLE_ARGS["scope"]})
    assign.assert_called_once_with(
        role=iothub.USER_ROLE,
        scope=ROLE_ARGS["scope"],
        assignee="principal",
        max_tries=iothub.MAX_RBAC_ASSIGNMENT_TRIES,
        wait=iothub.ROLE_ASSIGNMENT_REFRESH_TIME,
    )


def test_state_hub_role_setup_waits_before_returning_to_dataplane_setup(mocker):
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.return_value = {"user": {"name": "principal"}}
    assign = mocker.patch.object(fixtures, "assign_role_with_propagation")
    fixtures.assign_iot_hub_dataplane_rbac_role([
        {"hub": {"id": ROLE_ARGS["scope"]}},
        {"name": "mid-test-hub"},
    ])
    assign.assert_called_once_with(
        role=fixtures.USER_ROLE,
        scope=ROLE_ARGS["scope"],
        assignee="principal",
        max_tries=fixtures.MAX_RBAC_ASSIGNMENT_TRIES,
        wait=fixtures.ROLE_ASSIGNMENT_REFRESH_TIME,
    )


@pytest.mark.parametrize("marker_kwargs,system_endpoints", [
    ({"system_endpoints": True}, True),
    ({"system_endpoints": False}, False),
    pytest.param({}, True, id="marked-default-system"),
    pytest.param(None, True, id="unmarked-default-system"),
])
@pytest.mark.parametrize("failed_command", [None, *range(9)])
@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
def test_state_endpoint_roles_match_the_configured_identities(
    mocker, marker_kwargs, system_endpoints, failed_command, failure_kind
):
    user_id = "/user-identities/shared"
    storage = {
        "storage": {"id": "storage-scope", "primaryEndpoints": {"blob": "https://storage.blob.core.windows.net/"}},
        "container": {"name": "container"},
        "connectionString": "unused",
    }
    hubs = [
        {
            "name": name, "rg": "rg", "storage": storage,
            "hub": {"identity": {"principalId": f"{name}-system", "userAssignedIdentities": {user_id: {}}}},
        }
        for name in ("origin", "destination")
    ]
    eventhub = {
        "namespace": {"serviceBusEndpoint": "https://events.servicebus.windows.net/"},
        "eventhub": {"name": "events", "id": "eventhub-scope"},
    }
    servicebus = {
        "namespace": {"serviceBusEndpoint": "https://bus.servicebus.windows.net/"},
        "queue": {"name": "queue", "id": "queue-scope"},
        "topic": {"name": "topic", "id": "topic-scope"},
    }
    cosmos = {"container": {"name": "container"}, "database": {"name": "database"}, "connectionString": "unused"}
    marker = SimpleNamespace(kwargs=marker_kwargs) if marker_kwargs is not None else None
    mocker.patch.object(fixtures, "get_closest_marker", return_value=marker)
    assign = mocker.patch.object(fixtures, "assign_role_assignment")
    client = SimpleNamespace(
        exception_handler=mocker.Mock(return_value=1),
        result=SimpleNamespace(error=None),
    )
    mocker.patch.object(fixtures.cli, "az_cli", client)
    error = HttpResponseError("Original fixture command failure")
    exit_code = 2 if failure_kind == "system_exit" else 7

    def invoke(args, out_file):
        failed = client.invoke.call_count - 1 == failed_command
        client.result.error = error if failed and failure_kind == "cli_error" else None
        if failed:
            if failure_kind == "system_exit":
                raise SystemExit(exit_code)
            return exit_code
        out_file.write("{}")
        return 0

    client.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(fixtures, "sleep")
    mocker.patch.object(fixtures, "create_self_signed_certificate", return_value={"certificate": "unused"})
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch.object(fixtures.os.path, "isfile", return_value=True)
    remove = mocker.patch.object(fixtures.os, "remove")

    setup = fixtures.setup_hub_controlplane_states.__wrapped__(
        Mock(), {"principalId": "user-principal"}, hubs, eventhub, servicebus, cosmos
    )
    if failed_command is None:
        assert next(setup) is hubs
        setup.close()
        assert client.invoke.call_count == 9
    else:
        expected_error = HttpResponseError if failure_kind == "cli_error" else CLIInternalError
        with pytest.raises(expected_error) as raised:
            next(setup)
        if failure_kind == "cli_error":
            assert raised.value is error
        else:
            assert str(raised.value) == f"IoT Hub fixture command failed with exit code {exit_code}."
        assert client.invoke.call_count == failed_command + 1
    assert remove.call_count == (1 if failed_command in (None, 8) else 0)

    expected = []
    for scope, role in (
        ("storage-scope", "Storage Blob Data Contributor"),
        ("eventhub-scope", "Azure Event Hubs Data Sender"),
        ("queue-scope", "Azure Service Bus Data Sender"),
        ("topic-scope", "Azure Service Bus Data Sender"),
    ):
        principals = (
            ["origin-system", "destination-system"]
            if system_endpoints and scope != "topic-scope" else ["user-principal"]
        )
        expected.extend(
            mocker.call(assignee=principal, scope=scope, role=role, max_tries=fixtures.MAX_RBAC_ASSIGNMENT_TRIES)
            for principal in principals
        )
    assert assign.call_args_list == expected
    identity_commands = [call.args[0] for call in client.invoke.call_args_list if "--identity" in call.args[0]]
    if failed_command is None:
        assert len(identity_commands) == 4
    for command in identity_commands:
        identity = user_id if "servicebus-topic" in command or not system_endpoints else "[system]"
        assert command[command.index("--identity") + 1] == identity


def test_existing_hub_role_fixture_uses_propagation_wait(mocker):
    mocker.patch.object(fixtures, "settings", SimpleNamespace(env=SimpleNamespace(azext_iot_testhub="existing")))
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.side_effect = [
        {"user": {"name": "principal"}}, {"id": ROLE_ARGS["scope"]},
    ]
    assign = mocker.patch.object(fixtures, "assign_role_with_propagation")
    fixture = fixtures.fixture_provision_existing_hub_role.__wrapped__(Mock())
    next(fixture)
    assign.assert_called_once_with(
        role=fixtures.USER_ROLE,
        scope=ROLE_ARGS["scope"],
        assignee="principal",
        max_tries=fixtures.MAX_RBAC_ASSIGNMENT_TRIES,
        wait=fixtures.ROLE_ASSIGNMENT_REFRESH_TIME,
    )
    with pytest.raises(StopIteration):
        next(fixture)


def test_existing_hub_cleanup_explicitly_depends_on_role_setup():
    import inspect

    parameters = inspect.signature(fixtures.fixture_provision_existing_hub_device_config.__wrapped__).parameters
    assert "fixture_provision_existing_hub_role" in parameters


def test_existing_hub_setup_uses_get_not_list():
    client, create = Mock(), Mock()
    hub = {"name": "hub"}
    client.get.return_value = hub
    assert get_or_create_hub(client, "hub", "rg", create) == (hub, False)
    client.get.assert_called_once_with(resource_group_name="rg", resource_name="hub")
    client.list.assert_not_called()
    client.list_by_resource_group.assert_not_called()
    create.assert_not_called()


def test_missing_hub_is_created_only_after_404():
    client, create = Mock(), Mock()
    hub = {"name": "hub"}
    client.get.side_effect = [service_error(404, "ResourceNotFound"), hub]
    assert get_or_create_hub(client, "hub", "rg", create) == (hub, True)
    create.assert_called_once_with()
    assert client.get.call_count == 2


@pytest.mark.parametrize("status,code", [(400, "400024"), (403, "AuthorizationFailed"), (502, "ProviderError")])
def test_setup_does_not_create_on_other_service_errors(status, code):
    client, create = Mock(), Mock()
    error = service_error(status, code)
    client.get.side_effect = error
    with pytest.raises(HttpResponseError) as raised:
        get_or_create_hub(client, "hub", "rg", create)
    assert raised.value is error
    create.assert_not_called()


@pytest.mark.parametrize("api_version", ["2026-05-01-preview", "2026-10-01-preview"])
@pytest.mark.parametrize("status,code", [
    (400, "400024"), (403, "AuthorizationFailed"), (502, "OtherError"),
    (400, "ProviderError"), (403, "ProviderError"), (500, "ProviderError"),
])
def test_enumeration_workaround_does_not_hide_other_errors(status, code, api_version):
    error = service_error(status, code, api_version)
    with pytest.raises(HttpResponseError) as raised:
        with skip_hub_list_provider_error():
            raise error
    assert raised.value is error


@pytest.mark.parametrize("api_version", ["2026-05-01-preview", "2026-10-01-preview"])
@pytest.mark.parametrize("resource_group", [True, False])
def test_only_confirmed_list_provider_error_is_skipped(api_version, resource_group):
    error = service_error(502, "ProviderError", api_version)
    if not resource_group:
        error.response.request.url = error.response.request.url.replace("/resourceGroups/rg", "")
    with pytest.raises(pytest.skip.Exception, match="502 ProviderError"):
        with skip_hub_list_provider_error():
            raise error


@pytest.mark.parametrize("url", [
    "https://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs/hub/listKeys",
    "https://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs/hub",
    "https://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs?api-version=2023-06-30",
    "https://management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs?api-version=2026-10-01-preview",
    "https://management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs?api-version=2026-05-01-preview",
    "http://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs"
    "?api-version=2026-05-01-preview",
    "https://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs",
    "https://centraluseuap.management.azure.com/subscriptions/sub/providers/Microsoft.Devices/IotHubs"
    "?api-version=2026-05-01-preview&api-version=2026-10-01-preview",
    "",
])
def test_other_provider_502_operations_are_not_skipped(url):
    error = service_error(502, "ProviderError")
    error.response.request.url = url
    with pytest.raises(HttpResponseError) as raised:
        with skip_hub_list_provider_error():
            raise error
    assert raised.value is error


@pytest.mark.parametrize("api_version", ["2026-05-01-preview", "2026-10-01-preview"])
@pytest.mark.parametrize("method,suffix", [
    ("POST", ""), ("PUT", ""), ("DELETE", ""), ("HEAD", ""),
    ("GET", "/hub"), ("POST", "/hub/listKeys"),
])
def test_other_hub_operations_are_not_skipped_with_supported_api_versions(api_version, method, suffix):
    error = service_error(502, "ProviderError", api_version)
    request = error.response.request
    request.method = method
    request.url = request.url.replace("/IotHubs?", f"/IotHubs{suffix}?")
    with pytest.raises(HttpResponseError) as raised:
        with skip_hub_list_provider_error():
            raise error
    assert raised.value is error


def test_provider_error_without_request_diagnostics_is_not_skipped():
    error = service_error(502, "ProviderError")
    error.response = None
    with pytest.raises(HttpResponseError) as raised:
        with skip_hub_list_provider_error():
            raise error
    assert raised.value is error


@pytest.mark.parametrize("command,expected", [
    ("iot hub show -n hub", "iot hub show -n hub --resource-group rg"),
    ("iot hub device-twin show --hub-name hub -d d", "iot hub device-twin show --hub-name hub -d d --resource-group rg"),
    ("iot hub show -n hub -g other", "iot hub show -n hub -g other"),
    ("iot hub list", "iot hub list"),
    ("iot hub connection-string show", "iot hub connection-string show"),
    ("iot hub show -n other", "iot hub show -n other"),
    ("identity show -n hub", "identity show -n hub"),
])
def test_known_hub_scoping_does_not_rewrite_enumeration_or_other_resources(command, expected):
    assert scope_known_hub(command, "rg", ["hub", None]) == expected


@pytest.mark.parametrize("location,disabled", [("westus2", True), (HUB_TEST_LOCATION, False), (HUB_TEST_LOCATION, None)])
def test_supplied_hubs_must_meet_policy(location, disabled):
    with pytest.raises(AssertionError):
        assert_hub_policy({"location": location, "properties": {"disableLocalAuth": disabled}})


def test_fixture_creation_explicitly_sets_policy_and_location(mocker):
    mocker.patch.object(fixtures, "get_closest_marker", return_value=SimpleNamespace(kwargs={}))
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.return_value = {
        "location": HUB_TEST_LOCATION, "properties": {"disableLocalAuth": True}
    }
    result = fixtures._iot_hubs_provisioner(Mock())
    args = shlex.split(invoke.call_args.args[0])
    assert args[args.index("--location") + 1] == HUB_TEST_LOCATION
    assert args[args.index("--disable-local-auth") + 1] == "true"
    assert invoke.call_args.kwargs["capture_stderr"] is True
    assert invoke.call_count == 1  # No Hub list or key retrieval.
    assert "connectionString" not in result[0]


def test_fixture_cannot_override_canary_location(mocker):
    mocker.patch.object(fixtures, "get_closest_marker", return_value=SimpleNamespace(kwargs={"location": "westus2"}))
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    with pytest.raises(ValueError, match="must use"):
        fixtures._iot_hubs_provisioner(Mock())
    invoke.assert_not_called()


@pytest.mark.parametrize("with_storage", [False, True])
def test_scenario_create_explicitly_sets_policy_and_location(with_storage):
    scenario = SimpleNamespace(entity_name="hub", entity_rg="rg", cmd=Mock())
    if with_storage:
        scenario.storage_cstring = "storage-connection-string"
        scenario.storage_container = "container"
    IoTLiveScenarioTest._create_hub(scenario)
    args = shlex.split(scenario.cmd.call_args.args[0])
    assert args[args.index("--location") + 1] == HUB_TEST_LOCATION
    assert args[args.index("--disable-local-auth") + 1] == "true"
    assert ("--fcs" in args) is with_storage


@pytest.mark.parametrize("provisioner,command_prefix", [
    ("_user_identity_provisioner", "identity create"),
    ("_storage_provisioner", "storage account create"),
    ("_event_hub_provisioner", "eventhubs namespace create"),
    ("_service_bus_provisioner", "servicebus namespace create"),
    ("_cosmos_db_provisioner", "cosmosdb create"),
])
def test_dependency_resources_explicitly_use_hub_location(mocker, provisioner, command_prefix):
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.return_value = {
        "connectionString": "storage-connection-string",
        "primaryConnectionString": "endpoint-connection-string",
        "connectionStrings": [{
            "description": "Primary SQL Connection String", "connectionString": "cosmos-connection-string"
        }],
    }
    getattr(fixtures, provisioner)()
    commands = [call.args[0] for call in invoke.call_args_list if call.args[0].startswith(command_prefix)]
    assert len(commands) == 1
    if provisioner == "_cosmos_db_provisioner":
        assert f"--locations regionName={HUB_TEST_LOCATION}" in commands[0]
    else:
        assert f"--location {HUB_TEST_LOCATION}" in commands[0]


def test_device_stream_raw_create_sets_policy_and_location(mocker):
    from azext_iot.tests.iothub.device_stream import test_iothub_device_stream_int as streams

    invoke = mocker.patch.object(streams.cli, "invoke")
    fixture = streams.provisioned_preview_hub.__wrapped__()
    next(fixture)
    args = shlex.split(invoke.call_args.args[0])
    payload = json.loads(args[args.index("--properties") + 1])
    assert payload["location"] == HUB_TEST_LOCATION
    assert payload["properties"]["disableLocalAuth"] is True
    with pytest.raises(StopIteration):
        next(fixture)


def test_device_receiver_uses_device_credentials_and_always_shuts_down(mocker):
    factory = mocker.patch("azure.iot.device.IoTHubDeviceClient.create_from_connection_string")
    client = factory.return_value
    with pytest.raises(RuntimeError):
        with device_receiver("device-connection-string") as messages:
            client.on_message_received("message")
            assert messages.get_nowait() == "message"
            raise RuntimeError("Test failed")
    factory.assert_called_once_with("device-connection-string")
    client.connect.assert_called_once_with()
    client.shutdown.assert_called_once_with()


@pytest.mark.parametrize("id_key", [None, "deviceId", "moduleId"])
def test_query_wait_retries_only_until_exact_ids_are_visible(mocker, id_key):
    expected = ["device1", "device2"]
    rows = [{id_key: name} for name in expected] if id_key else expected
    read = Mock(side_effect=[[], rows[:1], rows])
    sleep = mocker.patch.object(integration_helpers, "sleep")
    assert integration_helpers.wait_for_query_ids(read, expected, id_key=id_key) == rows
    assert read.call_count == 3
    assert sleep.call_count == 2


def test_query_wait_exhaustion_preserves_observed_ids_and_fails(mocker):
    sleep = mocker.patch.object(integration_helpers, "sleep")
    read = Mock(return_value=["unexpected-device"])
    with pytest.raises(AssertionError, match="expected IDs.*new-device.*observed IDs.*unexpected-device"):
        integration_helpers.wait_for_query_ids(read, ["new-device"])
    assert read.call_count == 7
    assert sleep.call_count == 6


@pytest.mark.parametrize("status", [400, 403, 502])
def test_query_wait_never_retries_service_errors(mocker, status):
    sleep = mocker.patch.object(integration_helpers, "sleep")
    error = service_error(status, "ProviderError")
    read = Mock(side_effect=error)
    with pytest.raises(HttpResponseError) as raised:
        integration_helpers.wait_for_query_ids(read, ["device"])
    assert raised.value is error
    read.assert_called_once_with()
    sleep.assert_not_called()


@pytest.mark.parametrize("attempts,wait", [(0, 10), (1, -1)])
def test_query_wait_invalid_bounds_fail_before_reading(attempts, wait):
    read = Mock()
    with pytest.raises(ValueError, match="at least one attempt"):
        integration_helpers.wait_for_query_ids(read, [], attempts=attempts, wait=wait)
    read.assert_not_called()


@pytest.mark.parametrize("error_type", [HttpResponseError, integration_helpers.CloudError])
@pytest.mark.parametrize("status", [404, 400, 403, 409, 502])
def test_known_device_cleanup_ignores_only_actual_not_found(error_type, status):
    response = Response()
    response.status_code = status
    response._content = b"{}"
    error = error_type(response=response)
    devices = Mock()
    devices.delete_identity.side_effect = [error, None]
    if status == 404:
        integration_helpers.delete_known_devices(devices, ["owned-child", "owned-parent", "owned-child"])
        assert devices.delete_identity.call_count == 2
    else:
        with pytest.raises(error_type) as raised:
            integration_helpers.delete_known_devices(devices, ["owned-child", "owned-parent"])
        assert raised.value is error
        assert devices.delete_identity.call_count == 1
    devices.delete_identity.assert_any_call(id="owned-child", if_match="*")
    devices.get_devices.assert_not_called()


def test_edge_cleanup_uses_only_known_ids_with_entra(mocker):
    from azext_iot.tests.iothub.devices import test_iot_edge_devices_create_int as edge

    provider = mocker.patch.object(edge, "DeviceIdentityProvider")
    cleanup = mocker.patch.object(edge, "delete_known_devices")
    scenario = SimpleNamespace(entity_name="hub", entity_rg="rg", owned_device_ids=("child", "parent"))
    edge.TestNestedEdgeHierarchy._delete_owned_devices(scenario)
    provider.assert_called_once_with(cmd=scenario, hub_name="hub", rg="rg", auth_type_dataplane="login")
    cleanup.assert_called_once_with(provider.return_value.service_sdk.devices, ("child", "parent"))


def test_query_adapter_follows_continuation_after_an_empty_first_page():
    from azext_iot.operations.generic import _execute_query

    first = SimpleNamespace(response=SimpleNamespace(
        headers={"x-ms-continuation": "next"}, json=lambda: []
    ))
    last = SimpleNamespace(response=SimpleNamespace(
        headers={}, json=lambda: [{"deviceId": "owned-device"}]
    ))
    query = Mock(side_effect=[first, last])
    assert _execute_query(["SELECT deviceId FROM devices"], query) == [{"deviceId": "owned-device"}]
    assert query.call_count == 2
    assert query.call_args.kwargs["custom_headers"]["x-ms-continuation"] == "next"


@pytest.mark.parametrize("feedback_case", [
    "success", "success_with_noise", "missing", "wrong_device", "wrong_status", "wrong_message", "split_fields",
])
def test_c2d_feedback_scenario_checks_the_matching_stdout_record(mocker, feedback_case):
    from azext_iot.tests.iothub.messaging import test_iothub_c2d_messages_int as messaging

    mocker.patch.object(messaging, "uuid4", side_effect=["body", "message-id"])
    messages = Mock()
    messages.get.return_value = SimpleNamespace(data=b"body", message_id="message-id")
    receiver = mocker.patch.object(messaging, "device_receiver", return_value=nullcontext(messages))
    record = {"deviceId": "device", "statusCode": "Success", "originalMessageId": "message-id"}
    records = {
        "success": [record],
        "success_with_noise": [{**record, "originalMessageId": "other"}, record],
        "missing": [],
        "wrong_device": [{**record, "deviceId": "other"}],
        "wrong_status": [{**record, "statusCode": "Expired"}],
        "wrong_message": [{**record, "originalMessageId": "other"}],
        "split_fields": [{**record, "statusCode": "Expired"}, {**record, "originalMessageId": "other"}],
    }[feedback_case]

    def command_result(command, **kwargs):
        args = shlex.split(command)
        if args[:4] == ["iot", "device", "c2d-message", "send"]:
            assert args[args.index("--mid") + 1] == "message-id"
            assert args[args.index("--auth-type") + 1] == "login"
            assert args[args.index("--ack") + 1] == "full"
            assert "--wait" in args
            print("Starting C2D feedback monitor, use ctrl-c to stop...")
            for feedback in records:
                print(yaml.safe_dump({"feedback": feedback}, default_flow_style=False), flush=True)

    scenario = SimpleNamespace(
        generate_device_names=Mock(return_value=["device"]),
        entity_name="hub",
        entity_rg="rg",
        get_device_cstring=Mock(return_value="device-connection-string"),
        cmd=Mock(side_effect=command_result),
    )
    # Exercise the existing stdout-capture helper, not an invented ExecutionResult log.
    scenario.command_execute_assert = partial(CaptureOutputLiveScenarioTest.command_execute_assert, scenario)
    run = messaging.TestIoTHubC2DMessages.test_iothub_c2d_feedback
    if feedback_case.startswith("success"):
        run(scenario)
    else:
        with pytest.raises(AssertionError, match="No successful feedback"):
            run(scenario)
    messages.get.assert_called_once_with(timeout=60)
    receiver.assert_called_once_with("device-connection-string")


@pytest.mark.parametrize("collection", ["resources", "targets", "connection_strings"])
@pytest.mark.parametrize("missing_scope", [None, "subscription", "resource_group"])
def test_hub_collection_scenarios_require_owned_hub_not_cross_request_counts(mocker, collection, missing_scope):
    from azext_iot.tests.iothub.core import test_iothub_discovery_int as discovery_tests
    from azext_iot.tests.iothub.core import test_iothub_utilities_int as utility_tests

    metadata = {
        "cs": "metadata-only", "policy": "owner", "primarykey": "unused", "secondarykey": "unused",
        "entity": "hub.azure-devices.net", "subscription": "sub", "resourcegroup": "rg",
        "location": HUB_TEST_LOCATION, "sku_tier": "Standard",
        "events": {"endpoint": "endpoint", "partition_count": 2, "path": "path", "partition_ids": ["0", "1"]},
    }
    sub_hubs = [dict(metadata, name="other" if missing_scope == "subscription" else "hub")]
    rg_hubs = [dict(metadata, name="other" if missing_scope == "resource_group" else "hub")]
    if missing_scope is None:
        # Another worker can create a Hub between the two enumeration requests.
        rg_hubs.append(dict(metadata, name="new-hub"))
    scenario = SimpleNamespace(cmd_shell=Mock(), cli_ctx=Mock(), entity_name="hub", entity_rg="rg")

    if collection == "connection_strings":
        cli = mocker.patch.object(utility_tests, "EmbeddedCLI").return_value
        cli.invoke.return_value.as_json.side_effect = [sub_hubs, rg_hubs, []]
        run = utility_tests.TestIoTHubUtilities.test_iothub_connection_string_lists
    else:
        discovery = mocker.patch.object(discovery_tests, "IotHubDiscovery").return_value
        if collection == "resources":
            discovery.get_resources.side_effect = [sub_hubs, rg_hubs]
            run = discovery_tests.TestIoTHubDiscovery.test_iothub_discovery_lists
        else:
            discovery.get_targets.side_effect = [sub_hubs, rg_hubs]
            run = discovery_tests.TestIoTHubDiscovery.test_iothub_target_lists

    if missing_scope:
        with pytest.raises(AssertionError):
            run(scenario)
    else:
        run(scenario)


@pytest.mark.parametrize("unexpected_command,error_kind", [
    (None, None),
    ("simulate", "type"),
    ("send-d2c-message", "type"),
    ("simulate", "message"),
    ("send-d2c-message", "message"),
])
def test_x509_scenario_asserts_validation_exceptions_without_suppressing_them(mocker, unexpected_command, error_kind):
    from azext_iot.tests.iothub.core import test_iot_messaging_int as messaging

    mocker.patch.object(messaging, "read_file_content", return_value="{}")
    validation_calls = []
    unexpected_error = (
        RequiredArgumentMissingError("Unrelated missing argument")
        if error_kind == "message" else CLIInternalError("Unrelated command failure")
    )

    def command_result(command, **kwargs):
        from azure.cli.testsdk.base import ExecutionResult
        from azure.cli.testsdk.exceptions import CliExecutionError

        args = shlex.split(command)
        if args[:2] == ["iot", "device"] and (("--cp" in args) != ("--kp" in args)):
            assert "expect_failure" not in kwargs
            validation_calls.append(args[2])
            error = unexpected_error if args[2] == unexpected_command else RequiredArgumentMissingError(
                "Both 'certificate-file' and 'key-file' required for x509 certificate authentication."
            )
            # Exercise the real SDK path that unwraps its patched CLI exception.
            cli_ctx = SimpleNamespace(data={}, invoke=Mock(side_effect=CliExecutionError(error)))
            return ExecutionResult(cli_ctx, command)
        # Successful commands need no captured log; inspecting applog would fail.
        return None

    scenario = SimpleNamespace(
        generate_device_names=Mock(return_value=["device"]),
        entity_name="hub",
        entity_rg="rg",
        kwargs={},
        tracked_certs=[],
        check=Mock(),
        cmd=Mock(side_effect=command_result),
    )
    run = messaging.TestIoTHubMessaging.test_mqtt_device_simulation_x509
    if error_kind == "type":
        with pytest.raises(CLIInternalError) as raised:
            run(scenario)
        assert raised.value is unexpected_error
    elif error_kind == "message":
        with pytest.raises(AssertionError, match="Regex pattern did not match"):
            run(scenario)
    else:
        run(scenario)

    expected_calls = ["simulate"] if unexpected_command == "simulate" else ["simulate", "send-d2c-message"]
    assert validation_calls == expected_calls
