# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from collections import defaultdict
from copy import deepcopy
from functools import partial
from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from azure.cli.core.azclierror import (
    BadRequestError, CLIInternalError, RequiredArgumentMissingError, ResourceNotFoundError,
)

from azext_iot.tests.iothub._integration_helpers import wait_for_query_ids
from azext_iot.tests.iothub.state import _state_helpers as subject
from azext_iot.tests.iothub.state import test_hub_state_dataplane_int as dataplane
from azext_iot.tests.iothub.state import test_hub_state_int as controlplane


@pytest.fixture
def fake_cli(mocker):
    client = SimpleNamespace(
        exception_handler=mocker.Mock(return_value=1),
        result=SimpleNamespace(error=None),
    )
    mocker.patch.object(subject.cli, "az_cli", client)
    return client


@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
@pytest.mark.parametrize("scenario,failed_operation,expected_events", [
    ("test_migrate_dataplane", None, ["migrate", "ready", "compare"]),
    ("test_migrate_dataplane", "migrate", ["migrate"]),
    ("test_export_import_dataplane", None, ["export", "compare", "cleanup", "import", "ready", "compare"]),
    ("test_export_import_dataplane", "export", ["export"]),
    ("test_export_import_dataplane", "import", ["export", "compare", "cleanup", "import"]),
])
def test_state_command_error_precedes_comparison(
    mocker, fake_cli, scenario, failed_operation, expected_events, failure_kind
):
    events = []
    error = BadRequestError("Original state command failure")
    exit_code = 2 if failure_kind == "system_exit" else 7

    def invoke(args, out_file):
        assert args[:3] == ["iot", "hub", "state"]
        operation = args[3]
        if operation in ("export", "import"):
            assert args[args.index("-f") + 1] == "state directory/state.json"
        events.append(operation)
        fake_cli.result.error = error if operation == failed_operation and failure_kind == "cli_error" else None
        if operation == failed_operation:
            if failure_kind == "system_exit":
                raise SystemExit(exit_code)
            return exit_code
        out_file.write("{}")
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject.time, "sleep")
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    readiness = mocker.patch.object(
        subject, "_wait_for_dataplane_query", side_effect=lambda *args: events.append("ready")
    )
    compare_hubs = mocker.patch.object(subject, "compare_hubs_dataplane", side_effect=lambda *args: events.append("compare"))
    compare_file = mocker.patch.object(
        subject, "compare_hub_dataplane_to_file", side_effect=lambda *args: events.append("compare")
    )
    mocker.patch.object(subject, "clean_up_hub_dataplane", side_effect=lambda *args: events.append("cleanup"))
    owned = subject._OwnedDataplaneState(config_ids=["owned-config"], device_ids=["owned-device"])
    hubs = [
        {"name": "origin", "rg": "rg", "filename": "state directory/state.json", "state_data": owned},
        {"name": "destination", "rg": "rg"},
    ]

    if failed_operation:
        expected_error = BadRequestError if failure_kind == "cli_error" else CLIInternalError
        with pytest.raises(expected_error) as raised:
            getattr(dataplane, scenario)(hubs)
        if failure_kind == "cli_error":
            assert raised.value is error
        else:
            assert str(raised.value) == f"IoT Hub state command failed with exit code {exit_code}."
    else:
        getattr(dataplane, scenario)(hubs)
    assert events == expected_events
    for call in readiness.call_args_list:
        assert call.args[0] == subject._hub_auth(hubs[1] if scenario == "test_migrate_dataplane" else hubs[0])
        assert call.args[1] is owned
    for call in compare_hubs.call_args_list + compare_file.call_args_list:
        assert call.args[-1] is owned


@pytest.mark.parametrize("scenario", [
    "test_mirgate_hub_dataplane_error",
    "test_export_import_migrate_missing_hubs_error",
])
@pytest.mark.parametrize("outcome", ["expected_error", "success", "unrelated_error"])
def test_expected_state_failures_still_assert_original_error(mocker, fake_cli, scenario, outcome):
    def invoke(args, out_file):
        if outcome == "success":
            error = None
        elif outcome == "unrelated_error":
            error = BadRequestError("Unrelated failure")
        elif args[3] == "import" and "-g" not in args:
            error = RequiredArgumentMissingError("Resource group required")
        else:
            error = ResourceNotFoundError("Hub not found")
        fake_cli.result.error = error
        return 1 if error else 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    args = ([{"name": "hub", "rg": "rg"}],) if scenario == "test_mirgate_hub_dataplane_error" else ()
    if outcome == "expected_error":
        getattr(controlplane, scenario)(*args)
        assert fake_cli.invoke.call_count == (1 if args else 5)
    else:
        with pytest.raises(AssertionError):
            getattr(controlplane, scenario)(*args)


def _http_error(mocker, status):
    response = mocker.Mock(status_code=status, reason="Test failure", headers={})
    response.text.return_value = ""
    return HttpResponseError(message="Test service failure", response=response)


