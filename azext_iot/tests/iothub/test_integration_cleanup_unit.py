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
    request = SimpleNamespace(session=SimpleNamespace(
        items=[SimpleNamespace(nodeid="test_owned_int.py::test_case")],
    ))
    cleanup = fixtures._cleanup_dynamic_hub.__wrapped__(request)
    next(cleanup)
    with pytest.raises(CLIInternalError if fails else StopIteration):
        next(cleanup)
    assert client.invoke.call_count == attempts
    assert sleep.call_count == attempts - 1
    assert all(call.args == (30,) for call in sleep.call_args_list)
