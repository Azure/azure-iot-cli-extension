# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import CLIInternalError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError as CoreResourceNotFoundError
from requests import Response

from azext_iot.tests.iothub import conftest as fixtures
from azext_iot.tests import helpers


def _cli_outcomes(mocker, outcomes):
    client = SimpleNamespace(exception_handler=mocker.Mock(), result=SimpleNamespace(error=None))
    outcomes = iter(outcomes)

    def invoke(_args, out_file):
        code, error = next(outcomes)
        client.result.error = error
        out_file.write("{}")
        if isinstance(code, BaseException):
            raise code
        return code

    client.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(fixtures.cli, "az_cli", client)
    return client


def _http_error(status):
    error = HttpResponseError("Original cleanup failure; an internal lookup was not found")
    error.status_code = status
    return error


def _legacy_error(status):
    response = Response()
    response.status_code = status
    response._content = b"{}"
    return fixtures.CloudError(response=response)


@pytest.mark.parametrize("removal", [
    "_cosmos_db_removal", "_storage_removal", "_event_hub_removal",
    "_service_bus_removal", "_user_identity_removal", "device", "configuration",
])
@pytest.mark.parametrize("outcome", [
    "success", "nonzero", "empty_not_found_exit", "system_exit",
    "http_error", "http_404", "cli_404", "core_404", "legacy_404", "legacy_error", "unexpected_error",
])
def test_fixture_deletion_never_hides_failures(mocker, removal, outcome):
    error = {
        "http_error": _http_error(502),
        "http_404": _http_error(404),
        "cli_404": ResourceNotFoundError("absent"),
        "core_404": CoreResourceNotFoundError("absent"),
        "legacy_404": _legacy_error(404),
        "legacy_error": _legacy_error(403),
    }.get(outcome)
    code = {
        "success": 0,
        "empty_not_found_exit": 3,
        "system_exit": SystemExit(7),
        "unexpected_error": RuntimeError("programming failure"),
    }.get(outcome, 7)
    client = _cli_outcomes(mocker, [(code, error)])

    def delete(name):
        if removal == "device":
            return fixtures._clean_up(device_ids=[name])
        if removal == "configuration":
            return fixtures._clean_up(config_ids=[name])
        return getattr(fixtures, removal)(name)

    if outcome in ("success", "http_404", "cli_404", "core_404", "legacy_404"):
        delete("owned-resource")
    else:
        expected = (
            type(error) if error is not None
            else RuntimeError if outcome == "unexpected_error"
            else CLIInternalError
        )
        with pytest.raises(expected) as raised:
            delete("owned-resource")
        if error is not None:
            assert raised.value is error
        elif outcome != "unexpected_error":
            assert "owned-resource" in str(raised.value)
            assert "exit code" in str(raised.value)

    client.invoke.assert_called_once()
    assert "owned-resource" in client.invoke.call_args.args[0]


def test_cosmos_role_setup_rejects_nonzero_exit_without_exception(mocker):
    _cli_outcomes(mocker, [(7, None)])
    with pytest.raises(CLIInternalError, match="exit code 7"):
        fixtures.assign_cosmos_db_role("principal", "role", "account", "rg")


def test_storage_container_setup_stops_on_failed_create(mocker):
    client = _cli_outcomes(mocker, [(0, None), (7, None)])
    mocker.patch.object(fixtures, "_storage_get_cstring", return_value="fixture-connection-string")
    with pytest.raises(CLIInternalError, match="exit code 7"):
        fixtures._storage_provisioner()
    assert client.invoke.call_count == 2


def test_hub_cleanup_attempts_all_owned_hubs_and_reports_every_failure(mocker, caplog):
    caplog.set_level(logging.ERROR)
    error = _http_error(403)
    client = _cli_outcomes(mocker, [(7, None), (1, error), (0, None)])
    with pytest.raises(CLIInternalError) as raised:
        fixtures._iot_hubs_removal([{"name": name} for name in ("first", "second", "third")])
    assert "first, second" in str(raised.value)
    assert "third" not in str(raised.value)
    assert "first" in str(raised.value.__cause__)
    assert "second" in caplog.text
    assert client.invoke.call_count == 3


