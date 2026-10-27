# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from azure.cli.core.azclierror import BadRequestError, CLIInternalError, ForbiddenError, UnauthorizedError
from azure.core.exceptions import HttpResponseError

from azext_iot.tests import helpers
from azext_iot.tests.adr import _helpers as readiness
from azext_iot.tests.deviceupdate import conftest as fixtures


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
CALLER = "current-caller@example.test"
ASSIGNMENT_NAME = "00000000-0000-0000-0000-000000000002"
HUB_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/adu-tests/providers/Microsoft.Devices/IotHubs/hub-1"
ASSIGNMENT_ID = f"{HUB_ID}/providers/Microsoft.Authorization/roleAssignments/{ASSIGNMENT_NAME}"
PROPAGATION_ERROR = (
    "ErrorCode:IotHubUnauthorized;Principal 00000000-0000-0000-0000-000000000003 "
    "is not authorized for POST on /devices/query due to no assigned permissions"
)


def _http_error(status):
    error = HttpResponseError(message=f"HTTP {status}")
    error.status_code = status
    return error


@pytest.fixture
def adu_hubs(mocker):
    state = SimpleNamespace(
        account={"id": SUBSCRIPTION, "user": {"name": CALLER}},
        assignments=[], query_rows=[], errors={}, commands=[], finalizers=[],
        hub_id=None, assignment_id=None, failed_command=None,
    )

    def invoke(command, **_kwargs):
        args = shlex.split(command)
        action = tuple(args[:3]) if args[0] != "account" else tuple(args[:2])
        state.commands.append(args)
        if action in state.errors:
            raise state.errors[action]
        if action == ("account", "show"):
            payload = state.account
        elif action == ("iot", "hub", "create"):
            name = args[args.index("-n") + 1]
            payload = {"id": state.hub_id or HUB_ID.rsplit("/", 1)[0] + "/" + name}
        elif action == ("role", "assignment", "list"):
            payload = state.assignments
        elif action == ("role", "assignment", "create"):
            scope = args[args.index("--scope") + 1]
            payload = {
                "id": state.assignment_id or
                f"{scope}/providers/Microsoft.Authorization/roleAssignments/{ASSIGNMENT_NAME}"
            }
        elif action == ("iot", "hub", "query"):
            payload = state.query_rows
        else:
            assert action in (("iot", "hub", "delete"), ("role", "assignment", "delete"))
            payload = None
        result = Mock(error_code=1 if action == state.failed_command else 0)
        result.success.return_value = action != state.failed_command
        result.as_json.return_value = payload
        return result

    state.cli = mocker.patch.object(fixtures, "cli")
    state.cli.invoke.side_effect = invoke
    mocker.patch.object(helpers, "cli", state.cli)
    mocker.patch.object(fixtures, "ACCOUNT_RG", "adu-tests")
    mocker.patch.object(fixtures, "generate_linked_hub_id", side_effect=["hub-1", "hub-2"])
    mocker.patch.object(fixtures, "uuid4", return_value=ASSIGNMENT_NAME)
    state.factory = mocker.patch.object(fixtures, "iot_hub_service_factory")
    state.lookup = state.factory.return_value.__enter__.return_value.iot_hub_resource.get
    state.lookup.side_effect = _http_error(404)
    state.request = Mock()
    state.request.node.get_closest_marker.return_value = SimpleNamespace(kwargs={"instance_count": 1})
    state.request.addfinalizer.side_effect = state.finalizers.append
    state.sleep = mocker.patch.object(readiness.time, "sleep")
    mocker.patch.object(readiness.time, "monotonic", return_value=0)
    return state


@pytest.mark.parametrize("marker", [None, SimpleNamespace(kwargs={}), SimpleNamespace(kwargs={"instance_count": 0})])
def test_no_adu_hubs_without_instance_request(adu_hubs, marker):
    adu_hubs.request.node.get_closest_marker.return_value = marker
    assert fixtures._iothub_provisioner(adu_hubs.request) is None
    adu_hubs.cli.invoke.assert_not_called()
    adu_hubs.factory.assert_not_called()
    assert not adu_hubs.finalizers


