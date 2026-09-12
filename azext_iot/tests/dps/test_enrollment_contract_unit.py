# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import shlex
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import CLIInternalError, ForbiddenError, UnauthorizedError
from azure.core.exceptions import HttpResponseError
from msrest.serialization import Model

from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.dps.services._enrollment_errors import handle_enrollment_error
from azext_iot.operations import dps


def _wire(value):
    return value.serialize(keep_readonly=True) if isinstance(value, Model) else value


@pytest.mark.parametrize("operation", ["create", "update", "show"])
@pytest.mark.parametrize("show_keys", [False, True])
def test_group_output_is_opt_in_without_changing_credentials(mocker, operation, show_keys):
    body = {
        "enrollmentGroupId": "group", "etag": "etag", "provisioningStatus": "enabled",
        "attestation": {"type": "symmetricKey", "symmetricKey": {
            "primaryKey": "primary-secret", "secondaryKey": "secondary-secret",
        }},
        "initialTwin": {"tags": {"array": ["one", "two"]}, "properties": {"desired": {"value": 1}}},
    }
    legacy = hasattr(dps, "EnrollmentGroup")
    response = dps.EnrollmentGroup.deserialize(body) if legacy else deepcopy(body)
    attestation = response.attestation if legacy else deepcopy(body["attestation"])
    sdk = mocker.Mock()
    sdk.enrollment_group.create_or_update.return_value = response
    sdk.enrollment_group.get.return_value = deepcopy(response)
    sdk.enrollment_group.get_attestation_mechanism.return_value = attestation
    if operation == "show" and legacy:
        sdk.enrollment_group.get.return_value = SimpleNamespace(response=mocker.Mock())
        sdk.enrollment_group.get.return_value.response.json.return_value = deepcopy(body)
        sdk.enrollment_group.get_attestation_mechanism.return_value = SimpleNamespace(response=mocker.Mock())
        sdk.enrollment_group.get_attestation_mechanism.return_value.response.json.return_value = deepcopy(body["attestation"])
    mocker.patch.object(dps, "DPSDiscovery").return_value.get_target.return_value = {"policy": "login"}
    mocker.patch.object(dps, "SdkResolver").return_value.get_sdk.return_value = sdk
    function = getattr(dps, "iot_dps_device_enrollment_group_" + ("get" if operation == "show" else operation))
    result = function(mocker.Mock(), "group", dps_name="dps", show_keys=show_keys)
    output = _wire(result)
    keys = output["attestation"].get("symmetricKey") or {}
    assert keys.get("primaryKey") == ("primary-secret" if show_keys else None)
    assert keys.get("secondaryKey") == ("secondary-secret" if show_keys else None)
    assert output["attestation"]["type"] == "symmetricKey"
    assert output["initialTwin"]["tags"]["array"] == ["one", "two"]
    assert _wire(response)["attestation"]["symmetricKey"] == body["attestation"]["symmetricKey"]
    if operation == "create":
        sdk.enrollment_group.get.assert_not_called()
        sdk.enrollment_group.get_attestation_mechanism.assert_not_called()
    if operation == "update":
        sent = _wire(sdk.enrollment_group.create_or_update.call_args.args[1])
        assert sent["attestation"]["symmetricKey"] == body["attestation"]["symmetricKey"]


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("operation", ["show enrollment", "create enrollment group"])
@pytest.mark.parametrize("policy", ["login", "service-policy"])
def test_enrollment_guidance_uses_effective_service_auth_and_preserves_cause(status, operation, policy):
    original = HttpResponseError("(403000) Unauthorized")
    original.status_code = status
    kind = UnauthorizedError if status == 401 else ForbiddenError

    def translate(error):
        assert error is original
        raise kind("(403000) Unauthorized") from error

    with pytest.raises(kind) as raised:
        handle_enrollment_error(original, {"policy": policy}, operation, translate)
    message = str(raised.value)
    assert "(403000) Unauthorized" in message and operation in message
    assert raised.value.__cause__ is original
    assert "DPS managed-identity" in message and "does not identify" in message
    if policy == "login":
        assert "Microsoft Entra" in message
        assert ("Data Contributor" in message) is operation.startswith("create")
    else:
        assert "SAS/shared-access policy" in message
        assert "Data Contributor" not in message


