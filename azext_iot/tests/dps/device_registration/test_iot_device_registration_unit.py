# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock, patch

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.dps import commands_device_registration as commands
import azext_iot.dps.providers.device_registration as subject
from azext_iot.dps.providers.device_registration import (
    DeviceRegistrationProvider,
    _read_csr_argument,
    _parse_body,
)
from azext_iot.dps.common import (
    DISABLED_REGISTRATION_ERROR,
    FAILED_REGISTRATION_ERROR,
)
from azext_iot.constants import IOTDPS_PROVISIONING_HOST


def _provider(
    id_scope="scope",
    provisioning_host="device.example.test",
    **kwargs,
):
    cmd = MagicMock()
    with patch.object(subject, "dps_device_service_factory") as factory:
        provider = DeviceRegistrationProvider(
            cmd=cmd,
            registration_id="reg",
            id_scope=id_scope,
            provisioning_host=provisioning_host,
            device_symmetric_key="device-key",
            **kwargs,
        )
        provider._get_client()
    return provider, factory


def _http_error(status=400):
    response = MagicMock(status_code=status)
    error = HttpResponseError(message="service failure", response=response)
    error.status_code = status
    return error


def test_generated_response_capture_and_retry_header_parsing():
    pipeline_response = MagicMock()
    pipeline_response.http_response.status_code = 202

    captured = subject._capture_device_response(
        pipeline_response,
        {"operationId": "operation"},
        {"Retry-After": "4"},
    )

    assert captured == subject._DeviceResponse(
        202, {"operationId": "operation"}, {"Retry-After": "4"}
    )
    assert subject._retry_after_seconds({"retry-after": "invalid"}) == 2
    assert subject._retry_after_seconds({"RETRY-AFTER": "45"}) == 30


def test_terminal_registration_validation_ignores_non_object_results():
    assert subject._raise_for_terminal_registration(None) is None


def test_init_uses_explicit_service_endpoint():
    provider, factory = _provider()

    assert provider.id_scope == "scope"
    assert provider.registration_id == "reg"
    factory.assert_called_once_with(
        provider.cmd.cli_ctx,
        endpoint="https://device.example.test",
        registration_id="reg",
        id_scope="scope",
        device_symmetric_key="device-key",
        certificate_file=None,
        key_file=None,
        passphrase=None,
    )


def test_get_idscope_and_endpoint_from_discovered_dps(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {
        "idscope": "scopeABC",
        "deviceHostName": "regional.azure-devices-provisioning.net",
    }
    factory = mocker.patch.object(subject, "dps_device_service_factory")

    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        dps_name="mydps",
        device_symmetric_key="device-key",
    )
    provider._get_client()

    assert provider.id_scope == "scopeABC"
    factory.assert_called_once_with(
        provider.cmd.cli_ctx,
        endpoint="https://regional.azure-devices-provisioning.net",
        registration_id="reg",
        id_scope="scopeABC",
        device_symmetric_key="device-key",
        certificate_file=None,
        key_file=None,
        passphrase=None,
    )


@pytest.mark.parametrize(
    "identifier",
    [
        {"dps_name": "mydps"},
        {
            "login": (
                "HostName=mydps.azure-devices-provisioning.net;"
                "SharedAccessKeyName=owner;SharedAccessKey=key"
            )
        },
    ],
)
def test_explicit_idscope_still_resolves_supplied_target_hostname(
    mocker, identifier
):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {
        "idscope": "discovered-scope",
        "deviceHostName": "regional.azure-devices-provisioning.net",
    }
    factory = mocker.patch.object(subject, "dps_device_service_factory")

    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="explicit-scope",
        device_symmetric_key="device-key",
        **identifier,
    )
    provider._get_client()

    discovery.return_value.get_target.assert_called_once()
    assert provider.id_scope == "explicit-scope"
    assert (
        factory.call_args.kwargs["endpoint"]
        == "https://regional.azure-devices-provisioning.net"
    )


