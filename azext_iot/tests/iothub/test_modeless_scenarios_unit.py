# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exercise existing live assertions with modeless and omitted optional fields."""

from contextlib import nullcontext
from copy import deepcopy
import json
from shlex import split
from types import SimpleNamespace

import pytest
from azure.cli.testsdk.base import CheckerMixin

from azext_iot.tests.iothub.core import test_iot_messaging_int as messaging
from azext_iot.tests.iothub.devices import test_iot_edge_devices_create_int as edge
from azext_iot.tests.iothub.devices import test_iothub_device_twin_int as device_twins
from azext_iot.tests.iothub.modules import test_iothub_module_twin_int as module_twins
from azext_iot.tests.iothub.modules import test_iothub_modules_int as modules


def _result(value):
    return SimpleNamespace(get_output_in_json=lambda: deepcopy(value))


def _scenario():
    return SimpleNamespace(
        entity_name="unit-hub", entity_rg="unit-rg", host_name="unit-hub.example",
        kwargs={}, generate_device_names=lambda _count: ["device"],
        generate_module_names=lambda _count: ["module", "certificate-module"],
        set_cmd_auth_type=lambda command, auth_type: command,
        check=lambda *args: args, exists=lambda expression: expression,
    )


@pytest.mark.parametrize("module,method", [
    (device_twins, device_twins.TestIoTHubDeviceTwin.test_iothub_device_twin),
    (module_twins, module_twins.TestIoTHubModuleTwin.test_iothub_module_twin),
])
@pytest.mark.parametrize("empty_tags,error", [
    ("omitted", None), ("null", None), ("empty", None), ("retained", AssertionError),
])
def test_twin_lifecycle_optional_tags(module, method, empty_tags, error, monkeypatch):
    monkeypatch.setattr(module, "DATAPLANE_AUTH_TYPES", ["login"])
    scenario = _scenario()
    twin = {"deviceId": "device", "moduleId": "device",
            "properties": {"desired": {"$version": 1}, "reported": {"$version": 1}}}
    commands = []

    def command(text, **kwargs):
        args = split(CheckerMixin._apply_kwargs(scenario, text))
        commands.append(args)
        if args[3] != "update":
            return _result(twin)
        if kwargs.get("expect_failure"):
            assert args[-1] == "badinput"
            return _result(None)
        for flag in ("--desired", "--tags"):
            if flag not in args:
                continue
            target = twin["properties"]["desired"] if flag == "--desired" else twin.setdefault("tags", {})
            patch = json.loads(args[args.index(flag) + 1])
            for key, value in patch.items():
                if value is None:
                    target.pop(key)
                else:
                    target[key] = value
            if flag == "--desired":
                target["$version"] += 1
            elif not target:
                if empty_tags == "omitted":
                    twin.pop("tags")
                elif empty_tags == "null":
                    twin["tags"] = None
                elif empty_tags == "retained":
                    twin["tags"] = {"unexpected": "still-present"}
        return _result(twin)

    scenario.cmd = command
    with pytest.raises(error) if error else nullcontext():
        method(scenario)
    if not error:
        assert twin["properties"]["desired"]["$version"] == 4
        assert commands[-1][-1] == "badinput"


@pytest.mark.parametrize("actual,error", [
    (["device"], None), ([], AssertionError), (["other"], AssertionError),
    (["device", "unexpected"], AssertionError),
])
def test_edge_validation_uses_exact_modeless_identity_set(actual, error, mocker):
    provider = mocker.patch.object(edge, "DeviceIdentityProvider").return_value
    provider.service_sdk.devices.get_devices.return_value = [{"deviceId": value} for value in actual]
    scenario = _scenario()
    scenario.cmd = mocker.Mock(return_value=_result({"deviceId": "device"}))
    expected = [edge.EdgeDevicesTestConfig("device", None, None, None, None)]
    with pytest.raises(error) if error else nullcontext():
        edge.TestNestedEdgeHierarchy._validate_results(scenario, expected, output_path=None)
    provider.service_sdk.devices.get_devices.assert_called_once_with()
    if error:
        scenario.cmd.assert_not_called()
    else:
        scenario.cmd.assert_called_once_with(
            "iot hub device-identity show -d device -n unit-hub -g unit-rg"
        )