def test_connection_string_overrides_requested_login_auth(mocker):
    target = DPSDiscovery(mocker.Mock()).get_target(
        "ignored", login="HostName=dps.test;SharedAccessKeyName=service-policy;SharedAccessKey=not-a-live-key",
        auth_type="login",
    )
    assert target["policy"] == "service-policy"


@pytest.mark.parametrize("status", [401, 403])
def test_actual_discovery_handler_preserves_authorization_cause(mocker, status):
    original = HttpResponseError("(AuthorizationFailed) original service detail")
    original.status_code = status
    discovery = DPSDiscovery(mocker.Mock())
    discovery.client = mocker.Mock()
    discovery.client.get.side_effect = original
    kind = UnauthorizedError if status == 401 else ForbiddenError
    with pytest.raises(kind, match="ARM read/list-keys") as raised:
        discovery.find_resource("dps", "rg")
    assert raised.value.__cause__ is original
    assert "AuthorizationFailed" in str(raised.value)


@pytest.mark.parametrize("status", [404, 502])
def test_discovery_context_does_not_reclassify_other_http_errors(mocker, status):
    original = HttpResponseError("Original non-authorization error")
    original.status_code = status
    mocker.patch("azext_iot.common.base_discovery.BaseDiscovery.get_target", side_effect=original)
    with pytest.raises(HttpResponseError) as raised:
        DPSDiscovery(mocker.Mock()).get_target("dps", "rg")
    assert raised.value is original


def test_non_authorization_error_is_not_reclassified():
    original = RuntimeError("non-authentication failure")

    def translate(error):
        raise error

    with pytest.raises(RuntimeError) as raised:
        handle_enrollment_error(original, {"policy": "login"}, "create enrollment", translate)
    assert raised.value is original


def test_fresh_integration_cohorts_do_not_reuse_credentials_or_registrations(mocker):
    from azext_iot.common.utility import generate_key
    from azext_iot.tests.dps.device_registration import test_iot_device_registration_fresh_keys_int as fresh

    resource = {"name": "dps", "resourceGroup": "rg", "hubHostName": "hub.test", "iotHub": {},
                "dps": {"properties": {"idScope": "scope", "deviceProvisioningHostName": "configured.test"}}}
    cohorts, registrations, deleted, states = [], [], [], []
    selected_key = ["secondaryKey"]
    selected_endpoint = ["configured"]
    selected_kind = ["individual"]

    def invoke(command, capture_stderr):
        assert capture_stderr
        args = shlex.split(command)

        def value(option):
            return args[args.index(option) + 1]

        if args[1:3] == ["device", "registration"]:
            device_id = value("--registration-id")
            registrations.append(device_id)
            assert value("--key") == cohorts[-1][1][selected_key[0]]
            expected_host = "configured.test" if selected_endpoint[0] == "configured" else (
                "global.azure-devices-provisioning.net"
            )
            assert value("--host") == expected_host
            assert ("--compute-key" in args) == (selected_kind[0] == "group")
            assert (device_id == cohorts[-1][0]) == (selected_kind[0] == "individual")
            result = {"operationId": "op", "status": "assigned", "registrationState": {
                "registrationId": device_id, "deviceId": device_id,
                "assignedHub": "hub.test", "substatus": "initialAssignment",
                "createdDateTimeUtc": "2026-01-01T00:00:00Z", "lastUpdatedDateTimeUtc": "2026-01-01T00:00:00Z",
                "etag": "etag",
            }}
            states.append(result["registrationState"])
        elif args[3] == "create":
            assert "--primary-key" not in args and "--secondary-key" not in args
            keys = {"primaryKey": generate_key(), "secondaryKey": generate_key()}
            cohorts.append((value("--enrollment-id"), keys))
            assert args[2] != "enrollment-group" or "--show-keys" in args
            result = {"attestation": {"symmetricKey": keys}}
        elif args[3:5] == ["registration", "show"]:
            result = states[-1]
        else:
            assert args[3] == "delete"
            deleted.append(value("--enrollment-id"))
            result = {}
        return SimpleNamespace(as_json=lambda: result, success=lambda: True, error_code=0)

    mocker.patch.object(fresh, "EmbeddedCLI").return_value.invoke.side_effect = invoke
    check_hub = mocker.patch("azext_iot.tests.dps.device_registration.check_hub_device")
    finalizers = []
    request = SimpleNamespace(addfinalizer=finalizers.append)
    for kind in ("individual", "group"):
        for endpoint in ("configured", "global"):
            for key_name in ("secondaryKey", "primaryKey"):
                selected_key[0] = key_name
                selected_endpoint[0] = endpoint
                selected_kind[0] = kind
                fresh.test_fresh_registration_credential(resource, kind, endpoint, key_name, request)
                assert len(finalizers) == 1
                finalizers.pop()()
    assert len({enrollment for enrollment, _ in cohorts}) == 8
    assert len({key for _, keys in cohorts for key in keys.values()}) == 16
    assert len(set(registrations)) == 8
    assert deleted == [enrollment for enrollment, _ in cohorts]
    assert check_hub.call_count == 8