@pytest.mark.parametrize("caller", [CALLER, "00000000-0000-0000-0000-000000000003"])
def test_adu_dependency_hubs_enable_keys_and_grant_only_current_caller(adu_hubs, caller):
    adu_hubs.account["user"]["name"] = caller
    adu_hubs.request.node.get_closest_marker.return_value.kwargs["instance_count"] = 2
    hub_ids = [HUB_ID, HUB_ID.replace("hub-1", "hub-2")]

    assert fixtures._iothub_provisioner(adu_hubs.request) == {hub_id: {"id": hub_id} for hub_id in hub_ids}
    adu_hubs.factory.assert_called_once_with(adu_hubs.cli.az_cli, subscription_id=SUBSCRIPTION)
    assert adu_hubs.lookup.call_args_list == [
        call(resource_group_name="adu-tests", resource_name=name) for name in ("hub-1", "hub-2")
    ]
    for index, hub_id in enumerate(hub_ids):
        create, lookup, grant, probe = adu_hubs.commands[1 + index * 4:5 + index * 4]
        assert create == [
            "iot", "hub", "create", "-g", "adu-tests", "-n", hub_id.rsplit("/", 1)[1],
            "--subscription", SUBSCRIPTION, "--location", fixtures.HUB_TEST_LOCATION, "--disable-local-auth", "false",
        ]
        assert lookup == [
            "role", "assignment", "list", "--scope", hub_id, "--role", "IoT Hub Data Contributor",
            "--assignee", caller, "--fill-role-definition-name", "false",
        ]
        assert grant == [
            "role", "assignment", "create", "--assignee", caller, "--role", "IoT Hub Data Contributor",
            "--scope", hub_id, "--name", ASSIGNMENT_NAME, "--subscription", SUBSCRIPTION,
        ]
        assert probe == [
            "iot", "hub", "query", "-n", hub_id.rsplit("/", 1)[1], "-g", "adu-tests",
            "--subscription", SUBSCRIPTION, "--auth-type", "login",
            "--query-command", "SELECT deviceId FROM devices", "--top", "1",
        ]
    assert len(adu_hubs.finalizers) == 4
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
    assert [args[:3] for args in adu_hubs.commands[-4:]] == [
        ["role", "assignment", "delete"], ["iot", "hub", "delete"],
        ["role", "assignment", "delete"], ["iot", "hub", "delete"],
    ]
    assert adu_hubs.commands[-2:] == [
        ["role", "assignment", "delete", "--ids", ASSIGNMENT_ID, "--subscription", SUBSCRIPTION],
        ["iot", "hub", "delete", "--ids", HUB_ID],
    ]
    adu_hubs.sleep.assert_not_called()


def test_existing_caller_role_is_not_created_or_deleted_but_still_probed(adu_hubs):
    adu_hubs.assignments = [{"id": "preexisting-role"}]
    fixtures._iothub_provisioner(adu_hubs.request)
    assert [args[:3] for args in adu_hubs.commands[1:]] == [
        ["iot", "hub", "create"], ["role", "assignment", "list"], ["iot", "hub", "query"],
    ]
    assert len(adu_hubs.finalizers) == 1
    adu_hubs.finalizers[0]()
    assert adu_hubs.commands[-1] == ["iot", "hub", "delete", "--ids", HUB_ID]


@pytest.mark.parametrize("caller", [None, ""])
def test_missing_current_principal_fails_before_hub_creation(adu_hubs, caller):
    adu_hubs.account["user"]["name"] = caller
    with pytest.raises(RuntimeError, match="current principal"):
        fixtures._iothub_provisioner(adu_hubs.request)
    adu_hubs.factory.assert_not_called()
    assert not adu_hubs.finalizers


def test_preexisting_hub_is_never_adopted_granted_or_deleted(adu_hubs):
    adu_hubs.lookup.side_effect = None
    with pytest.raises(RuntimeError, match="Refusing to adopt existing"):
        fixtures._iothub_provisioner(adu_hubs.request)
    assert adu_hubs.commands == [["account", "show"]]
    assert not adu_hubs.finalizers


@pytest.mark.parametrize("status", [401, 403, 409, 500, 502])
def test_hub_lookup_failure_does_not_authorize_creation_or_cleanup(adu_hubs, status):
    error = _http_error(status)
    adu_hubs.lookup.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        fixtures._iothub_provisioner(adu_hubs.request)
    assert caught.value is error
    assert adu_hubs.commands == [["account", "show"]]
    assert not adu_hubs.finalizers


@pytest.mark.parametrize("action,cleanup_count", [
    (("account", "show"), 0),
    (("iot", "hub", "create"), 1),
    (("role", "assignment", "list"), 1),
    (("role", "assignment", "create"), 2),
    (("iot", "hub", "query"), 2),
])
def test_setup_permission_failures_propagate_and_owned_cleanup_remains_registered(adu_hubs, action, cleanup_count):
    error = ForbiddenError("AuthorizationFailed: fixture permission denied")
    adu_hubs.errors[action] = error
    with pytest.raises(ForbiddenError) as caught:
        fixtures._iothub_provisioner(adu_hubs.request)
    assert caught.value is error
    assert sum(tuple(args[:len(action)]) == action for args in adu_hubs.commands) == 1
    assert len(adu_hubs.finalizers) == cleanup_count
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
    if cleanup_count:
        assert adu_hubs.commands[-1] == ["iot", "hub", "delete", "--ids", HUB_ID]
    adu_hubs.sleep.assert_not_called()