@pytest.mark.parametrize("primary,error", [
    ("omitted", None), ("null", None), ("unexpected-primary", AssertionError),
    ("extra-module", AssertionError),
])
def test_module_rotation_optional_unrequested_key(primary, error, monkeypatch):
    monkeypatch.setattr(modules, "DATAPLANE_AUTH_TYPES", ["login"])
    scenario = _scenario()
    keys = {"primaryKey": "unit-primary", "secondaryKey": "unit-secondary"}
    bulk_calls = []

    def command(text):
        args = split(text)
        if args[3] == "renew-key":
            kind = args[args.index("--kt") + 1]
            if kind == "swap":
                keys["primaryKey"], keys["secondaryKey"] = keys["secondaryKey"], keys["primaryKey"]
            elif kind == "both":
                keys.update(primaryKey="renewed-primary", secondaryKey="renewed-secondary")
            else:
                assert kind == "secondary" and args[args.index("-m") + 1] == "*"
                bulk_calls.append(args)
                rotated = {"id": "device", "moduleId": "module", "secondaryKey": "bulk-secondary"}
                if primary not in ("omitted", "extra-module"):
                    rotated["primaryKey"] = None if primary == "null" else primary
                results = [rotated]
                if primary == "extra-module":
                    results.append({"id": "device", "moduleId": "certificate-module", "secondaryKey": "invalid"})
                return _result({"policyKey": "secondaryKey", "rotatedKeys": results})
        return _result({"authentication": {"symmetricKey": keys}})

    scenario.cmd = command
    with pytest.raises(error) if error else nullcontext():
        modules.TestIoTHubModules.test_iothub_module_renew_key(scenario)
    assert len(bulk_calls) == 1


@pytest.mark.parametrize("module_id,device_id,purged,error", [
    ("omitted", "device", 3, None), ("null", "device", 3, None),
    ("unexpected", "device", 3, AssertionError),
    ("omitted", "other", 3, AssertionError), ("omitted", "device", 2, AssertionError),
])
def test_feedback_scenario_optional_purge_module(module_id, device_id, purged, error):
    scenario = _scenario()
    scenario.connection_string = "unit-connection"
    scenario.is_empty = lambda: None
    monitors, invalid_acks, auto_acks = [], [], []
    scenario.command_execute_assert = lambda command, expected: monitors.append((command, expected))
    state = {"ack": None}

    def command(text, **kwargs):
        args = split(text)
        action = args[3]
        if kwargs.get("expect_failure"):
            invalid_acks.append(args)
            return _result(None)
        if action == "send":
            state["ack"] = args[args.index("--ack") + 1] if "--ack" in args else None
        if action == "receive":
            result = {
                "etag": "unit-etag", "data": "unit-payload",
                "properties": {"system": {"iothub-messageid": "unit-message", "iothub-ack": state["ack"]}},
            }
            for ack in ("complete", "abandon", "reject"):
                if f"--{ack}" in args:
                    auto_acks.append(ack)
                    result["ack"] = ack
            return _result(result)
        if action == "purge":
            result = {"deviceId": device_id, "totalMessagesPurged": purged}
            if module_id != "omitted":
                result["moduleId"] = None if module_id == "null" else module_id
            return _result(result)
        return _result(None)

    scenario.cmd = command
    with pytest.raises(error) if error else nullcontext():
        messaging.TestIoTHubMessaging.test_hub_monitor_feedback(scenario)
    assert len(monitors) == 3
    if not error:
        assert len(invalid_acks) == 3
        assert auto_acks == ["complete", "abandon", "reject"]