def test_only_idscope_and_credentials_use_global_endpoint_without_discovery(
    mocker,
):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    factory = mocker.patch.object(subject, "dps_device_service_factory")

    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        device_symmetric_key="device-key",
    )
    provider._get_client()

    discovery.assert_not_called()
    assert factory.call_args.kwargs["endpoint"] == (
        f"https://{IOTDPS_PROVISIONING_HOST}"
    )


def test_get_idscope_via_service_hostname(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {
        "entity": "mydps.azure-devices-provisioning.net"
    }
    discovery.return_value.get_id_scope.return_value = "scopeXYZ"
    mocker.patch.object(subject, "dps_device_service_factory")

    provider = DeviceRegistrationProvider(
        cmd=MagicMock(), registration_id="reg", dps_name="mydps"
    )

    assert provider.id_scope == "scopeXYZ"
    discovery.return_value.get_id_scope.assert_called_once_with(
        resource_name="mydps", rg=None
    )


def test_get_idscope_requires_resolvable_identifier(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {}

    with pytest.raises(RequiredArgumentMissingError, match="--id-scope"):
        DeviceRegistrationProvider(cmd=MagicMock(), registration_id="reg")


def test_symmetric_key_authentication_is_forwarded_to_factory(mocker):
    compute = mocker.patch.object(
        subject, "iot_dps_compute_device_key", return_value="computed-key"
    )
    factory = mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        enrollment_group_id="group",
        device_symmetric_key="group-key",
        compute_key=True,
    )

    assert provider._get_client() is factory.return_value
    compute.assert_called_once_with(
        cmd=provider.cmd,
        registration_id="reg",
        enrollment_id="group",
        symmetric_key="group-key",
        dps_name=None,
        resource_group_name=None,
        login=None,
        auth_type_dataplane=None,
    )
    assert factory.call_args.kwargs["device_symmetric_key"] == "computed-key"


def test_x509_authentication_is_forwarded_to_factory(mocker):
    factory = mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        certificate_file="device-cert.pem",
        key_file="device-key.pem",
        passphrase="not-logged",
    )

    provider._get_client()

    kwargs = factory.call_args.kwargs
    assert kwargs["certificate_file"] == "device-cert.pem"
    assert kwargs["key_file"] == "device-key.pem"
    assert kwargs["passphrase"] == "not-logged"
    assert kwargs["device_symmetric_key"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"compute_key": True},
        {"certificate_file": "device-cert.pem"},
        {"key_file": "device-key.pem"},
        {"passphrase": "secret"},
    ],
)
def test_attestation_validation_rejects_incomplete_inputs(kwargs):
    with pytest.raises(RequiredArgumentMissingError):
        provider = DeviceRegistrationProvider(
            cmd=MagicMock(),
            registration_id="reg",
            id_scope="scope",
            **kwargs,
        )
        provider._get_client()


def test_internal_x509_guard_remains_fail_closed():
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        device_symmetric_key="key",
    )

    with pytest.raises(RequiredArgumentMissingError, match="Both certificate"):
        provider._validate_attestation_params(  # pylint: disable=protected-access
            certificate_file="cert.pem"
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "device_symmetric_key": "symmetric",
            "certificate_file": "cert.pem",
            "key_file": "key.pem",
        },
        {
            "compute_key": True,
            "enrollment_group_id": "group",
            "certificate_file": "cert.pem",
            "key_file": "key.pem",
        },
        {
            "device_symmetric_key": "symmetric",
            "passphrase": "not-logged",
        },
    ],
)
def test_mixed_auth_is_rejected_before_discovery_or_secret_lookup(
    mocker, kwargs
):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    compute = mocker.patch.object(subject, "iot_dps_compute_device_key")
    enrollment = mocker.patch.object(
        subject, "iot_dps_device_enrollment_get"
    )

    with pytest.raises(MutuallyExclusiveArgumentError, match="cannot be combined"):
        DeviceRegistrationProvider(
            cmd=MagicMock(),
            registration_id="reg",
            id_scope="scope",
            dps_name="dps",
            **kwargs,
        )

    discovery.assert_not_called()
    compute.assert_not_called()
    enrollment.assert_not_called()