@pytest.mark.parametrize("action", [
    ("iot", "hub", "create"), ("role", "assignment", "create"), ("iot", "hub", "query"),
])
def test_unsuccessful_commands_without_service_error_fail_closed(adu_hubs, action):
    adu_hubs.failed_command = action
    with pytest.raises(CLIInternalError, match="failed with exit code 1"):
        fixtures._iothub_provisioner(adu_hubs.request)
    assert sum(tuple(args[:3]) == action for args in adu_hubs.commands) == 1
    assert adu_hubs.finalizers


@pytest.mark.parametrize("action,cleanup_count", [
    (("iot", "hub", "create"), 1), (("role", "assignment", "create"), 2),
])
@pytest.mark.parametrize("error", [TimeoutError("create outcome unknown"), _http_error(503)])
def test_uncertain_creates_are_not_replayed_and_exact_cleanup_is_already_registered(
    adu_hubs, action, cleanup_count, error,
):
    adu_hubs.errors[action] = error
    with pytest.raises(type(error)) as caught:
        fixtures._iothub_provisioner(adu_hubs.request)
    assert caught.value is error
    assert sum(tuple(args[:3]) == action for args in adu_hubs.commands) == 1
    assert len(adu_hubs.finalizers) == cleanup_count
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
    assert adu_hubs.commands[-1] == ["iot", "hub", "delete", "--ids", HUB_ID]
    adu_hubs.sleep.assert_not_called()


@pytest.mark.parametrize("field,message", [
    ("hub_id", "owned ADU scope"), ("assignment_id", "role assignment ID changed"),
    ("assignments", "role-assignment response"), ("query_rows", "device-query response"),
])
def test_malformed_or_foreign_results_are_not_readiness_evidence(adu_hubs, field, message):
    setattr(adu_hubs, field, "foreign-or-malformed")
    with pytest.raises((AssertionError, RuntimeError), match=message):
        fixtures._iothub_provisioner(adu_hubs.request)
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
    delete_args = [args for args in adu_hubs.commands if "delete" in args]
    assert all("foreign-or-malformed" not in args for args in delete_args)
    assert delete_args[-1] == ["iot", "hub", "delete", "--ids", HUB_ID]


def test_second_hub_setup_failure_keeps_both_owned_hubs_cleanup(adu_hubs):
    adu_hubs.request.node.get_closest_marker.return_value.kwargs["instance_count"] = 2
    original = adu_hubs.cli.invoke.side_effect
    error = ForbiddenError("second Hub create denied")

    def invoke(command, **kwargs):
        if "create" in command and "-n hub-2" in command:
            raise error
        return original(command, **kwargs)

    adu_hubs.cli.invoke.side_effect = invoke
    with pytest.raises(ForbiddenError) as caught:
        fixtures._iothub_provisioner(adu_hubs.request)
    assert caught.value is error
    assert len(adu_hubs.finalizers) == 3
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
    assert adu_hubs.commands[-3] == ["iot", "hub", "delete", "--ids", HUB_ID.replace("hub-1", "hub-2")]
    assert adu_hubs.commands[-1] == ["iot", "hub", "delete", "--ids", HUB_ID]


@pytest.mark.parametrize("error_type", [UnauthorizedError, ForbiddenError])
@pytest.mark.parametrize("message", [PROPAGATION_ERROR, {"Message": PROPAGATION_ERROR}])
def test_only_device_query_authorization_propagation_is_retried(adu_hubs, error_type, message):
    fixtures._iothub_provisioner(adu_hubs.request)
    adu_hubs.commands.clear()
    adu_hubs.errors[("iot", "hub", "query")] = error_type(message)
    adu_hubs.sleep.side_effect = lambda _seconds: adu_hubs.errors.clear()
    fixtures._iothub_wait_for_data_role(HUB_ID)
    assert len(adu_hubs.commands) == 2
    assert all(args[:3] == ["iot", "hub", "query"] and "login" in args for args in adu_hubs.commands)
    adu_hubs.sleep.assert_called_once_with(10)


