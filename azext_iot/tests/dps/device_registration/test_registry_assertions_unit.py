# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Existing receipt ownership plus registry assertions; all transports remain offline."""

from copy import deepcopy
import json
import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import HttpResponse, HttpTransport

from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr import test_adr_validation_scenarios_unit as cli_tests
from azext_iot.tests.dps import _csr_issuance as csr, _csr_registry as registry, _registry_assertions as assertions
from azext_iot.tests.dps.device_registration import test_csr_registry_cleanup_unit as registry_tests

wire = registry_tests.wire
offline_cli = cli_tests.offline_cli


@pytest.fixture
def case(wire, mocker, monkeypatch):
    owner = registry_tests.start(wire)
    device = registry_tests.device(wire)
    wire.devices[device["name"]] = device
    owner.record_result(registry_tests.result())
    profile = {
        "id": device["id"] + "/authenticationProfiles/server-profile", "name": "server-profile",
        "properties": {"authenticationType": "SymmetricKey"},
    }
    capability = {
        "id": device["id"] + "/capabilities/server-capability", "name": "server-capability",
        "properties": {"capabilityType": "Microsoft.IoTHub", "provisioningState": "Succeeded",
                       "authenticationProfileResourceId": profile["id"].swapcase()},
    }
    state = SimpleNamespace(
        owner=owner, wire=wire, device=device, profile=profile, capability=capability,
        identity={"deviceId": owner.intent["device_id"], "uuid": device["properties"]["uuid"], "authType": "sas"},
        profiles=[profile], capabilities=[capability], keys={"primary": 44, "secondary": 44},
        commands=[], failure=None, fail_on=None, action_error=None,
    )
    monkeypatch.setattr(assertions, "METADATA_TIMEOUT", 0)

    def invoke(command):
        args = shlex.split(command)
        state.commands.append(command)
        assert args[args.index("--subscription") + 1] == registry_tests.SUB
        if state.fail_on and state.fail_on in command:
            raise state.failure
        if "device-identity show " in command:
            assert args[args.index("--query") + 1] == (
                "{deviceId:deviceId,uuid:adrDeviceProperties.uuid,authType:authentication.type}"
            )
            body = state.identity
        elif " auth list " in command:
            body = state.profiles
        elif " auth show-keys " in command:
            assert args[args.index("--query") + 1] == assertions.KEY_LENGTH_QUERY
            body = state.keys
        elif " auth show " in command:
            body = state.profile
        elif " capability list " in command:
            body = state.capabilities
        elif " capability show " in command:
            body = state.capability
        elif " auth revoke-certs " in command:
            assert "--yes" in args and "--no-wait" not in args
            receipt = json.loads((wire.directory / owner._name("profile-action")).read_text())
            assert receipt["profile_id"] == profile["id"] and receipt["completed"] is False
            if state.action_error:
                raise state.action_error
            state.device["etag"] = '"updated-by-revocation"'
            body = None
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


def certificate(case):
    case.profile["properties"] = {
        "authenticationType": "CertificateAuthoritySignedX509Certificate",
        "certificateAuthority": {
            "certificatePolicyResourceId": (
                case.owner.namespace["id"] + "/certificateAuthorities/issuingca/certificatePolicies/leafpolicy"
            ),
        },
    }


@pytest.mark.parametrize("ca", [False, True])
def test_assertions_use_actual_metadata_and_same_owned_cleanup(case, ca):
    if ca:
        certificate(case)
    assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=ca)
    assert not (case.wire.directory / case.owner._name("resolved")).exists()
    assert any("--external-device-id backend-generated-external-id" in command for command in case.commands)
    assert any("auth show " in command and "server-profile" in command for command in case.commands)
    assert any("capability show " in command and "server-capability" in command for command in case.commands)
    assert sum("revoke-certs" in command for command in case.commands) == int(ca)
    assert sum("show-keys" in command for command in case.commands) == int(not ca)
    case.owner.cleanup()
    assert not case.wire.devices
    assert sum(method == "DELETE" for method, _ in case.wire.calls) == 1