def test_compute_key_accepts_group_retrieval_shape_but_rejects_empty_key(
    mocker,
):
    mocker.patch.object(subject, "DPSDiscovery").return_value.get_target.return_value = {
        "idscope": "scope",
        "deviceHostName": "regional.example.test",
    }
    DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        dps_name="dps",
        enrollment_group_id="group",
        compute_key=True,
    )

    with pytest.raises(InvalidArgumentValueError, match="cannot be empty"):
        DeviceRegistrationProvider(
            cmd=MagicMock(),
            registration_id="reg",
            id_scope="scope",
            device_symmetric_key="",
        )


def test_attestation_is_retrieved_for_individual_enrollment(mocker):
    mocker.patch.object(subject, "DPSDiscovery").return_value.get_target.return_value = {
        "idscope": "scope",
        "deviceHostName": "regional.example.test",
    }
    mocker.patch.object(
        subject,
        "iot_dps_device_enrollment_get",
        return_value={
            "attestation": {
                "type": "symmetricKey",
                "symmetricKey": {"primaryKey": "retrieved-key"},
            }
        },
    )
    factory = mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        dps_name="dps",
    )

    provider._get_client()

    assert factory.call_args.kwargs["device_symmetric_key"] == "retrieved-key"


def test_individual_attestation_reloads_plaintext_key(mocker):
    mocker.patch.object(subject, "DPSDiscovery").return_value.get_target.return_value = {
        "idscope": "scope",
        "deviceHostName": "regional.example.test",
    }
    enrollment_get = mocker.patch.object(
        subject,
        "iot_dps_device_enrollment_get",
        side_effect=[
            {"attestation": {"type": "symmetricKey"}},
            {
                "attestation": {
                    "type": "symmetricKey",
                    "symmetricKey": {"primaryKey": "retrieved-key"},
                }
            },
        ],
    )
    mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        dps_name="dps",
    )

    provider._get_client()

    assert enrollment_get.call_count == 2
    assert enrollment_get.call_args.kwargs["show_keys"] is True


def test_operation_requires_authentication_when_dps_cannot_be_queried():
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(), registration_id="reg", id_scope="scope"
    )

    with pytest.raises(
        RequiredArgumentMissingError, match="Cannot retrieve device"
    ):
        provider.operation_status("operation")


def test_attestation_is_retrieved_and_computed_for_enrollment_group(mocker):
    mocker.patch.object(subject, "DPSDiscovery").return_value.get_target.return_value = {
        "idscope": "scope",
        "deviceHostName": "regional.example.test",
    }
    mocker.patch.object(
        subject,
        "iot_dps_device_enrollment_group_get",
        return_value={"attestation": {"type": "symmetricKey"}},
    )
    compute = mocker.patch.object(
        subject, "iot_dps_compute_device_key", return_value="group-device-key"
    )
    factory = mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        dps_name="dps",
        enrollment_group_id="group",
    )

    provider._get_client()

    assert factory.call_args.kwargs[
        "device_symmetric_key"
    ] == "group-device-key"
    compute.assert_called_once()


@pytest.mark.parametrize(
    "group,attestation_type,error",
    [
        (False, "x509", "certificate"),
        (True, "x509", "certificate"),
        (False, "tpm", "TPM"),
        (True, "tpm", "TPM"),
    ],
)
def test_unsupported_retrieved_attestation_requires_explicit_material(
    mocker, group, attestation_type, error
):
    mocker.patch.object(subject, "DPSDiscovery").return_value.get_target.return_value = {
        "idscope": "scope",
        "deviceHostName": "regional.example.test",
    }
    operation = (
        "iot_dps_device_enrollment_group_get"
        if group
        else "iot_dps_device_enrollment_get"
    )
    mocker.patch.object(
        subject,
        operation,
        return_value={"attestation": {"type": attestation_type}},
    )
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(),
        registration_id="reg",
        id_scope="scope",
        dps_name="dps",
        enrollment_group_id="group" if group else None,
    )

    with pytest.raises(InvalidArgumentValueError, match=error):
        provider._get_client()