@pytest.mark.parametrize("error", [
    BadRequestError({
        "Message": "ErrorCode:ArgumentInvalid;BadRequest",
        "ExceptionMessage": "Tracking ID:00000000-0000-0000-0000-000000000004-G:0-TimeStamp:09/22/2026 23:38:41",
    }),
    UnauthorizedError("token expired"),
    ForbiddenError("AuthorizationFailed for POST/devices/query"),
    ForbiddenError("IotHubUnauthorized for PUT/devices/device-1"),
    UnauthorizedError("IotHubUnauthorized: no assigned permissions for POST/devices/query"),
    UnauthorizedError({"Message": PROPAGATION_ERROR.replace("no assigned permissions", "token expired")}),
    ForbiddenError({"Message": PROPAGATION_ERROR.replace("no assigned permissions", "an explicit deny assignment")}),
    UnauthorizedError(PROPAGATION_ERROR.replace("IotHubUnauthorized", "AuthorizationFailed")),
    ForbiddenError(PROPAGATION_ERROR.replace("POST on", "GET on")),
    UnauthorizedError(PROPAGATION_ERROR.replace("/devices/query", "/devices/query/other")),
    ForbiddenError(PROPAGATION_ERROR.replace("/devices/query", "/devices/device-1")),
    RuntimeError(PROPAGATION_ERROR),
    _http_error(500),
])
def test_unrelated_probe_errors_are_not_retried(adu_hubs, error):
    adu_hubs.errors[("iot", "hub", "query")] = error
    with pytest.raises(type(error)) as caught:
        fixtures._iothub_wait_for_data_role(HUB_ID)
    assert caught.value is error
    assert len(adu_hubs.commands) == 1
    adu_hubs.sleep.assert_not_called()


def test_permission_never_propagates_fails_bounded_setup_and_keeps_cleanup(adu_hubs):
    adu_hubs.errors[("iot", "hub", "query")] = UnauthorizedError(PROPAGATION_ERROR)
    with pytest.raises(AssertionError, match="Timed out.*13 attempt.*IotHubUnauthorized"):
        fixtures._iothub_provisioner(adu_hubs.request)
    assert sum(args[:3] == ["iot", "hub", "query"] for args in adu_hubs.commands) == 13
    assert sum(args[:3] == ["role", "assignment", "create"] for args in adu_hubs.commands) == 1
    assert adu_hubs.sleep.call_count == 12
    assert len(adu_hubs.finalizers) == 2
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()


def test_probe_elapsed_time_budget_is_bounded(adu_hubs, mocker):
    mocker.patch.object(readiness.time, "monotonic", side_effect=[0, 120])
    adu_hubs.errors[("iot", "hub", "query")] = UnauthorizedError(PROPAGATION_ERROR)
    with pytest.raises(AssertionError, match="Timed out.*1 attempt"):
        fixtures._iothub_wait_for_data_role(HUB_ID)
    assert len(adu_hubs.commands) == 1
    adu_hubs.sleep.assert_not_called()


@pytest.mark.parametrize("action", [("role", "assignment", "delete"), ("iot", "hub", "delete")])
def test_cleanup_failures_are_reported_and_hub_cleanup_is_independent(adu_hubs, action):
    fixtures._iothub_provisioner(adu_hubs.request)
    error = ForbiddenError("owned cleanup denied")
    adu_hubs.errors[action] = error
    role_cleanup, hub_cleanup = reversed(adu_hubs.finalizers)
    failing, other = (role_cleanup, hub_cleanup) if action[0] == "role" else (hub_cleanup, role_cleanup)
    with pytest.raises(ForbiddenError) as caught:
        failing()
    assert caught.value is error
    other()
    assert any(args[:3] == ["iot", "hub", "delete"] for args in adu_hubs.commands)


@pytest.mark.parametrize("fixture", [fixtures.provisioned_iothubs, fixtures.provisioned_iothubs_module])
@pytest.mark.parametrize("instance_count", [0, 1])
def test_both_fixture_scopes_use_registered_cleanup_without_duplicate_deletion(adu_hubs, fixture, instance_count):
    adu_hubs.request.node.get_closest_marker.return_value.kwargs["instance_count"] = instance_count
    generator = fixture.__wrapped__(adu_hubs.request)
    assert next(generator) == ({HUB_ID: {"id": HUB_ID}} if instance_count else None)
    with pytest.raises(StopIteration):
        next(generator)
    assert not any("delete" in args for args in adu_hubs.commands)
    assert len(adu_hubs.finalizers) == instance_count * 2
    for cleanup in reversed(adu_hubs.finalizers):
        cleanup()
