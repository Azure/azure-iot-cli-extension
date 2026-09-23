# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import CLIInternalError
from knack.util import CLIError

from azext_iot.common.embedded_cli import EmbeddedCLI


@pytest.fixture
def embedded(monkeypatch):
    client = Mock(result=None)
    monkeypatch.setattr("azext_iot.common.embedded_cli.get_default_cli", lambda: client)
    return EmbeddedCLI(), client


@pytest.mark.parametrize("output", ["", '{"looks": "successful"}'])
def test_json_preserves_original_command_failure(embedded, output):
    cli, client = embedded
    error = CLIError("Please run 'az login' to setup account.")

    def invoke(_args, out_file):
        out_file.write(output)
        client.result = SimpleNamespace(error=error)
        return 1

    client.invoke.side_effect = invoke
    assert cli.invoke("group show") is cli
    with pytest.raises(CLIError) as raised:
        cli.as_json()
    assert raised.value is error


def test_capture_preserves_failure_exit_code_and_restores_handler(embedded):
    cli, client = embedded
    handler = client.exception_handler
    error = CLIError("expected failure")

    def invoke(_args, out_file):
        exit_code = client.exception_handler(error)
        client.result = SimpleNamespace(error=error)
        return exit_code

    client.invoke.side_effect = invoke
    with pytest.raises(CLIError) as raised:
        cli.invoke("group show", capture_stderr=True)
    assert raised.value is error
    assert cli.error_code == 1
    assert client.exception_handler is handler
    handler.assert_not_called()


def test_capture_preserves_nonzero_status_for_contextual_callers(embedded):
    cli, client = embedded
    client.invoke.return_value = 2
    assert not cli.invoke("group show", capture_stderr=True).success()
    with pytest.raises(CLIInternalError, match="exit code 2"):
        cli.raise_for_error()


@pytest.mark.parametrize("capture", [False, True])
def test_unexpected_exception_restores_handler_and_closes_capture(embedded, capture):
    cli, client = embedded
    handler = client.exception_handler
    error = RuntimeError("unexpected failure")
    streams = []

    def invoke(_args, out_file):
        streams.append(out_file)
        out_file.write("partial")
        raise error

    client.invoke.side_effect = invoke
    with pytest.raises(RuntimeError) as raised:
        cli.invoke("group show", capture_stderr=capture)
    assert raised.value is error
    assert client.exception_handler is handler
    assert streams[0].closed
    assert cli.output == "partial"
    assert not cli.success()


@pytest.mark.parametrize("code", [None, 0, 3])
def test_system_exit_preserves_result_and_restores_handler(embedded, code):
    cli, client = embedded
    handler = client.exception_handler
    error = SystemExit(code)

    def invoke(_args, out_file):
        client.result = SimpleNamespace(error=error)
        raise error

    client.invoke.side_effect = invoke
    cli.invoke("group show")
    assert cli.success() is (not code)
    assert client.exception_handler is handler
    if code:
        with pytest.raises(SystemExit) as raised:
            cli.raise_for_error()
        assert raised.value is error


def test_previous_error_is_not_reused_for_later_invocation(embedded):
    cli, client = embedded
    client.result = SimpleNamespace(error=CLIError("previous"))

    def invoke(_args, out_file):
        client.result = SimpleNamespace(error=None)
        return 2

    client.invoke.side_effect = invoke
    cli.invoke("group show")
    assert cli.get_error() is None
    with pytest.raises(CLIInternalError, match="exit code 2"):
        cli.as_json()


@pytest.mark.parametrize("output", ["", "sensitive-non-json-output"])
def test_invalid_success_json_does_not_echo_payload(embedded, output):
    cli, client = embedded

    def invoke(_args, out_file):
        out_file.write(output)
        return 0

    client.invoke.side_effect = invoke
    cli.invoke("group show")
    assert cli.raise_for_error() is cli
    with pytest.raises(CLIInternalError, match="Issue parsing received payload") as raised:
        cli.as_json()
    assert "sensitive-non-json-output" not in str(raised.value)


def test_no_output_success_does_not_require_json(embedded):
    cli, client = embedded
    client.invoke.return_value = None
    assert cli.invoke("group delete", capture_stderr=True).success()


def test_endpoint_scenario_stops_at_first_failed_command(embedded):
    _, client = embedded
    path = Path(__file__).parents[1] / "iothub/message_endpoint/test_iothub_message_endpoint_int.py"
    scenario = runpy.run_path(str(path))
    error = CLIError("Original endpoint command failure")

    def invoke(_args, out_file):
        client.result = SimpleNamespace(error=error)
        return 1

    client.invoke.side_effect = invoke
    hub = {
        "hub": {
            "name": "hub",
            "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub",
            "identity": {"userAssignedIdentities": {"identity-id": {}}},
        },
        "rg": "rg",
    }
    endpoint = {
        "eventhub": {"name": "events"},
        "namespace": {"serviceBusEndpoint": "https://endpoint.servicebus.windows.net/"},
        "connectionString": "unused-placeholder",
    }
    with pytest.raises(CLIError) as raised:
        scenario["test_iot_eventhub_endpoint_lifecycle"](([hub], endpoint))
    assert raised.value is error
    client.invoke.assert_called_once()


def test_real_cli_replaces_results_without_wrapper_mutation():
    cli = EmbeddedCLI()
    assert cli.invoke("version").success()
    successful_result = cli.az_cli.result

    assert not cli.invoke("version --invalid-embedded-regression-option").success()
    assert cli.az_cli.result is not successful_result
    error = cli.get_error()
    assert isinstance(error, BaseException)
    with pytest.raises(type(error)) as raised:
        cli.as_json()
    assert raised.value is error

    failed_result = cli.az_cli.result
    assert cli.invoke("version", capture_stderr=True).success()
    assert cli.az_cli.result is not failed_result
    assert cli.get_error() is None