def test_parse_body_accepts_mapping_inline_json_and_file(mocker):
    assert _parse_body({"value": 1}, "--body") == {"value": 1}
    assert _parse_body(None, "--body") == {}
    parse = mocker.patch.object(
        subject, "process_json_arg", return_value={"from": "file"}
    )
    assert _parse_body("request.json", "--body") == {"from": "file"}
    parse.assert_called_once_with("request.json", "--body")


def test_parse_body_rejects_invalid_or_non_object(mocker):
    mocker.patch.object(
        subject, "process_json_arg", side_effect=ValueError("bad")
    )
    with pytest.raises(InvalidArgumentValueError, match="JSON object"):
        _parse_body("bad", "--body")

    subject.process_json_arg.side_effect = None
    subject.process_json_arg.return_value = []
    with pytest.raises(InvalidArgumentValueError, match="JSON object"):
        _parse_body("[]", "--body")


@pytest.fixture
def valid_csr():
    import base64
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID

    request = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reg")])
    ).sign(ec.generate_private_key(ec.SECP256R1()), hashes.SHA256())
    return request.public_bytes(Encoding.PEM).decode(), base64.b64encode(request.public_bytes(Encoding.DER)).decode()


def test_create_uses_register_and_issue_certificate_contract(mocker, valid_csr):
    provider, _ = _provider()
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = {
        "operationId": "operation",
        "status": "assigned",
        "registrationState": {
            "registrationId": "reg",
            "deviceId": "registry-external-id",
            "connectionProfile": "MqttV5",
            "issuedCertificateChain": ["certificate"],
        },
    }
    mocker.patch.object(subject, "read_file_content", return_value=valid_csr[0])
    mocker.patch.object(
        subject, "process_json_arg", return_value={"site": "factory"}
    )

    result = provider.create(
        csr="device.csr",
        payload="payload.json",
        endorsement_key="endorsement",
        storage_root_key="storage",
    )

    operation = (
        provider.client.runtime_registration
        .register_device_and_issue_certificate
    )
    # Generated operation methods are MagicMocks on this test client.
    # pylint: disable=no-member
    operation.assert_called_once_with(
        registration_id="reg",
        id_scope="scope",
        device_registration={
            "registrationId": "reg",
            "csr": valid_csr[1],
            "payload": {"site": "factory"},
            "tpm": {
                "endorsementKey": "endorsement",
                "storageRootKey": "storage",
            },
        },
        cls=subject._capture_device_response,
    )
    state = result["registrationState"]
    assert state["connectionProfile"] == "MqttV5"
    assert state["issuedCertificateChain"] == ["certificate"]
    assert state["registryDeviceExternalId"] == "reg"


def test_create_accepts_inline_csr_and_correlates_registration_id(valid_csr):
    provider, _ = _provider()
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = {
        "registrationState": {}
    }

    inline_csr = valid_csr[0]
    result = provider.create(csr=inline_csr)

    operation = (
        provider.client.runtime_registration
        .register_device_and_issue_certificate
    )
    # pylint: disable=no-member
    body = operation.call_args.kwargs["device_registration"]
    assert body["csr"] == valid_csr[1]
    assert result["registrationState"]["registryDeviceExternalId"] == "reg"


