# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Existing receipt ownership plus GA registry assertions; all transports remain offline."""

from copy import deepcopy
import json
import shlex
from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import HttpResponse

from azext_iot.tests.dps import _registry_assertions as assertions
from azext_iot.tests.dps.device_registration import test_csr_registry_cleanup_unit as registry_tests

wire = registry_tests.wire


class _Response(HttpResponse):
    def __init__(self, request, payload):
        super().__init__(request, None)
        self.status_code, self.headers, self.reason = 200, {"Content-Type": "application/json"}, "OK"
        self.content = json.dumps(payload).encode()

    def body(self):
        return self.content

    def json(self):
        return json.loads(self.content)


@pytest.fixture
def case(wire, mocker, monkeypatch):
    owner = registry_tests.start(wire)
    device = registry_tests.device(wire)
    wire.devices[device["name"]] = device
    owner.record_result(registry_tests.result())
    state = SimpleNamespace(
        owner=owner, wire=wire, device=device,
        identity={"deviceId": owner.intent["device_id"], "uuid": device["properties"]["uuid"], "authType": "sas"},
        commands=[], failure=None, fail_on=None,
    )
    monkeypatch.setattr(assertions, "METADATA_TIMEOUT", 0)

    def invoke(command):
        args = shlex.split(command)
        state.commands.append(command)
        assert args[args.index("--subscription") + 1] == registry_tests.SUB
        assert not any(word in args for word in ("auth", "attribute", "capability"))
        if state.fail_on and state.fail_on in command:
            raise state.failure
        if "device-identity show " in command:
            assert args[args.index("--query") + 1] == (
                "{deviceId:deviceId,uuid:adrDeviceProperties.uuid,authType:authentication.type}"
            )
            body = state.identity
        elif " wait " in command:
            body = None
        elif " list " in command:
            body = [state.device]
        else:
            assert " show " in command
            body = state.device
        return SimpleNamespace(as_json=lambda: deepcopy(body))

    state.invoke = mocker.patch.object(assertions, "invoke", side_effect=invoke)
    return state


@pytest.mark.parametrize("certificate", [False, True])
def test_assertions_use_actual_metadata_and_same_owned_cleanup(case, certificate):
    assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=certificate)
    assert not (case.wire.directory / case.owner._name("resolved")).exists()
    assert any("--external-device-id backend-generated-external-id" in command for command in case.commands)
    assert not any("revoke-certs" in command or "show-keys" in command for command in case.commands)
    case.owner.cleanup()
    assert not case.wire.devices
    assert sum(method == "DELETE" for method, _ in case.wire.calls) == 1


@pytest.mark.parametrize("change", [
    lambda c: c.identity.update(deviceId="foreign"),
    lambda c: c.identity.update(uuid="foreign"),
    lambda c: c.identity.update(authType="foreign"),
])
def test_assertions_reject_changed_metadata_without_mutation(case, change):
    change(case)
    with pytest.raises(AssertionError):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


def test_metadata_readiness_is_bounded_and_does_not_mutate(case):
    case.identity["uuid"] = None
    with pytest.raises(AssertionError, match="Timed out"):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


def test_metadata_readiness_only_polls_until_hub_metadata_is_ready(case, monkeypatch):
    clock, sleeps, calls = [0], [], {}
    original = case.invoke.side_effect
    wait = assertions.wait_for_condition
    monkeypatch.setattr(assertions, "METADATA_TIMEOUT", 20)

    def pause(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def timed_wait(fetch, condition, **kwargs):
        return wait(fetch, condition, **kwargs, clock=lambda: clock[0], sleeper=pause)

    def delayed(command):
        result = original(command)
        calls[command] = calls.get(command, 0) + 1
        if "device-identity show " in command and calls[command] <= 2:
            return SimpleNamespace(as_json=lambda: {**case.identity, "uuid": None})
        return result

    monkeypatch.setattr(assertions, "wait_for_condition", timed_wait)
    case.invoke.side_effect = delayed
    assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert sleeps == [5, 5]
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


def test_identity_replacement_during_metadata_readiness_prevents_cleanup(case):
    original = case.invoke.side_effect

    def replace(command):
        result = original(command)
        if "device-identity show " in command:
            case.device["properties"]["uuid"] = "replacement"
        return result

    case.invoke.side_effect = replace
    with pytest.raises(AssertionError, match="identity changed"):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    with pytest.raises(AssertionError, match="Conflicting"):
        case.owner.cleanup()
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


@pytest.mark.parametrize("command", [
    "iot adr ns device show", "iot adr ns device list", "device-identity show",
])
def test_service_errors_propagate_without_read_or_action_retry(case, command):
    case.fail_on, case.failure = command, HttpResponseError("service denied")
    with pytest.raises(HttpResponseError) as raised:
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert raised.value is case.failure
    assert sum(command in value for value in case.commands) == 1