@pytest.mark.parametrize("kind", ["individual", "group"])
@pytest.mark.parametrize("outcome", ["assigning", "401002"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_fresh_generated_credential_preserves_failure_and_cleanup(mocker, kind, outcome, cleanup_fails):
    from azext_iot.common.utility import generate_key
    from azext_iot.tests.dps.device_registration import register_fresh_generated_credential

    cli = mocker.Mock()
    keys = {"primaryKey": generate_key(), "secondaryKey": generate_key()}
    commands = []
    denied = RuntimeError("401002")

    def invoke(command, capture_stderr):
        assert capture_stderr
        args = shlex.split(command)
        commands.append(args)
        if args[1:3] == ["device", "registration"]:
            assert args[args.index("--key") + 1] == keys["secondaryKey"]
            assert "--dps-name" in args and "--host" not in args
            if outcome == "401002":
                raise denied
            result = {"operationId": "op", "status": "assigning"}
        elif args[3] == "create":
            assert "--primary-key" not in args and "--secondary-key" not in args
            result = {"attestation": {"symmetricKey": keys}}
        else:
            assert args[3] == "delete"
            result = {}
        return SimpleNamespace(
            as_json=lambda: result,
            success=lambda: not (args[3] == "delete" and cleanup_fails),
            error_code=7 if cleanup_fails else 0,
        )

    cli.invoke.side_effect = invoke
    check_hub = mocker.patch("azext_iot.tests.dps.device_registration.check_hub_device")
    finalizers = []
    request = SimpleNamespace(addfinalizer=finalizers.append)
    with pytest.raises(RuntimeError if outcome == "401002" else AssertionError) as raised:
        register_fresh_generated_credential(
            cli, {"name": "dps", "resourceGroup": "rg"}, kind, "secondaryKey", request,
        )
    if outcome == "401002":
        assert raised.value is denied
    assert len(commands) == 2
    assert len(finalizers) == 1
    if cleanup_fails:
        with pytest.raises(CLIInternalError, match="exit code 7"):
            finalizers.pop()()
    else:
        finalizers.pop()()
    assert len(commands) == 3
    assert commands[-1][commands[-1].index("--enrollment-id") + 1] == (
        commands[0][commands[0].index("--enrollment-id") + 1]
    )
    check_hub.assert_not_called()


def test_fresh_cohort_does_not_accept_nonzero_create_without_error(mocker):
    from azext_iot.tests.dps.device_registration import register_fresh_generated_credential

    cli = mocker.Mock()
    cli.invoke.return_value.success.return_value = False
    cli.invoke.return_value.error_code = 7
    request = mocker.Mock()
    with pytest.raises(CLIInternalError, match="exit code 7"):
        register_fresh_generated_credential(
            cli, {"name": "dps", "resourceGroup": "rg"}, "individual", "secondaryKey", request,
        )
    request.addfinalizer.assert_not_called()
    cli.invoke.return_value.as_json.assert_not_called()