def test_hub_cleanup_accepts_only_confirmed_absence(mocker):
    client = _cli_outcomes(mocker, [(3, ResourceNotFoundError("absent")), (0, None)])
    fixtures._iot_hubs_removal([{"name": "already-absent"}, {"name": "existing"}])
    assert client.invoke.call_count == 2


@pytest.mark.parametrize("outcomes,attempts,fails", [
    ([(7, None)] * 3, 3, True),
    ([(7, None), (0, None)], 2, False),
    ([(3, ResourceNotFoundError("absent"))], 1, False),
])
def test_dynamic_hub_cleanup_has_bounded_retries_and_truthful_result(
    mocker, monkeypatch, outcomes, attempts, fails,
):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    mocker.patch.object(
        fixtures, "iothub_settings",
        SimpleNamespace(env=SimpleNamespace(azext_iot_testhub=None)),
    )
    client = _cli_outcomes(mocker, outcomes)
    sleep = mocker.patch.object(fixtures, "sleep")
    request = SimpleNamespace(
        config=SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda _: None)),
        session=SimpleNamespace(items=[SimpleNamespace(nodeid="test_owned_int.py::test_case")]),
    )
    cleanup = fixtures._cleanup_dynamic_hub.__wrapped__(request)
    next(cleanup)
    with pytest.raises(CLIInternalError if fails else StopIteration):
        next(cleanup)
    assert client.invoke.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert all(call.args == (30,) for call in sleep.call_args_list)