@pytest.fixture
def state_request(mocker):
    request = mocker.Mock()
    request.node.get_closest_marker.return_value = SimpleNamespace(kwargs={"count": 2})
    return request


@pytest.fixture
def state_backend(mocker, fake_cli):
    states = {
        name: {"devices": set(), "configs": set()}
        for name in ("origin", "destination")
    }
    deleted = []
    clients = {}

    def delete(name, kind, item_id):
        deleted.append((name, kind, item_id))
        if item_id not in states[name][kind]:
            raise _http_error(mocker, 404)
        states[name][kind].remove(item_id)

    for name in states:
        client = mocker.Mock()
        client.devices.get_devices.side_effect = lambda top, name=name: list(states[name]["devices"])[:top]
        client.configuration.get_configurations.side_effect = lambda top, name=name: list(states[name]["configs"])[:top]
        client.devices.delete_identity.side_effect = (
            lambda id, if_match, name=name: delete(name, "devices", id)
        )
        client.configuration.delete.side_effect = (
            lambda id, if_match, name=name: delete(name, "configs", id)
        )
        clients[name] = client

    def invoke(args, out_file):
        fake_cli.result.error = None
        name = args[args.index("--hub-name") + 1]
        if args[:3] == ["iot", "hub", "query"]:
            assert args[args.index("-q") + 1] == "select deviceId from devices"
            out_file.write(json.dumps([{"deviceId": device} for device in sorted(states[name]["devices"])]))
            return 0
        kind = None
        if args[:4] == ["iot", "hub", "configuration", "create"]:
            kind, id_flag = "configs", "--config-id"
        elif args[:4] == ["iot", "edge", "deployment", "create"]:
            kind, id_flag = "configs", "-d"
        elif args[:4] == ["iot", "hub", "device-identity", "create"]:
            kind, id_flag = "devices", "-d"
        if kind:
            item_id = args[args.index(id_flag) + 1]
            if item_id in states[name][kind]:
                fake_cli.result.error = BadRequestError("ConfigurationAlreadyExists")
                return 1
            states[name][kind].add(item_id)
        out_file.write("{}")
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject, "_state_service_sdk", side_effect=lambda hub: clients[hub["name"]])
    role_assignment = mocker.patch.object(subject, "assign_iot_hub_dataplane_rbac_role")
    mocker.patch.object(subject.time, "sleep")
    mocker.patch.object(subject, "generate_key", return_value="unit-key")
    mocker.patch.object(subject, "create_self_signed_certificate", return_value={"thumbprint": "unit-thumbprint"})
    return SimpleNamespace(
        hubs=[{"name": "origin", "rg": "rg"}, {"name": "destination", "rg": "rg"}, {"name": "unrelated"}],
        states=states, clients=clients, deleted=deleted, invoke=invoke, role_assignment=role_assignment,
    )


def _state_fixture(backend, request, tmp_path):
    return subject.setup_hub_states_dataplane.__wrapped__(backend.hubs, request, tmp_path)


def _matches_setup_command(args, operation):
    prefixes = {
        "configuration": ["iot", "hub", "configuration", "create"],
        "deployment": ["iot", "edge", "deployment", "create"],
        "layered": ["iot", "edge", "deployment", "create"],
        "device": ["iot", "hub", "device-identity", "create"],
        "module": ["iot", "hub", "module-identity", "create"],
        "device_twin": ["iot", "hub", "device-twin", "update"],
        "module_twin": ["iot", "hub", "module-twin", "update"],
        "set_modules": ["iot", "edge", "set-modules"],
        "children": ["iot", "hub", "device-identity", "children", "add"],
    }
    prefix = prefixes[operation]
    matches = args[:len(prefix)] == prefix
    if operation in ("deployment", "layered"):
        matches = matches and ("--layered" in args) == (operation == "layered")
    return matches


@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
@pytest.mark.parametrize("operation", [
    "configuration", "deployment", "layered", "device", "module",
    "device_twin", "module_twin", "set_modules", "children",
])
def test_setup_failure_is_visible_and_cleans_partial_state(
    mocker, fake_cli, state_backend, state_request, tmp_path, failure_kind, operation
):
    error = BadRequestError("ConfigurationAlreadyExists")
    exit_code = 2 if failure_kind == "system_exit" else 7

    def invoke(args, out_file):
        if _matches_setup_command(args, operation):
            fake_cli.result.error = error if failure_kind == "cli_error" else None
            if failure_kind == "system_exit":
                raise SystemExit(exit_code)
            return exit_code
        return state_backend.invoke(args, out_file)

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    expected = BadRequestError if failure_kind == "cli_error" else CLIInternalError
    with pytest.raises(expected) as raised:
        next(fixture)
    if failure_kind == "cli_error":
        assert raised.value is error
    else:
        assert str(raised.value) == f"IoT Hub state setup failed with exit code {exit_code}."
    assert all(not values for state in state_backend.states.values() for values in state.values())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("operation", ["deployment", "layered"])