@pytest.mark.parametrize("change", [
    lambda c: c.identity.update(deviceId="foreign"),
    lambda c: c.identity.update(uuid="foreign"),
    lambda c: c.identity.update(authType="foreign"),
    lambda c: c.profiles.append(deepcopy(c.profile)),
    lambda c: c.profile.update(id=c.profile["id"] + "-foreign"),
    lambda c: c.profile["properties"].update(symmetricKey={"primaryKey": "must-not-appear"}),
    lambda c: c.capability.update(id=c.capability["id"] + "-foreign"),
    lambda c: c.capability["properties"].update(provisioningState="Failed"),
    lambda c: c.keys.update(primary=0),
    lambda c: c.keys.update(primary=True),
    lambda c: c.keys.update(primary="not-a-length"),
    lambda c: c.keys.update(unexpected=1),
])
def test_assertions_reject_changed_metadata_without_mutation(case, change):
    change(case)
    with pytest.raises(AssertionError):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert not any("revoke-certs" in command for command in case.commands)
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


def test_certificate_policy_mismatch_never_revokes(case):
    certificate(case)
    case.profile["properties"]["certificateAuthority"]["certificatePolicyResourceId"] += "-foreign"
    with pytest.raises(AssertionError):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    assert not any("revoke-certs" in command for command in case.commands)


@pytest.mark.parametrize("kind", ["profile", "capability", "hub"])
def test_metadata_readiness_is_bounded_and_does_not_mutate(case, kind):
    if kind == "profile":
        case.profiles.clear()
    elif kind == "capability":
        case.capabilities.clear()
    else:
        case.identity["uuid"] = None
    with pytest.raises(AssertionError, match="Timed out"):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert not any("revoke-certs" in command or "show-keys" in command for command in case.commands)


def test_metadata_readiness_only_polls_until_expected_profile_and_capability_are_ready(case, monkeypatch):
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
        if " auth list " in command and calls[command] == 1:
            return SimpleNamespace(as_json=lambda: [])
        if " capability list " in command and calls[command] <= 2:
            pending = deepcopy(case.capability)
            pending["properties"]["provisioningState"] = "Accepted"
            value = [] if calls[command] == 1 else [pending]
            return SimpleNamespace(as_json=lambda: value)
        return result

    monkeypatch.setattr(assertions, "wait_for_condition", timed_wait)
    case.invoke.side_effect = delayed
    assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert sleeps == [5, 5, 5]
    assert sum("auth show-keys" in command for command in case.commands) == 1
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


def test_identity_replacement_during_metadata_readiness_prevents_revocation_and_cleanup(case):
    certificate(case)
    original = case.invoke.side_effect

    def replace(command):
        result = original(command)
        if " capability show " in command:
            case.device["properties"]["uuid"] = "replacement"
        return result

    case.invoke.side_effect = replace
    with pytest.raises(AssertionError, match="identity changed"):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    with pytest.raises(AssertionError, match="Conflicting"):
        case.owner.cleanup()
    assert not any("revoke-certs" in command for command in case.commands)


@pytest.mark.parametrize("command", ["auth list", "capability list", "device-identity show", "auth show-keys"])
def test_service_errors_propagate_without_read_or_action_retry(case, command):
    case.fail_on, case.failure = command, HttpResponseError("service denied")
    with pytest.raises(HttpResponseError) as raised:
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=False)
    assert raised.value is case.failure
    assert sum(command in value for value in case.commands) == 1


def test_uncertain_revocation_is_not_replayed_and_controller_retains_quarantine(case):
    certificate(case)
    case.action_error = HttpResponseError("accepted action response lost")
    with pytest.raises(HttpResponseError) as raised:
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    assert raised.value is case.action_error
    with pytest.raises(RuntimeError, match="refuses to repeat"):
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    with pytest.raises(AssertionError, match="quarantined"):
        case.owner.cleanup()
    with pytest.raises(AssertionError, match="quarantined"):
        registry.cleanup_registry_devices(case.owner.namespace)
    assert sum("revoke-certs" in command for command in case.commands) == 1
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