def test_csr_plain_path_is_read_and_unreadable_error_is_sanitized(mocker):
    assert _read_csr_argument(__file__).startswith("# coding=utf-8")

    read = mocker.patch.object(
        subject,
        "read_file_content",
        side_effect=PermissionError("PRIVATE KEY CONTENT"),
    )
    supplied = "not-inline-secret-certificate-content"
    with pytest.raises(InvalidArgumentValueError) as raised:
        _read_csr_argument(supplied)

    read.assert_called_once_with(supplied)
    message = str(raised.value)
    assert supplied not in message
    assert "PRIVATE KEY CONTENT" not in message
    assert "--csr file" in message
    assert raised.value.__cause__ is None

    with pytest.raises(InvalidArgumentValueError, match="inline PEM"):
        _read_csr_argument(b"certificate bytes")


@pytest.mark.parametrize(
    "endorsement, storage",
    [("endorsement", None), (None, "storage")],
)
def test_create_requires_complete_tpm_material(endorsement, storage):
    provider, _ = _provider()
    with pytest.raises(RequiredArgumentMissingError, match="provided together"):
        provider.create(
            endorsement_key=endorsement, storage_root_key=storage
        )


def test_tpm_only_has_explicit_unsupported_diagnostic_before_network(mocker):
    factory = mocker.patch.object(subject, "dps_device_service_factory")
    provider = DeviceRegistrationProvider(
        cmd=MagicMock(), registration_id="reg", id_scope="scope"
    )

    with pytest.raises(InvalidArgumentValueError, match="TPM-only"):
        provider.create(
            endorsement_key="endorsement",
            storage_root_key="storage",
        )

    factory.assert_not_called()


def test_accepted_registration_polls_to_200_and_honors_retry_after():
    now = [0]
    sleeps = []

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    provider, _ = _provider(
        clock=lambda: now[0],
        sleeper=sleeper,
        registration_timeout=30,
    )
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(
            202,
            {"operationId": "operation", "status": "assigning"},
            {"rEtRy-AfTeR": "3"},
        )
    )
    provider.client.runtime_registration.operation_status_lookup_preview.side_effect = [
        subject._DeviceResponse(
            202,
            {"operationId": "operation", "status": "assigning"},
            {"RETRY-AFTER": "5"},
        ),
        subject._DeviceResponse(
            200,
            {
                "operationId": "operation",
                "status": "assigned",
                "registrationState": {"registrationId": "reg"},
            },
            {},
        ),
    ]

    result = provider.create()

    assert result["status"] == "assigned"
    assert result["registrationState"]["registryDeviceExternalId"] == "reg"
    assert sleeps == [3, 5]
    # Generated operation methods are replaced with MagicMocks in this test.
    # pylint: disable=no-member
    assert (
        provider.client.runtime_registration
        .operation_status_lookup_preview.call_count
        == 2
    )


def _set_registration_result(provider, result, polled):
    if polled:
        provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
            subject._DeviceResponse(
                202,
                {"operationId": "operation", "status": "assigning"},
                {"Retry-After": "1"},
            )
        )
        provider.client.runtime_registration.operation_status_lookup_preview.return_value = (
            subject._DeviceResponse(200, result, {})
        )
    else:
        provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
            subject._DeviceResponse(200, result, {})
        )


@pytest.mark.parametrize("polled", [False, True], ids=["direct", "polled"])
@pytest.mark.parametrize(
    "status_location,status",
    [("top", "FaIlEd"), ("nested", "FAILED")],
)
def test_create_rejects_failed_registration_with_sanitized_details(
    polled, status_location, status
):
    provider, _ = _provider(sleeper=lambda _: None)
    result = {
        "status": "assigned",
        "errorCode": "TopLevelFallback",
        "registrationState": {
            "status": "assigned",
            "errorCode": 401,
            "errorMessage": "Denied\r\nwithout\x1b terminal control",
            "deviceKey": "must-not-be-exposed",
        },
    }
    target = result if status_location == "top" else result["registrationState"]
    target["status"] = status
    _set_registration_result(provider, result, polled)

    with pytest.raises(AzureResponseError) as raised:
        provider.create()

    message = str(raised.value)
    assert FAILED_REGISTRATION_ERROR in message
    assert "errorCode: 401" in message
    assert "errorMessage: Denied without terminal control" in message
    assert "\r" not in message
    assert "\n" not in message
    assert "\x1b" not in message
    assert "must-not-be-exposed" not in message


