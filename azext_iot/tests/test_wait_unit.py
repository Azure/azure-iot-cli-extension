# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from io import StringIO
import shlex

import pytest
from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands import CliCommandType
from azure.cli.core.commands.command_operation import ShowCommandOperation, WaitCommandOperation
from azure.cli.core.mock import DummyCli
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from knack.util import CLIError

from azext_iot import IoTExtCommandsLoader


WAIT_COMMANDS = {
    "dt wait": ("azext_iot.digitaltwins.commands_resource.wait_instance", ""),
    "dt endpoint wait": ("azext_iot.digitaltwins.commands_resource.wait_endpoint", "--en endpoint"),
    "dt data-history connection wait": ("azext_iot.digitaltwins.commands_resource.wait_data_connection", "--cn connection"),
    "dt network private-endpoint connection wait": (
        "azext_iot.digitaltwins.commands_resource.wait_private_endpoint_conn", "--cn connection",
    ),
    "iot du account wait": ("azext_iot.deviceupdate.commands_account.wait_on_account", ""),
    "iot du instance wait": ("azext_iot.deviceupdate.commands_instance.wait_on_instance", "--instance instance"),
}
TIMEOUT_MESSAGE = "Wait operation timed-out after 1 seconds"
UNSUPPORTED_CONDITIONS = {
    "dt wait": {"--updated"},
    "dt endpoint wait": {"--updated"},
    "dt network private-endpoint connection wait": {"--created", "--exists"},
}


def wait_cases(conditions):
    return [
        (command, condition) for command in WAIT_COMMANDS for condition in conditions
        if condition not in UNSUPPORTED_CONDITIONS.get(command, set())
    ]


@pytest.fixture(params=WAIT_COMMANDS)
def wait_command(request, mocker):
    getter_path, arguments = WAIT_COMMANDS[request.param]
    getter = mocker.patch(getter_path, autospec=True)
    mocker.patch("time.sleep")
    return f"{request.param} -n resource -g rg {arguments}", getter


def invoke_wait(cli, command, condition, output_format="json"):
    output = StringIO()
    code = cli.invoke(
        shlex.split(f"{command} {condition} --timeout 1 --interval 1 -o {output_format}"),
        out_file=output,
    )
    return code, output.getvalue()


def test_all_generic_wait_commands_are_covered():
    loader = IoTExtCommandsLoader(DummyCli())
    table = loader.load_command_table(None)
    generic_waits = {
        name for name, command in table.items()
        if isinstance(command.command_kwargs.get("command_operation"), WaitCommandOperation)
    }
    assert generic_waits == set(WAIT_COMMANDS)


@pytest.mark.parametrize("wait_command,condition", wait_cases([
    "--created", "--updated", "--deleted", "--custom 'name == `\"other\"`'",
]), indirect=["wait_command"])
@pytest.mark.parametrize("output_format", ["json", "none"])
def test_timeout_fails_in_native_cli(offline_cli, wait_command, condition, output_format, caplog):
    command, getter = wait_command
    getter.return_value = {"name": "resource", "properties": {"provisioningState": "Creating"}}

    code, output = invoke_wait(offline_cli, command, condition, output_format)

    assert code != 0
    assert output == ""
    assert isinstance(offline_cli.result.error, CLIError)
    assert str(offline_cli.result.error) == TIMEOUT_MESSAGE
    assert TIMEOUT_MESSAGE in caplog.text
    getter.assert_called_once()


@pytest.mark.parametrize("wait_command,condition", wait_cases(["--created", "--exists"]), indirect=["wait_command"])
def test_missing_resource_times_out(offline_cli, wait_command, condition):
    command, getter = wait_command
    getter.side_effect = ResourceNotFoundError("not materialized", response=None)
    getter.side_effect.status_code = 404

    code, output = invoke_wait(offline_cli, command, condition)

    assert code != 0
    assert output == ""
    assert str(offline_cli.result.error) == TIMEOUT_MESSAGE