@pytest.mark.parametrize("permission", [
    "Microsoft.DeviceRegistry/locations/asyncOperationStatuses/read",
    "Microsoft.DeviceRegistry/namespaces/registryDevices/authenticationProfiles/read",
    "Microsoft.Other/unrelated/read",
])
def test_revocation_403_and_changed_metadata_cannot_complete_or_release_cleanup(case, permission):
    certificate(case)
    case.action_error = HttpResponseError(f"AuthorizationFailed: {permission}")
    case.action_error.status_code = 403
    original = case.invoke.side_effect

    def mutate_then_fail(command):
        if " auth revoke-certs " in command:
            case.device["etag"] = '"changed-after-submission"'
            case.profile["properties"]["provisioningState"] = "Succeeded"
            case.profile["systemData"] = {"lastModifiedAt": "2026-09-22T00:00:00Z"}
        return original(command)

    case.invoke.side_effect = mutate_then_fail
    with pytest.raises(HttpResponseError) as raised:
        assertions.assert_registry_registration(case.wire.resource, case.owner, certificate=True)
    assert raised.value is case.action_error
    receipt = json.loads((case.wire.directory / case.owner._name("profile-action")).read_text())
    assert receipt["completed"] is False
    for cleanup in (case.owner.cleanup, registry.require_registry_cleanup_resolved):
        with pytest.raises(AssertionError, match="quarantined"):
            cleanup()
    assert sum("revoke-certs" in command for command in case.commands) == 1
    assert not any("show-keys" in command or "--no-wait" in command for command in case.commands)
    assert not any(method == "DELETE" for method, _ in case.wire.calls)


@pytest.mark.parametrize("name", [None, "", ".", "..", "nested/child", "escaped%2fchild"])
def test_child_names_cannot_redirect_commands(name):
    with pytest.raises(AssertionError):
        assertions._child_name({"name": name, "id": "/foreign"}, "/parent", "capabilities")


class _Response(HttpResponse):
    def __init__(self, request, payload):
        super().__init__(request, None)
        self.status_code, self.headers, self.reason = 200, {"Content-Type": "application/json"}, "OK"
        self.content = json.dumps(payload).encode()

    def body(self):
        return self.content

    def json(self):
        return json.loads(self.content)


def test_native_cli_key_projection_never_reaches_embedded_output_or_logs(offline_cli, mocker, caplog):
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline-token", 4102444800)))
    transport = MagicMock(spec=HttpTransport)
    secret = "DO-NOT-LOG-REAL-NATIVE-KEY"
    requests = []

    def send(request, **_kwargs):
        requests.append(request)
        payload = (
            {"symmetricKey": {"primaryKey": secret, "secondaryKey": secret + "-secondary"}}
            if request.method == "POST" else {"name": "profile", "properties": {"authenticationType": "SymmetricKey"}}
        )
        return _Response(request, payload)

    transport.send.side_effect = send
    client = DeviceRegistryMgmtClient(credential, registry_tests.SUB, transport=transport)
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    mocker.patch("azext_iot.common.embedded_cli.get_default_cli", return_value=offline_cli)
    mocker.patch.object(csr.fixtures, "cli", SimpleNamespace(az_cli=offline_cli))
    try:
        with caplog.at_level("DEBUG"):
            result = csr.invoke(
                "iot adr ns device auth show-keys --ns ns -g rg --rdn device -n profile "
                f"--query {shlex.quote(assertions.KEY_LENGTH_QUERY)}"
            )
        assert result.as_json() == {"primary": len(secret), "secondary": len(secret + "-secondary")}
        assert [request.method for request in requests] == ["GET", "POST"]
        assert requests[-1].url.split("?")[0].endswith("/authenticationProfiles/profile/listKeys")
        assert secret not in caplog.text and secret not in result.output
    finally:
        client.close()
