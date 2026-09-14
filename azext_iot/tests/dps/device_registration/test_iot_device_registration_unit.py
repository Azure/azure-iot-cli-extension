# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import MagicMock

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    AzureResponseError,
    AzureConnectionError,
    UnauthorizedError,
)

import azext_iot.dps.providers.device_registration as subject
from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider
from azext_iot.dps.common import (
    DISABLED_REGISTRATION_ERROR,
    FAILED_REGISTRATION_ERROR,
    UNAUTHORIZED_ERROR,
)


def _provider(id_scope="scope", **kwargs):
    return DeviceRegistrationProvider(
        cmd=MagicMock(), registration_id="reg", id_scope=id_scope, **kwargs
    )


# ---------------------------------------------------------------------------
# __init__ / _get_idscope
# ---------------------------------------------------------------------------


def test_init_with_id_scope():
    provider = _provider()
    assert provider.id_scope == "scope"
    assert provider.registration_id == "reg"


def test_get_idscope_from_target(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {"idscope": "scopeABC"}
    provider = DeviceRegistrationProvider(cmd=MagicMock(), registration_id="reg", dps_name="mydps")
    assert provider.id_scope == "scopeABC"


def test_get_idscope_via_cstring(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery")
    discovery.return_value.get_target.return_value = {"entity": "mydps.azure-devices.net"}
    discovery.return_value.get_id_scope.return_value = "scopeXYZ"
    provider = DeviceRegistrationProvider(cmd=MagicMock(), registration_id="reg", dps_name="mydps")
    assert provider.id_scope == "scopeXYZ"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def _registration_result():
    result = MagicMock()
    result.operation_id = "op"
    result.status = "assigned"
    state = result.registration_state
    state.device_id = "dev"
    state.assigned_hub = "hub"
    state.sub_status = "initialAssignment"
    state.created_date_time = "created"
    state.last_update_date_time = "updated"
    state.etag = "etag"
    state.response_payload = {"a": "b"}
    return result


def test_create_success(mocker):
    provider = _provider()
    mocker.patch.object(provider, "_validate_attestation_params")
    sdk = MagicMock()
    sdk.register.return_value = _registration_result()
    mocker.patch.object(provider, "_get_dps_device_sdk", return_value=sdk)

    result = provider.create(payload="{}")

    assert result["operationId"] == "op"
    assert result["status"] == "assigned"
    assert result["registrationState"]["deviceId"] == "dev"
    assert result["registrationState"]["assignedHub"] == "hub"
    assert sdk.provisioning_payload == "{}"


def test_create_handles_exception(mocker):
    from azure.iot.device.exceptions import ClientError

    provider = _provider()
    mocker.patch.object(provider, "_validate_attestation_params")
    sdk = MagicMock()
    sdk.register.side_effect = ClientError("fail")
    mocker.patch.object(provider, "_get_dps_device_sdk", return_value=sdk)
    mocker.patch.object(provider, "_handle_exception", return_value=ValueError("mapped"))

    with pytest.raises(ValueError):
        provider.create(enrollment_group_id="group")


# ---------------------------------------------------------------------------
# _validate_attestation_params
# ---------------------------------------------------------------------------


def test_validate_compute_key_missing_args():
    provider = _provider()
    with pytest.raises(RequiredArgumentMissingError):
        provider._validate_attestation_params(compute_key=True)


def test_validate_symmetric_key_no_compute():
    provider = _provider()
    provider._validate_attestation_params(device_symmetric_key="key")
    assert provider.device_symmetric_key == "key"
    assert provider.certificate is None


def test_validate_symmetric_key_with_compute(mocker):
    provider = _provider()
    compute = mocker.patch.object(subject, "iot_dps_compute_device_key", return_value="computed")
    provider._validate_attestation_params(
        device_symmetric_key="key", compute_key=True, enrollment_group_id="group"
    )
    assert provider.device_symmetric_key == "computed"
    compute.assert_called_once()


def test_validate_certificate(mocker):
    provider = _provider()
    x509 = mocker.patch("azure.iot.device.X509")
    provider._validate_attestation_params(certificate_file="cert.pem", key_file="key.pem")
    assert provider.certificate is x509.return_value


def test_validate_missing_credentials():
    provider = _provider()
    provider.dps_name = None
    provider.login = None
    with pytest.raises(RequiredArgumentMissingError):
        provider._validate_attestation_params()


def test_validate_retrieves_attestation(mocker):
    provider = _provider(dps_name="mydps")
    get_attest = mocker.patch.object(provider, "_get_attestation_params")
    provider._validate_attestation_params()
    get_attest.assert_called_once()


# ---------------------------------------------------------------------------
# _get_dps_device_sdk
# ---------------------------------------------------------------------------


def test_get_sdk_symmetric_key(mocker):
    provider = _provider()
    provider.device_symmetric_key = "key"
    provider.certificate = None
    pdc = mocker.patch("azure.iot.device.ProvisioningDeviceClient")
    result = provider._get_dps_device_sdk()
    assert result is pdc.create_from_symmetric_key.return_value


def test_get_sdk_certificate(mocker):
    provider = _provider()
    provider.device_symmetric_key = None
    provider.certificate = MagicMock()
    pdc = mocker.patch("azure.iot.device.ProvisioningDeviceClient")
    result = provider._get_dps_device_sdk()
    assert result is pdc.create_from_x509_certificate.return_value


def test_get_sdk_certificate_ssl_error(mocker):
    from ssl import SSLError

    provider = _provider()
    provider.device_symmetric_key = None
    provider.certificate = MagicMock()
    pdc = mocker.patch("azure.iot.device.ProvisioningDeviceClient")
    pdc.create_from_x509_certificate.side_effect = SSLError("bad cert")
    with pytest.raises(InvalidArgumentValueError):
        provider._get_dps_device_sdk()


def test_get_sdk_tpm_unsupported():
    provider = _provider()
    provider.device_symmetric_key = None
    provider.certificate = None
    with pytest.raises(InvalidArgumentValueError):
        provider._get_dps_device_sdk()


# ---------------------------------------------------------------------------
# _get_attestation_params
# ---------------------------------------------------------------------------


def test_get_attestation_group_symmetric(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_group_get",
        return_value={"attestation": {"type": "symmetricKey"}},
    )
    compute = mocker.patch.object(subject, "iot_dps_compute_device_key", return_value="gkey")
    provider._get_attestation_params(enrollment_group_id="group")
    assert provider.device_symmetric_key == "gkey"
    compute.assert_called_once()


def test_get_attestation_group_x509(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_group_get",
        return_value={"attestation": {"type": "x509"}},
    )
    with pytest.raises(InvalidArgumentValueError):
        provider._get_attestation_params(enrollment_group_id="group")


def test_get_attestation_group_tpm(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_group_get",
        return_value={"attestation": {"type": "tpm"}},
    )
    with pytest.raises(InvalidArgumentValueError):
        provider._get_attestation_params(enrollment_group_id="group")


def test_get_attestation_individual_symmetric(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_get",
        return_value={"attestation": {"type": "symmetricKey", "symmetricKey": {"primaryKey": "ikey"}}},
    )
    provider._get_attestation_params()
    assert provider.device_symmetric_key == "ikey"


def test_get_attestation_individual_x509(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_get",
        return_value={"attestation": {"type": "x509"}},
    )
    with pytest.raises(InvalidArgumentValueError):
        provider._get_attestation_params()


def test_get_attestation_individual_tpm(mocker):
    provider = _provider(dps_name="mydps")
    mocker.patch.object(
        subject, "iot_dps_device_enrollment_get",
        return_value={"attestation": {"type": "tpm"}},
    )
    with pytest.raises(InvalidArgumentValueError):
        provider._get_attestation_params()


# ---------------------------------------------------------------------------
# _handle_exception
# ---------------------------------------------------------------------------


def test_handle_credential_error():
    from azure.iot.device.exceptions import CredentialError

    provider = _provider()
    result = provider._handle_exception(CredentialError("x"))
    assert isinstance(result, UnauthorizedError)


def test_handle_connection_failed():
    from azure.iot.device.exceptions import ConnectionFailedError

    provider = _provider()
    assert isinstance(provider._handle_exception(ConnectionFailedError("x")), AzureConnectionError)


def test_handle_connection_dropped():
    from azure.iot.device.exceptions import ConnectionDroppedError

    provider = _provider()
    assert isinstance(provider._handle_exception(ConnectionDroppedError("x")), AzureConnectionError)


def test_handle_operation_timeout():
    from azure.iot.device.exceptions import OperationTimeout

    provider = _provider()
    assert isinstance(provider._handle_exception(OperationTimeout("x")), AzureConnectionError)


def _client_error_with_cause(cause_message):
    from azure.iot.device.exceptions import ClientError

    error = ClientError("client")
    error.__cause__ = Exception(cause_message)
    return error


def test_handle_client_error_disabled():
    provider = _provider()
    result = provider._handle_exception(_client_error_with_cause(DISABLED_REGISTRATION_ERROR))
    assert isinstance(result, AzureResponseError)
    assert "disabled" in str(result)


def test_handle_client_error_failed():
    provider = _provider()
    result = provider._handle_exception(_client_error_with_cause(FAILED_REGISTRATION_ERROR), is_group=True)
    assert isinstance(result, AzureResponseError)
    assert "enrollment-group" in str(result)


def test_handle_client_error_unauthorized():
    provider = _provider()
    result = provider._handle_exception(_client_error_with_cause(UNAUTHORIZED_ERROR))
    assert isinstance(result, UnauthorizedError)


def test_handle_client_error_other():
    provider = _provider()
    result = provider._handle_exception(_client_error_with_cause("some other failure"))
    assert isinstance(result, AzureResponseError)


def test_handle_unknown_error():
    provider = _provider()
    original = ValueError("unexpected")
    assert provider._handle_exception(original) is original


# ---------------------------------------------------------------------------
# command wrapper
# ---------------------------------------------------------------------------


def test_create_device_registration_command(mocker):
    from azext_iot.dps.services.auth import get_dps_sas_auth_header  # noqa: F401  (ensure module importable)
    from azext_iot.dps.commands_device_registration import create_device_registration

    provider = mocker.patch(
        "azext_iot.dps.commands_device_registration.DeviceRegistrationProvider"
    )
    create_device_registration(
        cmd=MagicMock(),
        registration_id="reg",
        enrollment_group_id="group",
        device_symmetric_key="key",
        id_scope="scope",
    )
    provider.assert_called_once()
    provider.return_value.create.assert_called_once()
