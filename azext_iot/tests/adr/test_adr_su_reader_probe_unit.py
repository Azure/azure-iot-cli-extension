# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.core.rest import HttpRequest

from azext_iot.tests.adr import _su_reader_probe as subject
from azext_iot.tests.adr._su_reader_probe import SUReaderProbe

SU_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceUpdate/updateInstances/su"
HOST = "owned.api.adu.microsoft.com"
COMMAND = "iot adr ns su software-update list --ns ns -g rg"


def _error(status=403, host=HOST, method="GET"):
    error = HttpResponseError("synthetic discovery failure")
    error.status_code = status
    error.response = SimpleNamespace(
        status_code=status, request=HttpRequest(method, f"https://{host}/updates"),
        headers={"x-ms-request-id": "request-id", "x-ms-correlation-request-id": "correlation-id"},
    )
    return error


@pytest.fixture
def probe(caplog, monkeypatch):
    monkeypatch.setattr(subject, "wait_for_condition", Mock())
    scenario = Mock()
    scenario._owned_resources = {("su", "su", "rg"): None}
    scenario.cmd.return_value.get_output_in_json.return_value = [
        {"id": "inherited-assignment", "roleDefinitionName": "Owner", "scope": "/subscriptions/sub"},
    ]
    scenario.assign_role.return_value = "owned-reader-assignment"
    result = SUReaderProbe(scenario, "caller", SU_ID, HOST)
    command = scenario.cmd.call_args.args[0]
    assert "--assignee-object-id caller" in command
    assert "--include-inherited --include-groups --fill-principal-name false" in command
    assert "--assignee " not in command
    assert "inherited-assignment" in caplog.text
    assert "cannot prove Reader universally unnecessary" in caplog.text
    scenario.cmd.reset_mock()
    return result, scenario


def test_reader_probe_success_does_not_grant_or_remove_any_roles(probe, caplog):
    reader, scenario = probe
    output = Mock()
    scenario.cmd.return_value = output
    assert reader.cmd(COMMAND) is output
    scenario.cmd.assert_called_once_with(COMMAND)
    scenario.assign_role.assert_not_called()
    assert "without fixture Reader: command succeeded" in caplog.text


def test_reader_probe_get_403_grants_only_owned_target_and_repeats_identical_command_once(probe, caplog):
    reader, scenario = probe
    output = Mock()
    scenario.cmd.side_effect = [_error(), output]
    assert reader.cmd(COMMAND) is output
    assert scenario.cmd.call_args_list == [call(COMMAND), call(COMMAND)]
    scenario.assign_role.assert_called_once_with("caller", "Device Update Reader", SU_ID, assignee_type=None)
    assert "without fixture Reader: HTTP 403" in caplog.text
    assert "requestId=request-id correlationId=correlation-id" in caplog.text
    assert "fixture assignment=owned-reader-assignment" in caplog.text
    assert "after fixture Reader: command succeeded" in caplog.text


@pytest.mark.parametrize("error", [
    _error(401), _error(404), _error(500), _error(host="management.azure.com"), _error(method="POST"),
    ServiceRequestError("transport failed"),
])
def test_reader_probe_non_target_or_non_403_errors_propagate_without_grant_or_replay(probe, error):
    reader, scenario = probe
    scenario.cmd.side_effect = error
    with pytest.raises(type(error)) as raised:
        reader.cmd(COMMAND)
    assert raised.value is error
    scenario.cmd.assert_called_once_with(COMMAND)
    scenario.assign_role.assert_not_called()


def test_reader_probe_second_403_is_not_retried_or_hidden(probe, caplog):
    reader, scenario = probe
    second_error = _error()
    scenario.cmd.side_effect = [_error(), second_error]
    with pytest.raises(HttpResponseError) as raised:
        reader.cmd(COMMAND)
    assert raised.value is second_error
    assert scenario.cmd.call_count == 2
    scenario.assign_role.assert_called_once()
    assert "after fixture Reader: HTTP 403" in caplog.text
    scenario.cmd.side_effect = second_error
    with pytest.raises(HttpResponseError):
        reader.cmd(COMMAND)
    assert scenario.cmd.call_count == 3
    scenario.assign_role.assert_called_once()


def test_reader_probe_grant_failure_does_not_repeat_discovery(probe):
    reader, scenario = probe
    scenario.cmd.side_effect = _error()
    scenario.assign_role.return_value = None
    with pytest.raises(AssertionError, match="scoped fixture role"):
        reader.cmd(COMMAND)
    scenario.cmd.assert_called_once()


def test_reader_probe_rejects_borrowed_target_before_any_command():
    scenario = Mock()
    scenario._owned_resources = {}
    with pytest.raises(AssertionError, match="freshly owned"):
        SUReaderProbe(scenario, "caller", SU_ID, HOST)
    scenario.cmd.assert_not_called()
    scenario.assign_role.assert_not_called()


@pytest.mark.parametrize("visible", [True, False])
def test_reader_replay_waits_for_scoped_visibility_and_bounded_propagation(probe, monkeypatch, visible):
    from azext_iot.tests.adr._helpers import wait_for_condition

    reader, scenario = probe
    now = [0]
    discovery_times = []

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(subject, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        subject, "wait_for_condition",
        lambda *args, **kwargs: wait_for_condition(*args, **kwargs, clock=lambda: now[0], sleeper=sleep),
    )

    def invoke(command):
        if command == COMMAND:
            discovery_times.append(now[0])
            if len(discovery_times) == 1:
                raise _error()
            return "discovery succeeded"
        assert command == (
            f"role assignment list --assignee-object-id caller --role 'Device Update Reader' "
            f"--scope '{SU_ID}' --fill-principal-name false"
        )
        return Mock(get_output_in_json=lambda: [{"id": "owned-reader-assignment"}] if visible else [])

    scenario.cmd.side_effect = invoke
    if visible:
        assert reader.cmd(COMMAND) == "discovery succeeded"
        assert discovery_times == [0, 180]
    else:
        with pytest.raises(AssertionError, match="Timed out"):
            reader.cmd(COMMAND)
        assert discovery_times == [0]
        assert now[0] == 300
    scenario.assign_role.assert_called_once_with("caller", "Device Update Reader", SU_ID, assignee_type=None)
