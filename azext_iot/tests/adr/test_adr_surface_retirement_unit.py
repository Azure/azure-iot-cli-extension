# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
import inspect
import json
import re
import shlex
from io import StringIO

import pytest
import yaml
from azure.cli.core import MainCommandsLoader
from knack.help_files import helps

from azext_iot.adr._help import load_adr_help
from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
)
from azext_iot.tests.adr import test_adr_validation_scenarios_unit as validation_fixtures
from azext_iot.tests.adr import _helpers, test_adr_link_int


offline_cli = validation_fixtures.offline_cli


def test_namespace_device_ga_surface_and_operation_group_remain(offline_cli):
    from azext_iot._factory import adr_service_factory

    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns"])
    load_adr_help()
    expected = {
        f"iot adr ns device {verb}"
        for verb in ("create", "show", "list", "update", "delete", "wait")
    }
    assert {name for name in table if name.startswith("iot adr ns device")} == expected
    assert expected <= set(helps)
    assert not any(name.startswith("iot adr ns registry-device") for name in table)
    assert not any(name.startswith("iot adr ns registry-device") for name in helps)
    assert callable(adr_service_factory(offline_cli).registry_devices.get)
    for command in ("iot hub device-identity create", "iot device registration create",
                    "iot hub job list", "iot dps enrollment-group list", "iot du account create"):
        assert command in table


@pytest.mark.parametrize("prefix", [
    "iot adr ns group", "iot adr ns job", "iot adr ns report", "iot adr ns link su", "iot adr ns su",
    "iot adr ns device auth", "iot adr ns device attribute", "iot adr ns device capability",
])
def test_preview_only_surfaces_are_absent_from_ga_registration_and_help(offline_cli, prefix):
    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr"])
    load_adr_help()
    assert not any(name == prefix or name.startswith(prefix + " ") for name in table)
    assert not any(name == prefix or name.startswith(prefix + " ") for name in helps)


def test_registry_device_command_spelling_is_not_registered(offline_cli):
    with pytest.raises(SystemExit) as error:
        offline_cli.invoke(["iot", "adr", "ns", "registry-device", "show"])
    assert error.value.code == 2


@pytest.mark.parametrize("module", [_helpers, test_adr_link_int])
def test_resource_cleanup_does_not_use_endpoint_delete_commands(module):
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{dynamic}"
                for part in node.values
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        assert not re.search(r"iot adr ns link (?:hub|dps|su|\{[^}]*\}) delete\b", text)


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_endpoint_delete_is_registered_without_restoring_composite_deletion(offline_cli, kind):
    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns", "link", kind])
    for verb in ("add", "update", "show", "list", "wait", "remove"):
        assert f"iot adr ns link {kind} {verb}" in table
    assert f"iot adr ns link {kind} delete" not in table
    for command in ("iot adr ns delete", "iot hub delete", "iot dps delete", ):
        assert command in table
    load_adr_help()
    assert f"iot adr ns link {kind} remove" in helps
    assert "Destructive delete" not in helps["iot adr ns link"]
    assert "does not delete or check the linked resource" in helps["iot adr ns link"]
    with pytest.raises(SystemExit) as error:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "kind,section,endpoint_type",
    [
        ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
        ("dps", "provisioning", DPS_ENDPOINT_TYPE),

    ],
)
def test_link_state_help_examples_run_against_top_level_output(
    offline_cli, mocker, kind, section, endpoint_type
):
    endpoints = {
        name: {
            "endpointType": endpoint_type,
            "linkingState": state,
            "properties": {"provisioningState": "Succeeded"},
        }
        for name, state in (("primary", "Failed"), ("ready", "Succeeded"))
    }
    mocker.patch(
        "azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
        return_value={"properties": {section: {"endpoints": endpoints}}},
    )
    load_adr_help()
    executed = 0
    for verb in ("show", "list"):
        examples = yaml.safe_load(helps[f"iot adr ns link {kind} {verb}"])["examples"]
        for example in examples:
            arguments = shlex.split(example["text"])[1:]
            if "--query" not in arguments:
                continue
            query = arguments[arguments.index("--query") + 1]
            assert "properties.provisioningState" not in query
            output = StringIO()
            assert offline_cli.invoke(arguments, out_file=output) == 0
            assert offline_cli.result.error is None
            if verb == "show":
                assert output.getvalue().strip() == "Failed"
            elif query.startswith("[?"):
                result = json.loads(output.getvalue())
                assert len(result) == 1
                assert result[0]["linkingState"] == "Failed"
            else:
                result = json.loads(output.getvalue())
                assert {item["linkingState"] for item in result} == {"Failed", "Succeeded"}
                assert all(set(item) == {"name", "linkingState"} for item in result)
            executed += 1
    assert executed == 3