@pytest.mark.parametrize("polled", [False, True], ids=["direct", "polled"])
@pytest.mark.parametrize(
    "status_location,status",
    [("top", "DiSaBlEd"), ("nested", "DISABLED")],
)
def test_create_rejects_disabled_registration(
    polled, status_location, status
):
    provider, _ = _provider(sleeper=lambda _: None)
    result = {
        "status": "failed" if status_location == "nested" else "assigning",
        "registrationState": {"status": "assigning"},
    }
    target = result if status_location == "top" else result["registrationState"]
    target["status"] = status
    _set_registration_result(provider, result, polled)

    with pytest.raises(AzureResponseError) as raised:
        provider.create()

    assert str(raised.value) == DISABLED_REGISTRATION_ERROR


def test_create_failed_registration_without_detail_uses_shared_error():
    provider, _ = _provider()
    _set_registration_result(
        provider,
        {"status": "failed", "registrationState": {}},
        polled=False,
    )

    with pytest.raises(AzureResponseError) as raised:
        provider.create()

    assert str(raised.value) == FAILED_REGISTRATION_ERROR


@pytest.mark.parametrize("polled", [False, True], ids=["direct", "polled"])
@pytest.mark.parametrize("status_location", ["top", "nested"])
def test_create_preserves_successful_registration(polled, status_location):
    provider, _ = _provider(sleeper=lambda _: None)
    result = {
        "status": "assigning",
        "registrationState": {"registrationId": "reg"},
    }
    target = result if status_location == "top" else result["registrationState"]
    target["status"] = "AsSiGnEd"
    _set_registration_result(provider, result, polled)

    response = provider.create()

    assert response is result
    assert response["registrationState"]["registryDeviceExternalId"] == "reg"


def test_registration_wait_retries_throttled_status_read():
    now = [0]

    def sleeper(delay):
        now[0] += delay

    provider, _ = _provider(
        clock=lambda: now[0],
        sleeper=sleeper,
        registration_timeout=30,
    )
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(
            202, {"operationId": "operation"}, {"Retry-After": "1"}
        )
    )
    throttled = _http_error(429)
    throttled.response.headers = {"retry-after": "2"}
    provider.client.runtime_registration.operation_status_lookup_preview.side_effect = [
        throttled,
        subject._DeviceResponse(
            200, {"operationId": "operation", "status": "assigned"}, {}
        ),
    ]

    assert provider.create()["status"] == "assigned"
    assert now[0] == 3


def test_registration_wait_times_out_with_safe_status_guidance():
    now = [0]
    sleeps = []

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    provider, _ = _provider(
        clock=lambda: now[0],
        sleeper=sleeper,
        registration_timeout=5,
    )
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(
            202, {"operationId": "operation"}, {"Retry-After": "30"}
        )
    )

    with pytest.raises(AzureResponseError, match="operation-status") as raised:
        provider.create()

    assert "may still complete" in str(raised.value)
    assert sleeps == [5]
    # pylint: disable=no-member
    provider.client.runtime_registration.operation_status_lookup_preview.assert_not_called()


def test_registration_wait_handles_preexpired_deadline():
    provider, _ = _provider(registration_timeout=0)
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(
            202, {"operationId": "operation"}, {"Retry-After": "1"}
        )
    )

    with pytest.raises(AzureResponseError, match="operation-status"):
        provider.create()

    # pylint: disable=no-member
    provider.client.runtime_registration.operation_status_lookup_preview.assert_not_called()


