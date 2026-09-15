# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.cli.core.mock import DummyCli
from knack.help_files import helps

from azext_iot.adr._help import load_adr_help
from azext_iot.adr.command_map import load_adr_commands
from azext_iot.adr.params_adr_management import load_adr_management_arguments

SUPPORTED = {
    "iot adr ns create", "iot adr ns show", "iot adr ns list", "iot adr ns update",
    "iot adr ns delete", "iot adr ns wait", "iot adr ns migrate",
    "iot adr ns identity show", "iot adr ns identity assign", "iot adr ns identity remove",
    "iot adr ns identity wait",
}
UNSUPPORTED = {
    "credential", "policy", "ca", "device", "registry-device", "group", "job", "run", "report", "link",
    "su", "asset", "discovered-asset", "discovered-device",
}


def test_exact_adr_registration_and_handlers():
    loader = MagicMock()
    groups = {}

    def group(name, **kwargs):
        assert kwargs["is_preview"] is True
        context = MagicMock()
        groups[name] = context.__enter__.return_value
        return context

    loader.command_group.side_effect = group
    load_adr_commands(loader, None)
    assert set(groups) == {"iot adr ns", "iot adr ns identity"}
    registered = {}
    for name, context in groups.items():
        for method in ("command", "show_command", "wait_command"):
            for call in getattr(context, method).call_args_list:
                command, handler = call.args
                registered[f"{name} {command}"] = handler
                assert hasattr(importlib.import_module("azext_iot.adr.commands_namespace"), handler)
                if command in {"create", "update", "delete", "migrate", "assign", "remove"}:
                    assert call.kwargs["supports_no_wait"] is True
                if command == "delete":
                    assert call.kwargs["confirmation"] is True
    assert set(registered) == SUPPORTED
    assert registered["iot adr ns identity wait"] == "adr_namespace_show"


def test_only_supported_arguments_are_registered():
    loader = MagicMock()
    contexts = {}

    def context(name):
        result = MagicMock()
        contexts.setdefault(name, []).append(result.__enter__.return_value)
        return result

    loader.argument_context.side_effect = context
    load_adr_management_arguments(loader, None)
    assert set(contexts) == {"iot adr ns", "iot adr ns create", "iot adr ns update", "iot adr ns migrate"}
    arguments = {}
    options = set()
    for name, records in contexts.items():
        for record in records:
            for call in record.argument.call_args_list:
                arguments.setdefault(name, set()).add(call.args[0])
                options.update(call.kwargs.get("options_list", []))
    assert arguments == {
        "iot adr ns": {"resource_group_name", "namespace_name"},
        "iot adr ns create": {"location", "tags", "system_assigned", "messaging_endpoints"},
        "iot adr ns update": {"tags", "system_assigned", "messaging_endpoints"},
        "iot adr ns migrate": {"resource_ids"},
    }
    assert options == {"--namespace", "--name", "-n", "--system-assigned", "--messaging-endpoints", "--resource-ids"}


def test_help_matches_supported_commands():
    load_adr_help()
    adr_help = {name for name in helps if name.startswith("iot adr")}
    assert adr_help == SUPPORTED | {"iot adr", "iot adr ns", "iot adr ns identity"}
    for name in adr_help:
        assert not set(name.split()[3:]) & UNSUPPORTED
        assert all(
            unsupported not in helps[name]
            for unsupported in ("user-assigned", "--outbound-", "--provisioning-", "--updating-", "--observability-")
        )


def test_root_loader_preserves_du_without_adr_su(mocker):
    from azext_iot import IoTExtCommandsLoader

    loader = IoTExtCommandsLoader(DummyCli())
    table = loader.load_command_table([])
    assert {name for name in table if name.startswith("iot adr ")} == SUPPORTED
    assert "iot du account create" in table
    assert not any(name.startswith("iot adr ns su ") for name in table)
    argument_loaders = [
        "azext_iot._params.load_arguments", "azext_iot.iothub.params.load_iothub_arguments",
        "azext_iot.central.params.load_central_arguments", "azext_iot.digitaltwins.params.load_digitaltwins_arguments",
        "azext_iot.dps.params.load_dps_arguments", "azext_iot.deviceupdate.params.load_deviceupdate_arguments",
        "azext_iot.core.params.load_core_arguments", "azext_iot.adr.params_adr_management.load_adr_management_arguments",
    ]
    patched = [mocker.patch(path) for path in argument_loaders]
    loader.load_arguments("iot adr ns create")
    for argument_loader in patched:
        argument_loader.assert_called_once_with(loader, "iot adr ns create")


@pytest.fixture
def resolved_commands():
    from azext_iot import IoTExtCommandsLoader

    cli = DummyCli()
    cli.invocation = SimpleNamespace(data={})
    loader = IoTExtCommandsLoader(cli)
    loader.load_command_table([])
    commands = {}
    for name in sorted(SUPPORTED):
        cli.invocation.data["command_string"] = name
        command = loader.command_table[name]
        command.load_arguments()
        loader.load_arguments(name)
        loader._apply_parameter_info(name, command)
        commands[name] = command
    return commands


def test_resolved_arguments_exclude_removed_features(resolved_commands):
    common = {"namespace_name", "resource_group_name"}
    wait = {"timeout", "interval", "created", "updated", "deleted", "exists", "custom"}
    expected = {
        "create": common | {"location", "tags", "system_assigned", "messaging_endpoints", "no_wait"},
        "update": common | {"tags", "system_assigned", "messaging_endpoints", "no_wait"},
        "delete": common | {"no_wait", "yes"},
        "migrate": common | {"resource_ids", "no_wait"},
        "show": common,
        "list": {"resource_group_name"},
        "wait": common | wait,
        "identity show": common,
        "identity assign": common | {"no_wait"},
        "identity remove": common | {"no_wait"},
        "identity wait": common | wait,
    }
    for name, arguments in expected.items():
        assert set(resolved_commands[f"iot adr ns {name}"].arguments) - {"cmd", "client"} == arguments


@pytest.mark.parametrize("operation,default", [("create", True), ("update", None)])
@pytest.mark.parametrize(
    "values,expected",
    [([], "default"), (["--system-assigned"], True),
     (["--system-assigned", "true"], True), (["--system-assigned", "false"], False)],
)
def test_system_identity_cli_parsing(resolved_commands, operation, default, values, expected):
    argument = resolved_commands[f"iot adr ns {operation}"].arguments["system_assigned"]
    parser = argparse.ArgumentParser()
    parser.add_argument(*argument.options_list, **argument.options)
    assert parser.parse_args(values).system_assigned is (default if expected == "default" else expected)


def test_system_identity_rejects_user_assigned_value(resolved_commands):
    argument = resolved_commands["iot adr ns create"].arguments["system_assigned"]
    parser = argparse.ArgumentParser()
    parser.add_argument(*argument.options_list, **argument.options)
    with pytest.raises(SystemExit):
        parser.parse_args(["--system-assigned", "UserAssigned"])
