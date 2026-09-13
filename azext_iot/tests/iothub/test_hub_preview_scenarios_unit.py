# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Execute preview scenario wiring without credentials, resources, or SDK threads."""

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from shlex import split
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError


@pytest.fixture(params=[
    ("regular", ("login",)),
    ("local-auth", ("key", "login", "cstring")),
])
def preview(request, monkeypatch):
    mode, expected = request.param
    monkeypatch.setenv("azext_iot_hub_auth_phase", mode)
    path = Path(__file__).parent / "devices" / "test_hub_preview_int.py"
    spec = spec_from_file_location("_preview_auth_wiring", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, expected


def _result(value=None):
    return SimpleNamespace(get_output_in_json=lambda: deepcopy(value))


def _scenario(mocker):
    scenario = mocker.Mock()
    scenario.entity_name = "unit-hub"
    scenario.entity_rg = "unit-rg"
    scenario.generate_module_names.return_value = ["module"]
    calls = []

    def auth(command, auth_type):
        calls.append((auth_type, command))
        return command

    scenario.set_cmd_auth_type.side_effect = auth
    return scenario, calls


def test_identity_scenario_executes_each_required_authentication(preview, mocker):
    module, expected = preview
    scenario, calls = _scenario(mocker)
    scenario.generate_device_names.return_value = ["parent", "device"]
    identities = {}
    authentication = {"symmetricKey": {"primaryKey": "unit-primary", "secondaryKey": "unit-secondary"}}

    def command(text):
        args = split(text)
        identifier = args[args.index("-d") + 1]
        if args[2] == "module-identity":
            identifier = "module"
        action = args[3]
        if action == "create":
            identities[identifier] = {
                "authentication": deepcopy(authentication), "attributes": {},
                "deviceScope": identifier + "-scope", "parentScopes": [],
            }
        elif action == "update":
            if any(flag in text for flag in (
                "--set adrDeviceProperties", "--remove adrDeviceProperties", "--add adrDeviceProperties",
            )):
                raise InvalidArgumentValueError("Service-owned property")
            attributes = next(arg.removeprefix("attributes=") for arg in args if arg.startswith("attributes="))
            identities[identifier].update({
                "attributes": json.loads(attributes), "status": "disabled", "statusReason": "preview",
            })
        elif action == "parent":
            identities[identifier]["parentScopes"] = [identities["parent"]["deviceScope"]]
        elif action == "renew-key":
            keys = identities[identifier]["authentication"]["symmetricKey"]
            keys["primaryKey"], keys["secondaryKey"] = keys["secondaryKey"], keys["primaryKey"]
        else:
            assert action == "show"
        return _result(identities[identifier])

    scenario.cmd.side_effect = command
    module.TestHubPreview.test_identity_roundtrip(scenario)

    assert tuple(dict.fromkeys(phase for phase, _ in calls)) == expected
    for phase in expected:
        commands = [text for auth, text in calls if auth == phase]
        assert any("device-identity renew-key" in text for text in commands)
        assert any("device-identity parent set" in text for text in commands)
        assert any("module-identity update" in text for text in commands)


def test_pnp_scenario_executes_each_required_authentication(preview, mocker):
    module, expected = preview
    scenario, calls = _scenario(mocker)
    scenario.generate_device_names.return_value = ["device"]
    scenario.get_device_cstring.return_value = "unit-connection-string"
    client = mocker.Mock()
    constructor = mocker.patch(
        "azure.iot.device.IoTHubDeviceClient.create_from_connection_string", return_value=client,
    )

    def command(text):
        args = split(text)
        if args[2] == "device-identity":
            return _result()
        action = args[3]
        if action == "show":
            return _result({"serialNumber": "device", "thermostat1": {"temperature": 21}})
        if action == "update":
            client.on_twin_desired_properties_patch_received({"thermostat1": {"targetTemperature": 22}})
            return _result()
        assert action == "invoke-command"
        name = args[args.index("--cn") + 1]
        if "--component-path" in args:
            name = args[args.index("--component-path") + 1] + "*" + name
        payload = json.loads(args[args.index("--payload") + 1])
        client.on_method_request_received(SimpleNamespace(name=name, payload=payload, request_id="unit-request"))
        response = client.send_method_response.call_args.args[0]
        return _result({"status": response.status, "payload": response.payload})

    scenario.cmd.side_effect = command
    method = module.TestHubPreview.test_responding_digital_twin
    method(scenario)

    assert tuple(dict.fromkeys(phase for phase, _ in calls)) == expected
    for phase in expected:
        commands = [text for auth, text in calls if auth == phase]
        assert sum("digital-twin show" in text for text in commands) == 1
        assert sum("digital-twin update" in text for text in commands) == 1
        assert sum("digital-twin invoke-command" in text for text in commands) == 2
    timeout = next(mark for mark in method.pytestmark if mark.name == "timeout")
    assert timeout.args == (300 * len(expected),)
    constructor.assert_called_once()
    client.shutdown.assert_called_once()
