# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests that exercise the extension command loader. Loading the full command
table and the arguments for every command executes the module-level command
registration, parameter registration and help registration code across all
service command groups (command_map.py, params.py, _help.py).
"""

import argparse
from types import SimpleNamespace

import pytest
from azure.cli.core.mock import DummyCli


@pytest.fixture(scope="module")
def loader():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli()
    loader = IoTExtCommandsLoader(cli_ctx=cli_ctx)
    return loader


@pytest.fixture(scope="module")
def command_table(loader):
    table = loader.load_command_table(None)
    return table


def test_command_table_loads(command_table):
    # The extension should register a non-trivial number of commands.
    assert command_table
    assert len(command_table) > 100
    # Spot check a few representative commands across services.
    for expected in [
        "iot du account create",
        "iot du instance create",
        "iot du update list",
        "iot dps enrollment create",
        "iot hub device-identity create",
        "iot hub topic-group create",
        "iot hub topic-group show",
        "iot hub topic-group list",
        "iot hub topic-group update",
        "iot hub topic-group delete",
    ]:
        assert expected in command_table, f"Missing command: {expected}"


def test_load_arguments_for_all_commands(loader, command_table):
    # Loading arguments for every command exercises all params.py modules.
    # skip_applicability avoids the need for a live invocation context.
    loader.skip_applicability = True
    for command_name in command_table:
        loader.load_arguments(command_name)
    # Argument registry should be populated.
    assert loader.command_table


@pytest.fixture(scope="module")
def resolved_topic_group_commands(loader, command_table):
    loader.cli_ctx.invocation = SimpleNamespace(data={})
    commands = {}
    for name in (
        "iot hub topic-group create",
        "iot hub topic-group show",
        "iot hub topic-group list",
        "iot hub topic-group update",
        "iot hub topic-group delete",
    ):
        loader.cli_ctx.invocation.data["command_string"] = name
        command = command_table[name]
        command.load_arguments()
        loader.load_arguments(name)
        loader._apply_parameter_info(name, command)
        commands[name] = command
    return commands


def test_topic_group_command_arguments(resolved_topic_group_commands):
    common = {"hub_name", "resource_group_name"}
    expected = {
        "create": common | {"topic_group_id", "topic_templates"},
        "show": common | {"topic_group_id"},
        "list": common,
        "update": common | {"topic_group_id", "topic_templates"},
        "delete": common | {"topic_group_id", "delete_all", "yes"},
    }

    for operation, arguments in expected.items():
        command = resolved_topic_group_commands[f"iot hub topic-group {operation}"]
        assert set(command.arguments) - {"cmd", "client"} == arguments


@pytest.mark.parametrize("operation", ["create", "update"])
def test_topic_group_templates_cli_parsing(
    resolved_topic_group_commands, operation
):
    argument = resolved_topic_group_commands[
        f"iot hub topic-group {operation}"
    ].arguments["topic_templates"]
    parser = argparse.ArgumentParser()
    parser.add_argument(*argument.options_list, **argument.options)

    assert parser.parse_args(["--topic-templates"]).topic_templates == []
    assert parser.parse_args(
        ["--topic-templates", "template/one", "template/two"]
    ).topic_templates == ["template/one", "template/two"]


@pytest.mark.parametrize(
    ("argument_name", "values", "expected"),
    [
        ("delete_all", [], False),
        ("delete_all", ["--all"], True),
        ("yes", [], False),
        ("yes", ["--yes"], True),
        ("yes", ["-y"], True),
    ],
)
def test_topic_group_delete_flag_cli_parsing(
    resolved_topic_group_commands, argument_name, values, expected
):
    argument = resolved_topic_group_commands[
        "iot hub topic-group delete"
    ].arguments[argument_name]
    parser = argparse.ArgumentParser()
    parser.add_argument(*argument.options_list, **argument.options)

    assert getattr(parser.parse_args(values), argument_name) is expected
