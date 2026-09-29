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
from azure.cli.core.azclierror import ForbiddenError, InvalidArgumentValueError, UnauthorizedError
from azure.cli.testsdk.base import CheckerMixin
from azure.iot.device.common.transport_exceptions import NoConnectionError


class _ConnectedPnpClient(SimpleNamespace):
    def __setattr__(self, name, value):
        if name in ("on_method_request_received", "on_twin_desired_properties_patch_received") and not self.connected:
            raise NoConnectionError("Subscriptions require an explicit connection when auto_connect is disabled.")
        super().__setattr__(name, value)


def _arguments(text):
    return split(CheckerMixin._apply_kwargs(SimpleNamespace(kwargs={}), text))


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


@pytest.mark.parametrize("reenable_damage", [None, "status", "authentication", "attributes", "parentScopes"])
def test_identity_scenario_executes_each_required_authentication(preview, mocker, reenable_damage):
    module, expected = preview
    scenario, calls = _scenario(mocker)
    scenario.generate_device_names.return_value = ["parent", "device"]
    identities = {}
    authentication = {"symmetricKey": {"primaryKey": "unit-primary", "secondaryKey": "unit-secondary"}}

    def command(text):
        args = _arguments(text)
        identifier = args[args.index("-d") + 1]
        if args[2] == "module-identity":
            if args[3] == "create":
                assert identities[identifier]["status"] == "enabled", "Module CRUD must not inherit the disabled-device phase."
            identifier = "module"
        action = args[3]
        if action == "create":
            identities[identifier] = {
                "authentication": deepcopy(authentication), "attributes": {},
                "deviceScope": identifier + "-scope", "parentScopes": [], "status": "enabled",
            }
        elif action == "update":
            if any(flag in text for flag in (
                "--set adrDeviceProperties", "--remove adrDeviceProperties", "--add adrDeviceProperties",
            )):
                raise InvalidArgumentValueError("Service-owned property")
            attributes = next((arg.removeprefix("attributes=") for arg in args if arg.startswith("attributes=")), None)
            if attributes is not None:
                identities[identifier]["attributes"] = json.loads(attributes)
            if "--status" in args:
                identities[identifier]["status"] = args[args.index("--status") + 1]
                if identities[identifier]["status"] == "enabled" and reenable_damage:
                    identities[identifier][reenable_damage] = "unexpected change"
            if "--status-reason" in args:
                identities[identifier]["statusReason"] = args[args.index("--status-reason") + 1]
        elif action == "parent":
            identities[identifier]["parentScopes"] = [identities["parent"]["deviceScope"]]
        elif action == "renew-key":
            keys = identities[identifier]["authentication"]["symmetricKey"]
            keys["primaryKey"], keys["secondaryKey"] = keys["secondaryKey"], keys["primaryKey"]
        else:
            assert action == "show"
        return _result(identities[identifier])

    scenario.cmd.side_effect = command
    if reenable_damage:
        with pytest.raises(AssertionError):
            module.TestHubPreview.test_identity_roundtrip(scenario)
        assert not any("module-identity create" in text for _, text in calls)
        return
    module.TestHubPreview.test_identity_roundtrip(scenario)

    assert tuple(dict.fromkeys(phase for phase, _ in calls)) == expected
    for phase in expected:
        commands = [text for auth, text in calls if auth == phase]
        assert any("device-identity renew-key" in text for text in commands)
        assert any("device-identity parent set" in text for text in commands)
        assert any("module-identity update" in text for text in commands)
        enabled_index = next(index for index, text in enumerate(commands) if "--status enabled" in text)
        module_index = next(index for index, text in enumerate(commands) if "module-identity create" in text)
        swap_index = next(index for index, text in enumerate(commands) if "device-identity renew-key" in text)
        assert swap_index < enabled_index < module_index


@pytest.fixture
def pnp_scenario(preview, mocker):
    module, expected = preview
    scenario, calls = _scenario(mocker)
    scenario.generate_device_names.return_value = ["device"]
    scenario.get_device_cstring.return_value = "unit-connection-string"
    client = _ConnectedPnpClient(
        connected=False, connect=mocker.Mock(), shutdown=mocker.Mock(),
        send_method_response=mocker.Mock(), patch_twin_reported_properties=mocker.Mock(),
    )
    client.connect.side_effect = lambda: setattr(client, "connected", True)
    constructor = mocker.patch(
        "azure.iot.device.IoTHubDeviceClient.create_from_connection_string", return_value=client,
    )
    runtime = SimpleNamespace(
        module=module, expected=expected, scenario=scenario, calls=calls, client=client, constructor=constructor,
        gateway="V2", failure=None, failure_phase="login", failure_component=False,
    )

    def command(text):
        args = _arguments(text)
        if args[2] == "show":
            details = {"gatewayVersion": runtime.gateway} if runtime.gateway else {}
            return _result({"properties": {"iotHubDetails": details}})
        if args[2] == "device-identity":
            return _result()
        action = args[3]
        if action == "show":
            return _result({"serialNumber": "device", "thermostat1": {"temperature": 21}})
        if action == "update":
            client.on_twin_desired_properties_patch_received({"thermostat1": {"targetTemperature": 22}})
            return _result()
        assert action == "invoke-command"
        auth_phase = calls[-1][0]
        targeted = auth_phase == runtime.failure_phase and ("--component-path" in args) == runtime.failure_component
        if targeted and isinstance(runtime.failure, Exception):
            raise runtime.failure
        if runtime.gateway == "V2" and auth_phase == "login" and not (targeted and runtime.failure == "unexpected-success"):
            raise UnauthorizedError({"Message": '{"errorCode":401002,"message":"Unauthorized access"}'})
        name = args[args.index("--cn") + 1]
        if "--component-path" in args:
            name = args[args.index("--component-path") + 1] + "*" + name
        payload = json.loads(args[args.index("--payload") + 1])
        client.on_method_request_received(SimpleNamespace(name=name, payload=payload, request_id="unit-request"))
        response = client.send_method_response.call_args.args[0]
        return _result({"status": response.status, "payload": response.payload})

    scenario.cmd.side_effect = command
    return runtime