def test_registration_wait_translates_nontransient_status_error(mocker):
    provider, _ = _provider(
        sleeper=lambda _: None,
        registration_timeout=30,
    )
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(
            202, {"operationId": "operation"}, {"Retry-After": "1"}
        )
    )
    provider.client.runtime_registration.operation_status_lookup_preview.side_effect = (
        _http_error(400)
    )
    translate = mocker.patch.object(
        subject,
        "handle_service_exception",
        return_value={"translated": True},
    )

    assert provider.create() == {"translated": True}
    translate.assert_called_once()


def test_accepted_registration_requires_operation_id():
    provider, _ = _provider()
    provider.client.runtime_registration.register_device_and_issue_certificate.return_value = (
        subject._DeviceResponse(202, {}, {})
    )

    with pytest.raises(AzureResponseError, match="operation ID"):
        provider.create()


def test_registration_and_operation_errors_use_shared_translation(mocker):
    provider, _ = _provider()
    translate = mocker.patch.object(
        subject, "handle_service_exception", return_value={"translated": True}
    )
    provider.client.runtime_registration.register_device_and_issue_certificate.side_effect = _http_error()
    assert provider.create() == {"translated": True}
    provider.client.runtime_registration.operation_status_lookup_preview.side_effect = _http_error(
        404
    )
    assert provider.operation_status("operation") == {"translated": True}
    assert translate.call_count == 2


def test_operation_status_calls_generated_group():
    provider, _ = _provider()
    terminal_result = {
        "status": "FaIlEd",
        "registrationState": {
            "status": "disabled",
            "errorMessage": "returned for explicit inspection",
        },
    }
    provider.client.runtime_registration.operation_status_lookup_preview.return_value = (
        terminal_result
    )

    assert provider.operation_status("operation") is terminal_result
    provider.client.runtime_registration.operation_status_lookup_preview.assert_called_once_with(  # pylint: disable=no-member
        registration_id="reg",
        operation_id="operation",
        id_scope="scope",
        cls=subject._capture_device_response,
    )


def test_device_registration_commands_delegate_new_contract():
    cmd = MagicMock()
    with patch.object(commands, "DeviceRegistrationProvider") as provider_type:
        provider = provider_type.return_value
        commands.create_device_registration(
            cmd,
            "reg",
            enrollment_group_id="group",
            device_symmetric_key="key",
            compute_key=True,
            certificate_file="cert.pem",
            key_file="key.pem",
            passphrase="passphrase",
            csr="csr",
            payload={"value": 1},
            endorsement_key="ek",
            storage_root_key="srk",
            id_scope="scope",
            provisioning_host="host",
        )
        commands.show_device_registration_operation(
            cmd, "reg", "operation", id_scope="scope",
            device_symmetric_key="key"
        )

    assert provider_type.call_count == 2
    assert all(
        call.kwargs["device_symmetric_key"] == "key"
        for call in provider_type.call_args_list
    )
    create_kwargs = provider_type.call_args_list[0].kwargs
    assert create_kwargs["enrollment_group_id"] == "group"
    assert create_kwargs["compute_key"] is True
    assert create_kwargs["certificate_file"] == "cert.pem"
    assert create_kwargs["key_file"] == "key.pem"
    assert create_kwargs["passphrase"] == "passphrase"
    provider.create.assert_called_once_with(
        csr="csr",
        payload={"value": 1},
        endorsement_key="ek",
        storage_root_key="srk",
    )
    provider.operation_status.assert_called_once_with("operation")


def test_device_update_actions_are_not_exposed_by_handwritten_cli_layers():
    for method_name in (
        "request_software_updates",
        "request_onboarding_updates",
        "report_update_status",
    ):
        assert not hasattr(DeviceRegistrationProvider, method_name)
    for wrapper_name in (
        "request_device_software_updates",
        "request_device_onboarding_updates",
        "report_device_update_status",
    ):
        assert not hasattr(commands, wrapper_name)