@pytest.fixture
def registry_cleanup(mocker):
    context = object()
    client = mocker.Mock(az_cli=context)
    client.invoke.return_value.success.return_value = True
    client.invoke.return_value.as_json.return_value = []
    mocker.patch.object(helpers, "cli", client)
    provider = mocker.patch("azext_iot.iothub.providers.device_identity.DeviceIdentityProvider")
    devices = provider.return_value.service_sdk.devices
    devices.get_devices.return_value = []
    clock = [0]
    mocker.patch.object(helpers, "monotonic", side_effect=lambda: clock[0])
    sleep = mocker.patch.object(helpers, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return SimpleNamespace(client=client, provider=provider, devices=devices, clock=clock, sleep=sleep)


@pytest.mark.parametrize("shape", ["model", "dict", "mixed"])
def test_registry_cleanup_preserves_login_context_and_identity_shapes(registry_cleanup, shape):
    fixture = registry_cleanup
    rows = [
        {"deviceId": "first"} if shape != "model" else SimpleNamespace(device_id="first"),
        SimpleNamespace(device_id="second") if shape != "dict" else {"deviceId": "second"},
    ]
    fixture.devices.get_devices.side_effect = [rows, []]
    helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    options = fixture.provider.call_args.kwargs
    assert options["cmd"].cli_ctx is fixture.client.az_cli
    assert {key: value for key, value in options.items() if key != "cmd"} == {
        "hub_name": "owned-hub", "rg": "owned-rg", "auth_type_dataplane": "login",
    }
    assert [call.kwargs for call in fixture.devices.delete_identity.call_args_list] == [
        {"id": "first", "if_match": "*"}, {"id": "second", "if_match": "*"},
    ]
    assert fixture.devices.get_devices.call_count == 2
    assert all(call.kwargs == {"top": 1000} for call in fixture.devices.get_devices.call_args_list)
    commands = [call.args[0] for call in fixture.client.invoke.call_args_list]
    assert len(commands) == 4
    assert all(command.endswith("--auth-type login") for command in commands)
    assert not any("connection-string" in command or "device-twin" in command for command in commands)


def test_registry_cleanup_drains_an_extra_batch_before_claiming_success(registry_cleanup):
    fixture = registry_cleanup
    fixture.devices.get_devices.side_effect = [
        [{"deviceId": f"device-{index}"} for index in range(1000)],
        [{"deviceId": "last-device"}],
        [],
    ]
    helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    assert fixture.devices.delete_identity.call_count == 1001
    fixture.devices.delete_identity.assert_called_with(id="last-device", if_match="*")
    assert fixture.devices.get_devices.call_count == 3


@pytest.mark.parametrize("after_delete", [False, True])
def test_registry_cleanup_read_errors_cannot_claim_success(registry_cleanup, after_delete):
    fixture = registry_cleanup
    error = _http_error(403)
    fixture.devices.get_devices.side_effect = ([[{"deviceId": "owned"}]] if after_delete else []) + [error]
    with pytest.raises(HttpResponseError) as raised:
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    assert raised.value is error
    assert fixture.devices.delete_identity.call_count == int(after_delete)
    fixture.sleep.assert_not_called()


@pytest.mark.parametrize("error,absent", [
    (ResourceNotFoundError("absent"), True),
    (CoreResourceNotFoundError("absent"), True),
    (_legacy_error(404), True),
    (_http_error(404), True),
    (_legacy_error(403), False),
    (_http_error(502), False),
    (RuntimeError("not found is only text"), False),
])
def test_registry_cleanup_only_ignores_confirmed_delete_absence(registry_cleanup, error, absent):
    fixture = registry_cleanup
    fixture.devices.get_devices.side_effect = [[{"deviceId": "owned"}], []]
    fixture.devices.delete_identity.side_effect = error
    if absent:
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
        assert fixture.devices.get_devices.call_count == 2
    else:
        with pytest.raises(type(error)) as raised:
            helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
        assert raised.value is error
    fixture.devices.delete_identity.assert_called_once_with(id="owned", if_match="*")


def test_registry_cleanup_visibility_wait_never_replays_deletes(registry_cleanup):
    fixture = registry_cleanup
    fixture.devices.get_devices.return_value = [{"deviceId": "still-visible"}]
    with pytest.raises(CLIInternalError, match="deadline exhausted"):
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    fixture.devices.delete_identity.assert_called_once_with(id="still-visible", if_match="*")
    assert fixture.clock[0] == 60
    assert all(call.args[0] == 2 for call in fixture.sleep.call_args_list)


def test_registry_cleanup_charges_read_time_and_rejects_late_empty_result(registry_cleanup):
    fixture = registry_cleanup

    def late_read(**_kwargs):
        fixture.clock[0] = 61
        return []

    fixture.devices.get_devices.side_effect = late_read
    with pytest.raises(CLIInternalError, match="deadline exhausted"):
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    fixture.devices.delete_identity.assert_not_called()


@pytest.mark.parametrize("rows", [None, {}, [{}], [SimpleNamespace()], [{"deviceId": ""}], [{"deviceId": 12}]])
def test_registry_cleanup_invalid_listing_fails_before_deleting(registry_cleanup, rows):
    fixture = registry_cleanup
    fixture.devices.get_devices.return_value = rows
    with pytest.raises(CLIInternalError):
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    fixture.devices.delete_identity.assert_not_called()


def test_cleanup_configuration_listing_exhaustion_cannot_mean_empty(registry_cleanup):
    fixture = registry_cleanup
    fixture.client.invoke.return_value.success.return_value = False
    fixture.client.invoke.return_value.error_code = 7
    with pytest.raises(RuntimeError, match="exit code 7"):
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    assert fixture.client.invoke.call_count == 3
    assert fixture.clock[0] == 60
    fixture.devices.delete_identity.assert_not_called()


@pytest.mark.parametrize("rows", [None, {}, False, "", 0])
@pytest.mark.parametrize("observation", [False, True])
def test_cleanup_malformed_configuration_listing_cannot_mean_empty(registry_cleanup, rows, observation):
    fixture = registry_cleanup
    fixture.client.invoke.return_value.as_json.side_effect = ([[], []] if observation else []) + [rows, [], []]
    with pytest.raises(CLIInternalError, match="invalid configuration listing"):
        helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    assert fixture.client.invoke.call_count == (3 if observation else 1)
    fixture.devices.delete_identity.assert_not_called()
    fixture.sleep.assert_not_called()


def test_cleanup_observes_configuration_deletion_without_replaying_it(registry_cleanup):
    fixture = registry_cleanup
    fixture.client.invoke.return_value.as_json.side_effect = [
        [{"id": "owned-deployment"}], [], [{"id": "owned-deployment"}], [], [],
    ]
    helpers.clean_up_iothub_device_config("owned-hub", "owned-rg")
    commands = [call.args[0] for call in fixture.client.invoke.call_args_list]
    assert sum("deployment delete" in command for command in commands) == 1
    assert sum("deployment list" in command for command in commands) == 3
    assert fixture.clock[0] == 2