@pytest.mark.parametrize("gateway", ["V2", "V1", None])
def test_pnp_scenario_executes_each_required_authentication(pnp_scenario, gateway):
    runtime = pnp_scenario
    runtime.gateway = gateway
    module, scenario, expected = runtime.module, runtime.scenario, runtime.expected
    method = module.TestHubPreview.test_responding_digital_twin
    method(scenario)

    assert tuple(dict.fromkeys(phase for phase, _ in runtime.calls)) == expected
    for phase in expected:
        commands = [text for auth, text in runtime.calls if auth == phase]
        assert sum("digital-twin show" in text for text in commands) == 1
        assert sum("digital-twin update" in text for text in commands) == 1
        assert sum("digital-twin invoke-command" in text for text in commands) == 2
    timeout = next(mark for mark in method.pytestmark if mark.name == "timeout")
    assert timeout.args == (300 * len(expected),)
    runtime.constructor.assert_called_once()
    runtime.client.connect.assert_called_once()
    runtime.client.shutdown.assert_called_once()
    expected_responses = 2 * (len(expected) - (1 if gateway == "V2" else 0))
    assert runtime.client.send_method_response.call_count == expected_responses


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize("failure", [
    UnauthorizedError({"Message": '{"errorCode":401003}'}),
    UnauthorizedError({"Message": '{"errorCode":4010020}'}),
    UnauthorizedError("401002 is only incidental text"),
    ForbiddenError('{"errorCode":401002}'),
    RuntimeError("transport failed"),
    "unexpected-success",
])
def test_gwv2_login_only_accepts_documented_command_rejection(pnp_scenario, component, failure):
    runtime = pnp_scenario
    runtime.failure, runtime.failure_component = failure, component
    expected = pytest.fail.Exception if failure == "unexpected-success" else (
        AssertionError if isinstance(failure, UnauthorizedError) else type(failure)
    )
    with pytest.raises(expected):
        runtime.module.TestHubPreview.test_responding_digital_twin(runtime.scenario)
    runtime.client.shutdown.assert_called_once()


@pytest.mark.parametrize("gateway,phase", [("V1", "login"), (None, "login"), ("V2", "key"), ("V2", "cstring")])
def test_pnp_supported_command_authentication_still_requires_success(pnp_scenario, gateway, phase):
    runtime = pnp_scenario
    runtime.gateway = gateway
    runtime.module.AUTH_TYPES = (phase,)
    runtime.failure_phase = phase
    runtime.failure = UnauthorizedError({"Message": '{"errorCode":401002}'})
    with pytest.raises(UnauthorizedError):
        runtime.module.TestHubPreview.test_responding_digital_twin(runtime.scenario)
    runtime.client.shutdown.assert_called_once()


def test_pnp_command_callback_failure_still_fails(pnp_scenario):
    runtime = pnp_scenario
    runtime.module.AUTH_TYPES = ("key",)
    runtime.client.send_method_response.side_effect = RuntimeError("device response failed")
    with pytest.raises(RuntimeError, match="device response failed"):
        runtime.module.TestHubPreview.test_responding_digital_twin(runtime.scenario)
    runtime.client.shutdown.assert_called_once()


@pytest.mark.parametrize("failure", ["connect", "subscribe"])
def test_pnp_initialization_failure_still_shuts_down(preview, mocker, failure):
    module, _ = preview
    scenario, _ = _scenario(mocker)
    scenario.cmd.return_value = _result({"properties": {}})
    scenario.generate_device_names.return_value = ["device"]
    client = _ConnectedPnpClient(connected=False, connect=mocker.Mock(), shutdown=mocker.Mock())
    if failure == "connect":
        client.connect.side_effect = RuntimeError("Connection failed")
    mocker.patch("azure.iot.device.IoTHubDeviceClient.create_from_connection_string", return_value=client)

    with pytest.raises(RuntimeError if failure == "connect" else NoConnectionError):
        module.TestHubPreview.test_responding_digital_twin(scenario)

    client.shutdown.assert_called_once()
