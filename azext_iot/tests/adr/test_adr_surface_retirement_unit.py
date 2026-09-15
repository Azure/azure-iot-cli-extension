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
from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE, SU_ENDPOINT_TYPE
from azext_iot.tests.adr import test_adr_validation_scenarios_unit as validation_fixtures
from azext_iot.tests.adr import _helpers, test_adr_link_int


offline_cli = validation_fixtures.offline_cli


def test_registry_device_surface_is_retired_but_backend_group_type_remains(offline_cli):
    from azext_iot._factory import adr_service_factory
    from azext_iot.adr.common import GroupType

    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns"])
    load_adr_help()
    assert not any(name.startswith("iot adr ns registry-device") for name in table)
    assert not any(name.startswith("iot adr ns registry-device") for name in helps)
    assert GroupType.registry_device.value == "RegistryDevice"
    assert callable(adr_service_factory(offline_cli).registry_devices.get)
    for command in ("iot adr ns group create", "iot adr ns job create",
                    "iot hub device-identity create", "iot device registration create"):
        assert command in table
    with pytest.raises(SystemExit) as error:
        offline_cli.invoke(["iot", "adr", "ns", "registry-device", "list"])
    assert error.value.code == 2


@pytest.mark.parametrize("module", [_helpers, test_adr_link_int])
def test_cleanup_sources_do_not_construct_retired_commands(module):
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


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_retired_link_delete_is_absent_from_real_cli_and_help(offline_cli, kind):
    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns", "link", kind])
    for verb in ("add", "update", "show", "list", "wait"):
        assert f"iot adr ns link {kind} {verb}" in table
    assert f"iot adr ns link {kind} delete" not in table
    for command in ("iot adr ns delete", "iot hub delete", "iot dps delete", "iot adr ns su instance delete"):
        assert command in table
    load_adr_help()
    assert f"iot adr ns link {kind} delete" not in helps
    assert "Destructive delete" not in helps["iot adr ns link"]
    assert "namespace replacement" not in helps["iot adr ns link"]
    with pytest.raises(SystemExit) as error:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "delete"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "kind,section,endpoint_type",
    [
        ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
        ("dps", "provisioning", DPS_ENDPOINT_TYPE),
        ("su", "updating", SU_ENDPOINT_TYPE),
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
    if kind == "su":
        endpoints["my-su"] = endpoints.pop("primary")
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