def test_setup_collision_preserves_the_conflicting_resource(
    mocker, fake_cli, state_backend, state_request, tmp_path, operation
):
    conflicting_ids = []

    def invoke(args, out_file):
        if _matches_setup_command(args, operation):
            item_id = args[args.index("-d") + 1]
            conflicting_ids.append(item_id)
            state_backend.states["origin"]["configs"].add(item_id)
        return state_backend.invoke(args, out_file)

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    with pytest.raises(BadRequestError, match="ConfigurationAlreadyExists"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    assert state_backend.states["origin"]["configs"] == set(conflicting_ids)
    assert all(item_id not in conflicting_ids for _, _, item_id in state_backend.deleted)


@pytest.mark.parametrize("hub_name", ["origin", "destination"])
@pytest.mark.parametrize("kind", ["devices", "configs"])
def test_borrowed_data_blocks_setup_without_deleting_it(
    fake_cli, state_backend, state_request, tmp_path, hub_name, kind
):
    state_backend.states[hub_name][kind].add("borrowed")
    with pytest.raises(CLIInternalError, match="pre-existing dataplane"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    assert state_backend.states[hub_name][kind] == {"borrowed"}
    fake_cli.invoke.assert_not_called()
    assert state_backend.deleted == []


@pytest.mark.parametrize("hub_name", ["origin", "destination"])
@pytest.mark.parametrize("kind", ["devices", "configs"])
@pytest.mark.parametrize("response", [None, {}, ()])
def test_invalid_listing_cannot_establish_ownership(
    fake_cli, state_backend, state_request, tmp_path, hub_name, kind, response
):
    client = state_backend.clients[hub_name]
    read = client.devices.get_devices if kind == "devices" else client.configuration.get_configurations
    read.side_effect = None
    read.return_value = response
    with pytest.raises(CLIInternalError, match="invalid .* listing"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    fake_cli.invoke.assert_not_called()
    assert state_backend.deleted == []


def test_same_hub_cannot_be_source_and_destination(fake_cli, state_backend, state_request, tmp_path):
    state_backend.hubs[1] = {"name": "ORIGIN", "rg": "RG"}
    with pytest.raises(CLIInternalError, match="distinct source and destination"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    fake_cli.invoke.assert_not_called()
    state_backend.role_assignment.assert_not_called()
    assert state_backend.deleted == []


@pytest.mark.parametrize("count", [0, 4])
def test_invalid_hub_count_fails_before_setup(fake_cli, state_backend, state_request, tmp_path, count):
    state_request.node.get_closest_marker.return_value.kwargs["count"] = count
    with pytest.raises(CLIInternalError, match="requires the requested provisioned hubs"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    fake_cli.invoke.assert_not_called()
    state_backend.role_assignment.assert_not_called()
    assert state_backend.deleted == []


@pytest.mark.parametrize("count", [None, 1, 2])
def test_sequential_state_fixtures_own_distinct_data_and_preserve_shared_pool(
    state_backend, state_request, tmp_path, count
):
    if count is None:
        state_request.node.get_closest_marker.return_value = None
    else:
        state_request.node.get_closest_marker.return_value.kwargs["count"] = count
    borrowed_file = tmp_path / "borrowed.json"
    borrowed_file.write_text("borrowed", encoding="utf-8")
    state_backend.hubs[0]["filename"] = str(borrowed_file)
    previous_ids = set()
    for _ in range(2):
        fixture = _state_fixture(state_backend, state_request, tmp_path)
        hubs = next(fixture)
        assert len(hubs) == (count or 1)
        assert hubs[0] is not state_backend.hubs[0]
        owned = hubs[0]["state_data"]
        assert len(owned.config_ids) == 3
        assert len(owned.device_ids) == 6
        assert any(item.startswith("deployment1-") for item in owned.config_ids)
        assert any(item.startswith("deployment2-") for item in owned.config_ids)
        ids = set(owned.config_ids + owned.device_ids)
        assert ids.isdisjoint(previous_ids)
        previous_ids = ids
        for hub in hubs[1:]:
            state_backend.states[hub["name"]]["configs"].update(owned.config_ids)
            state_backend.states[hub["name"]]["devices"].update(owned.device_ids)
        output = subject.Path(hubs[0]["filename"])
        output.write_text("{}", encoding="utf-8")
        subject.clean_up_hub_dataplane(hubs[0])
        state_backend.states["origin"]["configs"].update(owned.config_ids)
        state_backend.states["origin"]["devices"].update(owned.device_ids)
        fixture.close()
        assert not output.exists()
        assert all(not values for state in state_backend.states.values() for values in state.values())
    assert borrowed_file.read_text(encoding="utf-8") == "borrowed"
    assert state_backend.hubs[0]["filename"] == str(borrowed_file)
    assert all("state_data" not in hub for hub in state_backend.hubs)


def test_overlapping_fixture_cannot_delete_an_existing_lease(state_backend, state_request, tmp_path):
    first = _state_fixture(state_backend, state_request, tmp_path)
    hubs = next(first)
    owned = hubs[0]["state_data"]
    with pytest.raises(CLIInternalError, match="pre-existing dataplane"):
        next(_state_fixture(state_backend, state_request, tmp_path))
    assert state_backend.states["origin"]["devices"] == set(owned.device_ids)
    assert state_backend.deleted == []
    first.close()


def test_cleanup_preserves_unowned_ids_added_to_a_shared_hub(state_backend, state_request, tmp_path):
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    next(fixture)
    state_backend.states["origin"]["devices"].add("borrowed-device")
    state_backend.states["origin"]["configs"].add("deployment1")
    fixture.close()
    assert state_backend.states["origin"] == {"devices": {"borrowed-device"}, "configs": {"deployment1"}}
    assert all(item_id not in {"borrowed-device", "deployment1"} for _, _, item_id in state_backend.deleted)


@pytest.mark.parametrize("kind", ["devices", "configs"])
def test_teardown_failure_propagates_after_other_owned_cleanup(
    mocker, state_backend, state_request, tmp_path, kind
):
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    hubs = next(fixture)
    owned = hubs[0]["state_data"]
    output = subject.Path(hubs[0]["filename"])
    output.write_text("{}", encoding="utf-8")
    errors = []

    def fail_delete(**_kwargs):
        error = _http_error(mocker, 500)
        errors.append(error)
        raise error

    client = state_backend.clients["destination"]
    delete = client.devices.delete_identity if kind == "devices" else client.configuration.delete
    delete.side_effect = fail_delete
    with pytest.raises(HttpResponseError) as raised:
        fixture.close()
    assert raised.value is errors[-1]
    assert delete.call_count == (len(owned.device_ids) if kind == "devices" else len(owned.config_ids))
    assert state_backend.states["origin"] == {"devices": set(), "configs": set()}
    assert not output.exists()


def test_fixture_cleanup_runs_after_a_test_assertion(state_backend, state_request, tmp_path):
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    hubs = next(fixture)
    owned = hubs[1]["state_data"]
    state_backend.states["destination"]["devices"].update(owned.device_ids[:2])
    state_backend.states["destination"]["configs"].update(owned.config_ids[:1])
    with pytest.raises(AssertionError, match="test failed"):
        fixture.throw(AssertionError("test failed"))
    assert all(not values for state in state_backend.states.values() for values in state.values())


@pytest.mark.parametrize("status", [None, 403, 404, 500])
def test_owned_configuration_cleanup_only_ignores_actual_not_found(mocker, status):
    configurations = mocker.Mock()
    error = _http_error(mocker, status)
    configurations.delete.side_effect = error
    if status == 404:
        subject._delete_owned_configuration(configurations, "owned")
    else:
        with pytest.raises(HttpResponseError) as raised:
            subject._delete_owned_configuration(configurations, "owned")
        assert raised.value is error
    configurations.delete.assert_called_once_with(id="owned", if_match="*")


def test_registry_ownership_client_preserves_hub_context(mocker):
    provider = mocker.patch.object(subject, "DeviceIdentityProvider")
    client = subject._state_service_sdk({"name": "hub", "rg": "group"})
    assert client is provider.return_value.service_sdk
    kwargs = provider.call_args.kwargs
    assert kwargs["cmd"].cli_ctx is subject.cli.az_cli
    assert kwargs["hub_name"] == "hub"
    assert kwargs["rg"] == "group"
    assert kwargs["auth_type_dataplane"] == "login"


@pytest.fixture
def bounded_query_wait(mocker):
    return mocker.patch.object(
        subject, "wait_for_query_ids", side_effect=partial(wait_for_query_ids, attempts=3, wait=0),
    )


def test_source_fixture_waits_after_all_writes_before_exposing_owned_state(
    mocker, fake_cli, state_backend, state_request, tmp_path, bounded_query_wait
):
    queries = []

    def invoke(args, out_file):
        if args[:3] == ["iot", "hub", "query"]:
            devices = sorted(state_backend.states["origin"]["devices"])
            assert len(devices) == 6
            assert len(state_backend.states["origin"]["configs"]) == 3
            assert not state_backend.states["destination"]["devices"]
            queries.append(args)
            out_file.write(json.dumps([{"deviceId": device} for device in devices[:len(devices) if len(queries) == 2 else 1]]))
            return 0
        assert not queries, "Setup must finish before query readiness starts."
        return state_backend.invoke(args, out_file)

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    hubs = next(fixture)
    assert len(queries) == 2
    bounded_query_wait.assert_called_once()
    assert bounded_query_wait.call_args.args[1] is hubs[0]["state_data"].device_ids
    assert hubs[1]["state_data"].device_ids == hubs[0]["state_data"].device_ids
    fixture.close()
    assert all(not values for state in state_backend.states.values() for values in state.values())


@pytest.mark.parametrize("failure", ["omission", "duplicate", "wrong_id", "cli_error", "nonzero", "system_exit"])
def test_source_query_failure_cleans_only_written_owned_state(
    mocker, fake_cli, state_backend, state_request, tmp_path, bounded_query_wait, failure
):
    error = BadRequestError("Source query failed")
    queries = []
    written = set()

    def invoke(args, out_file):
        if args[:3] != ["iot", "hub", "query"]:
            return state_backend.invoke(args, out_file)
        queries.append(args)
        state_backend.states["destination"]["devices"].add("borrowed")
        written.update(state_backend.states["origin"]["devices"] | state_backend.states["origin"]["configs"])
        fake_cli.result.error = error if failure == "cli_error" else None
        if failure == "system_exit":
            raise SystemExit(7)
        devices = sorted(state_backend.states["origin"]["devices"])
        if failure == "duplicate":
            devices.append(devices[-1])
        elif failure == "wrong_id":
            devices[-1] = "unowned"
        else:
            devices = []
        out_file.write(json.dumps([{"deviceId": device} for device in devices]))
        return 7 if failure in ("cli_error", "nonzero") else 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    expected = {
        "cli_error": BadRequestError, "nonzero": CLIInternalError, "system_exit": CLIInternalError,
    }.get(failure, AssertionError)
    with pytest.raises(expected) as raised:
        next(_state_fixture(state_backend, state_request, tmp_path))
    if failure == "cli_error":
        assert raised.value is error
    assert len(queries) == (1 if failure in ("cli_error", "nonzero", "system_exit") else 3)
    bounded_query_wait.assert_called_once()
    assert {item_id for _, _, item_id in state_backend.deleted} == written
    assert all(name == "origin" for name, _, _ in state_backend.deleted)
    assert state_backend.states["origin"] == {"devices": set(), "configs": set()}
    assert state_backend.states["destination"]["devices"] == {"borrowed"}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("scenario", ["test_migrate_dataplane", "test_export_import_dataplane"])
@pytest.mark.parametrize("failure", [None, "omission", "cli_error", "nonzero"])
def test_destination_readiness_does_not_replay_writes_or_hide_export_failures(
    mocker, fake_cli, bounded_query_wait, scenario, failure
):
    owned = subject._OwnedDataplaneState(config_ids=["config"], device_ids=["one", "two"])
    hubs = [
        {"name": "origin", "rg": "rg", "filename": "state.json", "state_data": owned},
        {"name": "destination", "rg": "rg", "state_data": owned},
    ]
    events = []
    queries = []
    error = BadRequestError("Destination query failed")

    def invoke(args, out_file):
        fake_cli.result.error = error if args[:3] == ["iot", "hub", "query"] and failure == "cli_error" else None
        if args[:3] == ["iot", "hub", "query"]:
            events.append("query")
            queries.append(args)
            name = "destination" if scenario == "test_migrate_dataplane" else "origin"
            assert args[args.index("--hub-name") + 1] == name
            assert args[args.index("--auth-type") + 1] == "login"
            assert args[args.index("-q") + 1] == "select deviceId from devices"
            rows = [{"deviceId": "one"}]
            if failure is None and len(queries) == 2:
                rows.append({"deviceId": "two"})
            out_file.write(json.dumps(rows))
            return 7 if failure in ("cli_error", "nonzero") else 0
        events.append(args[3])
        out_file.write("{}")
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    mocker.patch.object(subject, "compare_hubs_dataplane", side_effect=lambda *args: events.append("compare"))
    mocker.patch.object(subject, "compare_hub_dataplane_to_file", side_effect=lambda *args: events.append("compare"))
    mocker.patch.object(subject, "clean_up_hub_dataplane", side_effect=lambda *args: events.append("cleanup"))
    if failure:
        expected = {"omission": AssertionError, "cli_error": BadRequestError, "nonzero": CLIInternalError}[failure]
        with pytest.raises(expected) as raised:
            getattr(dataplane, scenario)(hubs)
        if failure == "cli_error":
            assert raised.value is error
    else:
        getattr(dataplane, scenario)(hubs)
    prefix = ["migrate"] if scenario == "test_migrate_dataplane" else ["export", "compare", "cleanup", "import"]
    suffix = [] if failure else ["compare"]
    assert events == prefix + ["query"] * len(queries) + suffix
    assert len(queries) == (2 if failure is None else 3 if failure == "omission" else 1)
    bounded_query_wait.assert_called_once()


def test_invalid_export_fails_before_import_or_a_destination_visibility_wait(mocker):
    owned = subject._OwnedDataplaneState(config_ids=["config"], device_ids=["device"])
    hubs = [{"name": "origin", "rg": "rg", "filename": "state.json", "state_data": owned}]
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    invoke = mocker.patch.object(subject, "_invoke_state")
    compare = mocker.patch.object(subject, "compare_hub_dataplane_to_file", side_effect=AssertionError("incomplete export"))
    ready = mocker.patch.object(subject, "_wait_for_dataplane_query")
    with pytest.raises(AssertionError, match="incomplete export"):
        dataplane.test_export_import_dataplane(hubs)
    invoke.assert_called_once()
    assert invoke.call_args.args[0].startswith("iot hub state export")
    compare.assert_called_once()
    ready.assert_not_called()


@pytest.mark.parametrize("auth_phases", [["login"], ["login", "key"]])
@pytest.mark.parametrize("failure", [None, "compare", "cleanup"])
def test_final_migration_cleanup_belongs_to_fixture(
    mocker, state_backend, state_request, tmp_path, auth_phases, failure
):
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", auth_phases)
    fixture = _state_fixture(state_backend, state_request, tmp_path)
    hubs = next(fixture)
    owned = hubs[0]["state_data"]
    destination = state_backend.states["destination"]
    events = []

    def migrate(command):
        assert command.startswith("iot hub state migrate ")
        assert not destination["devices"] and not destination["configs"]
        destination["devices"].update(owned.device_ids)
        destination["configs"].update(owned.config_ids)
        events.append("migrate")

    def compare(origin_auth, dest_auth, expected):
        assert origin_auth == subject._hub_auth(hubs[0])
        assert dest_auth == subject._hub_auth(hubs[1])
        assert expected is owned
        events.append("compare")
        if failure == "compare":
            raise AssertionError("comparison failed")

    mocker.patch.object(subject, "_invoke_state", side_effect=migrate)
    mocker.patch.object(subject, "compare_hubs_dataplane", side_effect=compare)
    if failure == "compare":
        with pytest.raises(AssertionError, match="comparison failed"):
            dataplane.test_migrate_dataplane(hubs)
    else:
        dataplane.test_migrate_dataplane(hubs)
    assert destination["devices"] == set(owned.device_ids)
    assert destination["configs"] == set(owned.config_ids)
    assert hubs[1]["state_data"].device_ids == owned.device_ids
    assert hubs[1]["state_data"].config_ids == owned.config_ids
    phases_run = 1 if failure == "compare" else len(auth_phases)
    assert events == ["migrate", "compare"] * phases_run
    assert len(state_backend.deleted) == (phases_run - 1) * 9

    if failure == "cleanup":
        def fail_delete(**_kwargs):
            raise _http_error(mocker, 500)

        state_backend.clients["destination"].devices.delete_identity.side_effect = fail_delete
        with pytest.raises(HttpResponseError):
            fixture.close()
    else:
        fixture.close()
        assert not destination["devices"] and not destination["configs"]
        for item_id in owned.device_ids + owned.config_ids:
            assert sum(name == "destination" and deleted_id == item_id
                       for name, _, deleted_id in state_backend.deleted) == phases_run
    assert state_backend.states["origin"] == {"devices": set(), "configs": set()}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failed_destination", [None, "fresh-explicit", "fresh-default"])
@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
def test_controlplane_migration_creates_and_compares_both_owned_destinations(
    mocker, fake_cli, failed_destination, failure_kind
):
    hubs = [{"name": "origin", "rg": "owned-rg"}]
    mocker.patch.object(controlplane, "generate_hub_id", side_effect=["fresh-explicit", "fresh-default"])
    mocker.patch.object(subject, "delete_system_endpoints")
    mocker.patch.object(subject.time, "sleep")
    compare = mocker.patch.object(subject, "compare_hubs_controlplane")
    commands = []
    error = BadRequestError("Migration create failed")

    def invoke(args, out_file):
        commands.append(args)
        assert args[:4] == ["iot", "hub", "state", "migrate"]
        assert args[args.index("--origin-hub") + 1] == "origin"
        assert args[args.index("--origin-resource-group") + 1] == "owned-rg"
        assert args[args.index("--aspects") + 1] == "arm"
        destination = args[args.index("--destination-hub") + 1]
        assert destination == ("fresh-explicit" if len(commands) == 1 else "fresh-default")
        assert destination == hubs[-1]["name"], "Track the attempted destination before creation."
        if len(commands) == 1:
            assert args[args.index("--destination-resource-group") + 1] == "owned-rg"
        else:
            assert "--destination-resource-group" not in args
            compare.assert_called_once_with("origin", "fresh-explicit", "owned-rg")
        fake_cli.result.error = error if destination == failed_destination and failure_kind == "cli_error" else None
        if destination == failed_destination:
            if failure_kind == "system_exit":
                raise SystemExit(7)
            return 7
        out_file.write("{}")
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    if failed_destination:
        expected = BadRequestError if failure_kind == "cli_error" else CLIInternalError
        with pytest.raises(expected):
            controlplane.test_migrate_controlplane_with_create(hubs)
    else:
        controlplane.test_migrate_controlplane_with_create(hubs)
    attempted = ["fresh-explicit"] if failed_destination == "fresh-explicit" else ["fresh-explicit", "fresh-default"]
    assert [hub["name"] for hub in hubs] == ["origin"] + attempted
    successful = [destination for destination in attempted if destination != failed_destination]
    assert compare.call_args_list == [mocker.call("origin", destination, "owned-rg") for destination in successful]


def _comparison_read_key(args):
    kind = {
        ("hub", "configuration", "list"): "configs",
        ("edge", "deployment", "list"): "deployments",
        ("hub", "device-identity", "list"): "devices",
        ("hub", "device-identity", "show"): "identity",
        ("hub", "module-identity", "list"): "modules",
        ("hub", "module-twin", "show"): "module_twin",
        ("hub", "device-identity", "children"): "children",
    }[tuple(args[1:4])]
    return args[args.index("--hub-name") + 1], kind


@pytest.fixture
def comparison_data(mocker, fake_cli, tmp_path):
    owned = subject._OwnedDataplaneState(
        config_ids=[subject.generate_generic_id() for _ in range(3)],
        device_ids=subject.generate_device_names(6),
    )
    configs = [
        {
            "id": config_id, "content": {"setting": "value"}, "metrics": {}, "priority": 1,
            "systemMetrics": {"queries": {}}, "targetCondition": "tags.bar=12",
        }
        for config_id in owned.config_ids
    ]
    authentication = {"type": "sas", "symmetricKey": {"primaryKey": "unit-key", "secondaryKey": "unit-key"}}
    identity = {"authentication": authentication}
    devices = [
        {
            "deviceId": device_id, "authenticationType": "sas", "capabilities": {"iotEdge": True},
            "connectionState": "Disconnected", "status": "enabled", "tags": {"tag": "value"},
            "properties": {"desired": {"setting": "value", "$metadata": {}, "$version": 1}},
        }
        for device_id in owned.device_ids
    ]
    module = {"moduleId": "unit-module", "authentication": deepcopy(authentication)}
    module_twin = {
        "modelId": "unit-model", "tags": {"tag": "value"},
        "properties": {"desired": {"setting": "value", "$metadata": {}, "$version": 1}},
    }
    origin = {
        "configs": configs[:1], "deployments": configs[1:], "devices": devices,
        "identity": identity, "modules": [module], "module_twin": module_twin, "children": [],
    }
    views = {"origin": deepcopy(origin), "destination": deepcopy(origin)}
    exported = {
        "configurations": {
            "admConfigurations": {config["id"]: deepcopy(config) for config in configs[:1]},
            "edgeDeployments": {config["id"]: deepcopy(config) for config in configs[1:]},
        },
        "devices": {},
    }
    for device in devices:
        twin = deepcopy(device)
        twin["properties"]["desired"] = {"setting": "value"}
        file_module_twin = deepcopy(module_twin)
        file_module_twin["properties"]["desired"] = {"setting": "value"}
        exported["devices"][device["deviceId"]] = {
            "identity": deepcopy(identity), "twin": twin,
            "modules": {module["moduleId"]: {"identity": deepcopy(module), "twin": file_module_twin}},
        }
    counts = defaultdict(int)
    overrides = {}

    def invoke(args, out_file):
        fake_cli.result.error = None
        name, kind = key = _comparison_read_key(args)
        counts[key] += 1
        response = overrides[key](counts[key]) if key in overrides else views[name][kind]
        out_file.write(json.dumps(response))
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject.time, "sleep")

    def compare(mode):
        auth = subject._hub_auth({"name": "origin", "rg": "rg"})
        if mode == "migration":
            dest_auth = subject._hub_auth({"name": "destination", "rg": "rg"})
            subject.compare_hubs_dataplane(auth, dest_auth, owned)
        else:
            filename = tmp_path / "export.json"
            filename.write_text(json.dumps(exported), encoding="utf-8")
            subject.compare_hub_dataplane_to_file(str(filename), auth, owned)

    return SimpleNamespace(
        owned=owned, views=views, exported=exported, counts=counts, overrides=overrides,
        invoke=invoke, compare=compare,
    )


@pytest.mark.parametrize("mode", ["migration", "file"])
@pytest.mark.parametrize("kind", ["configs", "deployments", "devices", "all"])
@pytest.mark.parametrize("incomplete", [False, True])
def test_comparison_rejects_both_empty_or_equally_incomplete_data(comparison_data, mode, kind, incomplete):
    kinds = ["configs", "deployments", "devices"] if kind == "all" else [kind]
    for view in comparison_data.views.values():
        for item in kinds:
            view[item] = view[item][:-1] if incomplete else []
    origin = comparison_data.views["origin"]
    comparison_data.exported["configurations"] = {
        "admConfigurations": {config["id"]: config for config in origin["configs"]},
        "edgeDeployments": {config["id"]: config for config in origin["deployments"]},
    }
    visible_ids = {device["deviceId"] for device in origin["devices"]}
    comparison_data.exported["devices"] = {
        device_id: device for device_id, device in comparison_data.exported["devices"].items()
        if device_id in visible_ids
    }
    with pytest.raises(AssertionError, match="expected IDs"):
        comparison_data.compare(mode)


@pytest.mark.parametrize("mode", ["migration", "file"])
@pytest.mark.parametrize("kind", ["configs", "deployments", "devices"])
@pytest.mark.parametrize("eventual_success", [False, True])
def test_comparison_retry_exhaustion_raises_and_final_attempt_can_succeed(
    comparison_data, mode, kind, eventual_success
):
    name = "destination" if mode == "migration" else "origin"
    good = comparison_data.views[name][kind]
    bad = deepcopy(good)
    if kind == "devices":
        bad.pop()
    else:
        bad[0]["priority"] = 99
    comparison_data.overrides[(name, kind)] = (
        lambda attempt: good if eventual_success and attempt == subject.MAX_RETRIES else bad
    )
    if eventual_success:
        comparison_data.compare(mode)
    else:
        with pytest.raises(AssertionError):
            comparison_data.compare(mode)
    assert comparison_data.counts[(name, kind)] == subject.MAX_RETRIES
    assert subject.time.sleep.call_count == subject.MAX_RETRIES - 1


@pytest.mark.parametrize("mode", ["migration", "file"])
@pytest.mark.parametrize("change", ["wrong_id", "extra_id", "duplicate_id"])
def test_equal_query_counts_do_not_replace_owned_id_verification(comparison_data, mode, change):
    for view in comparison_data.views.values():
        if change == "wrong_id":
            view["devices"][-1]["deviceId"] = "unowned"
        else:
            extra = deepcopy(view["devices"][-1])
            if change == "extra_id":
                extra["deviceId"] = "unowned"
            view["devices"].append(extra)
    with pytest.raises(AssertionError, match="expected IDs"):
        comparison_data.compare(mode)


@pytest.mark.parametrize("mode", ["migration", "file"])
def test_complete_comparison_retains_detailed_device_and_module_checks(mocker, comparison_data, mode):
    devices = mocker.spy(subject, "compare_devices")
    modules = mocker.spy(subject, "compare_module_twins")
    configs = mocker.spy(subject, "compare_configs")
    comparison_data.compare(mode)
    assert devices.call_count == len(comparison_data.owned.device_ids)
    assert modules.call_count == len(comparison_data.owned.device_ids)
    assert configs.call_count == 2
    subject.time.sleep.assert_not_called()


@pytest.mark.parametrize("mode", ["migration", "file"])
@pytest.mark.parametrize("kind", ["device_tags", "module_auth", "module_twin"])
def test_owned_ids_do_not_bypass_detailed_value_mismatches(comparison_data, mode, kind):
    view = comparison_data.views["destination" if mode == "migration" else "origin"]
    if kind == "device_tags":
        view["devices"][0]["tags"] = {"unexpected": "value"}
    elif kind == "module_auth":
        view["modules"][0]["authentication"]["symmetricKey"]["primaryKey"] = "different-unit-key"
    else:
        view["module_twin"]["properties"]["desired"]["setting"] = "different"
    with pytest.raises(AssertionError):
        comparison_data.compare(mode)


@pytest.mark.parametrize("mode,hub,kind", [
    (mode, hub, kind)
    for mode in ("migration", "file")
    for hub in ("origin", "destination")
    for kind in ("configs", "deployments", "devices", "identity", "modules", "module_twin", "children")
    if mode == "migration" or (hub == "origin" and kind != "children")
])
@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
def test_comparison_cli_read_errors_propagate_without_retry(
    mocker, fake_cli, comparison_data, mode, hub, kind, failure_kind
):
    error = BadRequestError("Original comparison read failure")
    failed_reads = []

    def invoke(args, out_file):
        if _comparison_read_key(args) == (hub, kind):
            failed_reads.append(kind)
            fake_cli.result.error = error if failure_kind == "cli_error" else None
            out_file.write("[]")
            if failure_kind == "system_exit":
                raise SystemExit(7)
            return 7
        return comparison_data.invoke(args, out_file)

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    expected = BadRequestError if failure_kind == "cli_error" else CLIInternalError
    with pytest.raises(expected) as raised:
        comparison_data.compare(mode)
    if failure_kind == "cli_error":
        assert raised.value is error
    else:
        assert str(raised.value) == "IoT Hub state command failed with exit code 7."
    assert failed_reads == [kind]
    subject.time.sleep.assert_not_called()