@pytest.mark.parametrize("wait_command,condition", wait_cases([
    "--created", "--updated", "--exists", "--custom 'name == `\"resource\"`'",
]), indirect=["wait_command"])
def test_success_remains_silent(offline_cli, wait_command, condition):
    command, getter = wait_command
    getter.return_value = {"name": "resource", "properties": {"provisioningState": "Succeeded"}}

    code, output = invoke_wait(offline_cli, command, condition)

    assert code == 0
    assert output == ""
    assert offline_cli.result.error is None
    getter.assert_called_once()


def test_deleted_succeeds_on_404(offline_cli, wait_command):
    command, getter = wait_command
    getter.side_effect = ResourceNotFoundError("gone")
    getter.side_effect.status_code = 404

    code, output = invoke_wait(offline_cli, command, "--deleted")

    assert code == 0
    assert output == ""
    assert offline_cli.result.error is None


def test_service_error_is_not_replaced_by_timeout(offline_cli, wait_command):
    command, getter = wait_command
    error = HttpResponseError("access denied")
    error.status_code = 403
    getter.side_effect = error

    code, output = invoke_wait(offline_cli, command, "--custom 'name == `\"resource\"`'")

    assert code != 0
    assert output == ""
    assert offline_cli.result.error is error
    getter.assert_called_once()


def test_failed_resource_still_fails(offline_cli, wait_command):
    command, getter = wait_command
    getter.return_value = {"properties": {"provisioningState": "Failed"}}

    code, output = invoke_wait(offline_cli, command, "--custom 'name == `\"resource\"`'")

    assert code != 0
    assert output == ""
    assert "operation failed" in str(offline_cli.result.error)


@pytest.mark.parametrize("result", [None, {"name": "unchanged"}])
def test_registered_wait_preserves_success_values(mocker, result):
    loader = IoTExtCommandsLoader(DummyCli())
    operation = WaitCommandOperation(loader, "unused#get")
    handler = mocker.patch.object(operation, "handler", return_value=result)
    loader.add_cli_command("test wait", operation)
    arguments = {"unchanged": "value"}

    assert loader.command_table["test wait"].handler(arguments) is result
    handler.assert_called_once_with(arguments)


@pytest.mark.parametrize("raises", [False, True])
def test_registered_wait_preserves_original_exception(mocker, raises):
    loader = IoTExtCommandsLoader(DummyCli())
    operation = WaitCommandOperation(loader, "unused#get")
    error = CLIError(TIMEOUT_MESSAGE)
    mocker.patch.object(operation, "handler", **({"side_effect": error} if raises else {"return_value": error}))
    loader.add_cli_command("test wait", operation)

    with pytest.raises(CLIError) as caught:
        loader.command_table["test wait"].handler({})
    assert caught.value is error


def test_registered_wait_preserves_handler_metadata():
    loader = IoTExtCommandsLoader(DummyCli())
    operation = WaitCommandOperation(loader, "unused#get")
    original_handler = operation.handler
    loader.add_cli_command("test wait", operation)
    handler = loader.command_table["test wait"].handler

    assert handler.__wrapped__ == original_handler
    assert handler.__name__ == original_handler.__name__
    assert handler.__doc__ == original_handler.__doc__


def test_other_loaders_and_non_wait_commands_are_unchanged(mocker):
    error = CLIError("unchanged")
    loader = AzCommandsLoader(DummyCli())
    operation = WaitCommandOperation(loader, "unused#get")
    handler = mocker.patch.object(operation, "handler", return_value=error)
    loader.add_cli_command("test wait", operation)
    assert loader.command_table["test wait"].handler is handler
    assert loader.command_table["test wait"].handler({}) is error

    extension_loader = IoTExtCommandsLoader(DummyCli())
    show_handler = mocker.patch.object(ShowCommandOperation, "handler", return_value=error)
    with extension_loader.command_group("test", command_type=CliCommandType(operations_tmpl="unused#{}")) as group:
        group.show_command("show", "get")
    command = extension_loader.command_table["test show"]
    assert command.handler is show_handler
    assert command.handler({}) is error
