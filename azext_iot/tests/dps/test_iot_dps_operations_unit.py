# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
import pytest
from unittest.mock import MagicMock

from azure.cli.core.azclierror import (
    RequiredArgumentMissingError,
    InvalidArgumentValueError,
    ArgumentUsageError,
    MutuallyExclusiveArgumentError,
    BadRequestError,
    AzureResponseError,
)

import azext_iot.operations.dps as subject
from azext_iot.common.shared import AttestationType, ReprovisionType, AllocationType


# ---------------------------------------------------------------------------
# _get_reprovision_policy
# ---------------------------------------------------------------------------


def test_reprovision_migrate():
    policy = subject._get_reprovision_policy(ReprovisionType.reprovisionandmigratedata.value)
    assert policy.update_hub_assignment is True
    assert policy.migrate_device_data is True


def test_reprovision_reset():
    policy = subject._get_reprovision_policy(ReprovisionType.reprovisionandresetdata.value)
    assert policy.update_hub_assignment is True
    assert policy.migrate_device_data is False


def test_reprovision_never():
    policy = subject._get_reprovision_policy(ReprovisionType.never.value)
    assert policy.update_hub_assignment is False
    assert policy.migrate_device_data is False


def test_reprovision_invalid():
    with pytest.raises(InvalidArgumentValueError):
        subject._get_reprovision_policy("bogus")


def test_reprovision_default():
    policy = subject._get_reprovision_policy(None)
    assert policy.update_hub_assignment is True
    assert policy.migrate_device_data is True


# ---------------------------------------------------------------------------
# _get_twin_collection / _get_initial_twin
# ---------------------------------------------------------------------------


def test_twin_collection_empty_string():
    result = subject._get_twin_collection("")
    assert result.additional_properties is None


def test_twin_collection_none():
    result = subject._get_twin_collection(None)
    assert result.additional_properties is None


def test_twin_collection_dict():
    result = subject._get_twin_collection('{"key": "value"}')
    assert result.additional_properties == {"key": "value"}


def test_get_initial_twin():
    twin = subject._get_initial_twin(initial_twin_tags='{"t": 1}', initial_twin_properties='{"p": 2}')
    assert twin.tags.additional_properties == {"t": 1}
    assert twin.properties.desired.additional_properties == {"p": 2}


def test_get_updated_initial_twin_from_record():
    record = MagicMock()
    record.initial_twin.tags.as_dict.return_value = {"t": 1}
    record.initial_twin.properties.desired.as_dict.return_value = {"p": 2}
    twin = subject._get_updated_inital_twin(record)
    assert twin.tags.additional_properties == {"t": 1}
    assert twin.properties.desired.additional_properties == {"p": 2}


# ---------------------------------------------------------------------------
# x509 attestation helpers
# ---------------------------------------------------------------------------


def test_attestation_x509_client_cert_missing_paths():
    with pytest.raises(RequiredArgumentMissingError):
        subject._get_attestation_with_x509_client_cert(None, None)


def test_attestation_x509_client_cert(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="CERT")
    attestation = subject._get_attestation_with_x509_client_cert("primary.pem", None)
    assert attestation.type == AttestationType.x509.value
    assert attestation.x509.client_certificates.primary.certificate == "CERT"


def test_attestation_x509_signing_cert(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="CERT")
    attestation = subject._get_attestation_with_x509_signing_cert("primary.pem", None)
    assert attestation.x509.signing_certificates.primary.certificate == "CERT"


def test_attestation_x509_ca_cert():
    attestation = subject._get_attestation_with_x509_ca_cert("rootca", None)
    assert attestation.x509.ca_references.primary == "rootca"


def test_updated_attestation_x509_client_cert(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="NEW")
    attestation = MagicMock()
    result = subject._get_updated_attestation_with_x509_client_cert(
        attestation,
        primary_certificate_path="p.pem",
        secondary_certificate_path="s.pem",
        remove_primary_certificate=False,
        remove_secondary_certificate=False,
    )
    assert result.x509.client_certificates.primary.certificate == "NEW"


# ---------------------------------------------------------------------------
# _can_remove_primary/secondary_certificate
# ---------------------------------------------------------------------------


def test_can_remove_primary_certificate_no_remove():
    assert subject._can_remove_primary_certificate(False, MagicMock()) is True


def test_can_remove_primary_certificate_signing_no_secondary():
    attestation = MagicMock()
    attestation.x509.signing_certificates.secondary = None
    # ca_references absent
    del attestation.x509.ca_references
    assert subject._can_remove_primary_certificate(True, attestation) is False


def test_can_remove_secondary_certificate_signing_no_primary():
    attestation = MagicMock()
    attestation.x509.signing_certificates.primary = None
    del attestation.x509.ca_references
    assert subject._can_remove_secondary_certificate(True, attestation) is False


def test_can_remove_primary_certificate_ca_no_secondary():
    attestation = MagicMock()
    del attestation.x509.signing_certificates
    attestation.x509.ca_references.secondary = None
    assert subject._can_remove_primary_certificate(True, attestation) is False


def test_can_remove_secondary_certificate_ca_no_primary():
    attestation = MagicMock()
    del attestation.x509.signing_certificates
    attestation.x509.ca_references.primary = None
    assert subject._can_remove_secondary_certificate(True, attestation) is False


def test_updated_attestation_x509_signing_cert(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="NEW")
    attestation = MagicMock()
    result = subject._get_updated_attestation_with_x509_signing_cert(
        attestation,
        primary_certificate_path="p.pem",
        secondary_certificate_path="s.pem",
        remove_primary_certificate=True,
        remove_secondary_certificate=True,
    )
    assert result.x509.signing_certificates.primary.certificate == "NEW"


def test_updated_attestation_x509_signing_cert_no_existing(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="NEW")
    attestation = MagicMock()
    del attestation.x509.signing_certificates
    result = subject._get_updated_attestation_with_x509_signing_cert(
        attestation,
        primary_certificate_path="p.pem",
        secondary_certificate_path=None,
        remove_primary_certificate=False,
        remove_secondary_certificate=False,
    )
    assert result.x509.signing_certificates.primary.certificate == "NEW"


def test_updated_attestation_x509_ca_cert():
    attestation = MagicMock()
    attestation.x509.ca_references = MagicMock()
    result = subject._get_updated_attestation_with_x509_ca_cert(
        attestation,
        root_ca_name="rootca",
        secondary_root_ca_name="secondca",
        remove_primary_certificate=True,
        remove_secondary_certificate=True,
    )
    assert result.x509.ca_references.primary == "rootca"
    assert result.x509.ca_references.secondary == "secondca"


def test_updated_attestation_x509_ca_cert_no_existing():
    attestation = MagicMock()
    attestation.x509.ca_references = None
    result = subject._get_updated_attestation_with_x509_ca_cert(
        attestation,
        root_ca_name="rootca",
        secondary_root_ca_name=None,
        remove_primary_certificate=False,
        remove_secondary_certificate=False,
    )
    assert result.x509.ca_references.primary == "rootca"


# ---------------------------------------------------------------------------
# _validate_arguments_for_attestation_mechanism
# ---------------------------------------------------------------------------


def test_validate_tpm_with_cert():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.tpm.value, None, "cert.pem", None, False, False, None, None
        )


def test_validate_tpm_with_remove():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.tpm.value, None, None, None, True, False, None, None
        )


def test_validate_tpm_with_key():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.tpm.value, None, None, None, False, False, "pk", None
        )


def test_validate_x509_with_endorsement():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.x509.value, "ek", None, None, False, False, None, None
        )


def test_validate_x509_with_key():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.x509.value, None, None, None, False, False, "pk", None
        )


def test_validate_symmetric_with_cert():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.symmetricKey.value, None, "cert.pem", None, False, False, None, None
        )


def test_validate_symmetric_with_remove():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.symmetricKey.value, None, None, None, True, False, None, None
        )


def test_validate_symmetric_with_endorsement():
    with pytest.raises(ArgumentUsageError):
        subject._validate_arguments_for_attestation_mechanism(
            AttestationType.symmetricKey.value, "ek", None, None, False, False, None, None
        )


def test_validate_symmetric_valid_noop():
    # No raise expected.
    subject._validate_arguments_for_attestation_mechanism(
        AttestationType.symmetricKey.value, None, None, None, False, False, "pk", "sk"
    )


# ---------------------------------------------------------------------------
# _validate_allocation_policy_for_enrollment
# ---------------------------------------------------------------------------


def test_allocation_policy_mutually_exclusive():
    with pytest.raises(MutuallyExclusiveArgumentError):
        subject._validate_allocation_policy_for_enrollment(
            AllocationType.static.value, "hub.host", None, None, None
        )


def test_allocation_policy_invalid():
    with pytest.raises(RequiredArgumentMissingError):
        subject._validate_allocation_policy_for_enrollment("bogus", None, ["hub"], None, None)


def test_allocation_policy_static_no_hub():
    with pytest.raises(RequiredArgumentMissingError):
        subject._validate_allocation_policy_for_enrollment(
            AllocationType.static.value, None, None, None, None
        )


def test_allocation_policy_static_multiple_hubs():
    with pytest.raises(InvalidArgumentValueError):
        subject._validate_allocation_policy_for_enrollment(
            AllocationType.static.value, None, ["hub1", "hub2"], None, None
        )


def test_allocation_policy_custom_missing_webhook():
    with pytest.raises(RequiredArgumentMissingError):
        subject._validate_allocation_policy_for_enrollment(
            AllocationType.custom.value, None, None, None, None
        )


def test_allocation_policy_static_valid():
    # No raise expected.
    subject._validate_allocation_policy_for_enrollment(
        AllocationType.static.value, None, ["hub1"], None, None
    )


def test_allocation_policy_hub_list_without_policy():
    with pytest.raises(RequiredArgumentMissingError):
        subject._validate_allocation_policy_for_enrollment(None, None, ["hub1"], None, None)


def test_allocation_policy_from_current_enrollment():
    current = MagicMock()
    current.iot_hubs = ["hub1"]
    current.allocation_policy = AllocationType.static.value
    # No raise expected; policy derived from current enrollment.
    subject._validate_allocation_policy_for_enrollment(
        None, None, None, None, None, current_enrollment=current
    )


# ---------------------------------------------------------------------------
# iot_dps_compute_device_key
# ---------------------------------------------------------------------------


def test_compute_device_key_symmetric_provided():
    key = base64.b64encode(b"secret").decode("utf-8")
    result = subject.iot_dps_compute_device_key(
        cmd=MagicMock(), registration_id="reg", symmetric_key=key
    )
    assert result


def test_compute_device_key_missing_args():
    with pytest.raises(RequiredArgumentMissingError):
        subject.iot_dps_compute_device_key(cmd=MagicMock(), registration_id="reg")


def test_compute_device_key_from_enrollment(mocker):
    key = base64.b64encode(b"secret").decode("utf-8")
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    sdk = resolver.return_value.get_sdk.return_value
    sdk.enrollment_group.get_attestation_mechanism.return_value.response.json.return_value = {
        "type": "symmetricKey",
        "symmetricKey": {"primaryKey": key},
    }
    result = subject.iot_dps_compute_device_key(
        cmd=MagicMock(), registration_id="reg", enrollment_id="grp", dps_name="dps"
    )
    assert result


def test_compute_device_key_wrong_attestation(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    sdk = resolver.return_value.get_sdk.return_value
    sdk.enrollment_group.get_attestation_mechanism.return_value.response.json.return_value = {
        "type": "tpm",
    }
    with pytest.raises(BadRequestError):
        subject.iot_dps_compute_device_key(
            cmd=MagicMock(), registration_id="reg", enrollment_id="grp", dps_name="dps"
        )


# ---------------------------------------------------------------------------
# iot_dps_connection_string_show
# ---------------------------------------------------------------------------


def test_connection_string_show_single(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.find_resource.return_value = {
        "name": "mydps",
        "resourcegroup": "rg",
        "properties": {"serviceOperationsHostName": "host"},
    }
    discovery.find_policy.return_value = {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}
    result = subject.iot_dps_connection_string_show(cmd=MagicMock(), dps_name="mydps")
    assert "connectionString" in result
    assert "pk" in result["connectionString"]


def test_connection_string_show_all_in_rg(mocker):
    from azext_iot.common.shared import IoTDPSStateType

    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.get_resources.return_value = [
        {
            "name": "active-dps",
            "resourcegroup": "rg",
            "properties": {"serviceOperationsHostName": "host", "state": IoTDPSStateType.Active.value},
        },
        {
            "name": "inactive-dps",
            "resourcegroup": "rg",
            "properties": {"serviceOperationsHostName": "host", "state": "Disabled"},
        },
    ]
    discovery.find_policy.return_value = {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}
    result = subject.iot_dps_connection_string_show(cmd=MagicMock())
    assert len(result) == 1
    assert result[0]["name"] == "active-dps"


def test_connection_string_show_none_found(mocker):
    from azure.cli.core.azclierror import ResourceNotFoundError

    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.get_resources.return_value = None
    with pytest.raises(ResourceNotFoundError):
        subject.iot_dps_connection_string_show(cmd=MagicMock())


# ---------------------------------------------------------------------------
# iot_dps_registration_* error paths
# ---------------------------------------------------------------------------


def test_registration_delete(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    sdk = resolver.return_value.get_sdk.return_value
    subject.iot_dps_registration_delete(cmd=MagicMock(), registration_id="reg", dps_name="dps")
    sdk.device_registration_state.delete.assert_called_once_with("reg", if_match="*")


def test_registration_get(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    sdk = resolver.return_value.get_sdk.return_value
    sdk.device_registration_state.get.return_value.response.json.return_value = {"registrationId": "reg"}
    result = subject.iot_dps_registration_get(cmd=MagicMock(), registration_id="reg", dps_name="dps")
    assert result == {"registrationId": "reg"}


# ---------------------------------------------------------------------------
# Command function helpers: SDK mocking + service-exception handling
# ---------------------------------------------------------------------------


def _svc_exc():
    """Build a ProvisioningServiceErrorDetailsException without invoking the
    (deserialize, response) constructor so it can be raised as a side effect."""
    return subject.ProvisioningServiceErrorDetailsException.__new__(
        subject.ProvisioningServiceErrorDetailsException
    )


@pytest.fixture
def dps_sdk(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    return resolver.return_value.get_sdk.return_value


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch.object(subject, "handle_service_exception")


# --- individual enrollment list/get error + warning paths -------------------


def test_enrollment_list_service_error(mocker, dps_sdk, handle_exc):
    mocker.patch.object(subject, "_execute_query", side_effect=_svc_exc())
    subject.iot_dps_device_enrollment_list(cmd=MagicMock(), dps_name="dps")
    handle_exc.assert_called_once()


def test_enrollment_get_show_keys_non_symmetric_warns(mocker, dps_sdk):
    warn = mocker.patch.object(subject.logger, "warning")
    dps_sdk.individual_enrollment.get.return_value.response.json.return_value = {
        "attestation": {"type": AttestationType.x509.value}
    }
    result = subject.iot_dps_device_enrollment_get(
        cmd=MagicMock(), enrollment_id="eid", dps_name="dps", show_keys=True
    )
    assert result["attestation"]["type"] == AttestationType.x509.value
    warn.assert_called_once()


def test_enrollment_get_service_error(dps_sdk, handle_exc):
    dps_sdk.individual_enrollment.get.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_get(cmd=MagicMock(), enrollment_id="eid", dps_name="dps")
    handle_exc.assert_called_once()


# --- individual enrollment update branches ----------------------------------


def _update_record(attestation_type):
    record = MagicMock()
    record.attestation.type = attestation_type
    record.allocation_policy = AllocationType.static.value
    record.iot_hubs = ["hub1"]
    record.initial_twin.tags.as_dict.return_value = {}
    record.initial_twin.properties.desired.as_dict.return_value = {}
    return record


def test_enrollment_update_tpm_and_device_info_and_credential(dps_sdk):
    record = _update_record(AttestationType.tpm.value)
    dps_sdk.individual_enrollment.get.return_value = record
    subject.iot_dps_device_enrollment_update(
        cmd=MagicMock(),
        enrollment_id="eid",
        dps_name="dps",
        endorsement_key="ek",
        device_information='{"k": "v"}',
        credential_policy_name="cred",
    )
    assert record.attestation.tpm.endorsement_key == "ek"
    assert record.credential_policy_name == "cred"


def test_enrollment_update_symmetric_keys(dps_sdk):
    record = _update_record(AttestationType.symmetricKey.value)
    dps_sdk.individual_enrollment.get.return_value = record
    subject.iot_dps_device_enrollment_update(
        cmd=MagicMock(),
        enrollment_id="eid",
        dps_name="dps",
        primary_key="pk",
        secondary_key="sk",
    )
    assert record.attestation.symmetric_key.primary_key == "pk"
    assert record.attestation.symmetric_key.secondary_key == "sk"


def test_enrollment_update_service_error(dps_sdk, handle_exc):
    dps_sdk.individual_enrollment.get.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_update(cmd=MagicMock(), enrollment_id="eid", dps_name="dps")
    handle_exc.assert_called_once()


def test_enrollment_delete_service_error(dps_sdk, handle_exc):
    dps_sdk.individual_enrollment.delete.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_delete(cmd=MagicMock(), enrollment_id="eid", dps_name="dps")
    handle_exc.assert_called_once()


# --- enrollment group list/get error + warning paths ------------------------


def test_enrollment_group_list_service_error(mocker, dps_sdk, handle_exc):
    mocker.patch.object(subject, "_execute_query", side_effect=_svc_exc())
    subject.iot_dps_device_enrollment_group_list(cmd=MagicMock(), dps_name="dps")
    handle_exc.assert_called_once()


def test_enrollment_group_get_show_keys_non_symmetric_warns(mocker, dps_sdk):
    warn = mocker.patch.object(subject.logger, "warning")
    dps_sdk.enrollment_group.get.return_value.response.json.return_value = {
        "attestation": {"type": AttestationType.x509.value}
    }
    result = subject.iot_dps_device_enrollment_group_get(
        cmd=MagicMock(), enrollment_id="gid", dps_name="dps", show_keys=True
    )
    assert result["attestation"]["type"] == AttestationType.x509.value
    warn.assert_called_once()


def test_enrollment_group_get_service_error(dps_sdk, handle_exc):
    dps_sdk.enrollment_group.get.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_group_get(cmd=MagicMock(), enrollment_id="gid", dps_name="dps")
    handle_exc.assert_called_once()


# --- enrollment group create branches ---------------------------------------


def test_enrollment_group_create_cert_and_root_ca_mutually_exclusive(mocker, dps_sdk):
    mocker.patch.object(subject, "_get_attestation_with_x509_signing_cert")
    with pytest.raises(MutuallyExclusiveArgumentError):
        subject.iot_dps_device_enrollment_group_create(
            cmd=MagicMock(),
            enrollment_id="gid",
            dps_name="dps",
            certificate_path="cert.pem",
            root_ca_name="rootca",
        )


def test_enrollment_group_create_service_error(mocker, dps_sdk, handle_exc):
    dps_sdk.enrollment_group.create_or_update.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_group_create(
        cmd=MagicMock(), enrollment_id="gid", dps_name="dps", primary_key="pk"
    )
    handle_exc.assert_called_once()


# --- enrollment group update branches ---------------------------------------


def test_enrollment_group_update_symmetric_keys(dps_sdk):
    record = _update_record(AttestationType.symmetricKey.value)
    dps_sdk.enrollment_group.get.return_value = record
    subject.iot_dps_device_enrollment_group_update(
        cmd=MagicMock(),
        enrollment_id="gid",
        dps_name="dps",
        primary_key="pk",
        secondary_key="sk",
    )
    assert record.attestation.symmetric_key.primary_key == "pk"
    assert record.attestation.symmetric_key.secondary_key == "sk"


def test_enrollment_group_update_remove_both_certs_requires_one(dps_sdk):
    record = _update_record(AttestationType.x509.value)
    dps_sdk.enrollment_group.get.return_value = record
    with pytest.raises(RequiredArgumentMissingError):
        subject.iot_dps_device_enrollment_group_update(
            cmd=MagicMock(),
            enrollment_id="gid",
            dps_name="dps",
            remove_certificate=True,
            remove_secondary_certificate=True,
        )


def test_enrollment_group_update_cannot_remove_primary(mocker, dps_sdk):
    record = _update_record(AttestationType.x509.value)
    dps_sdk.enrollment_group.get.return_value = record
    mocker.patch.object(subject, "_can_remove_primary_certificate", return_value=False)
    with pytest.raises(RequiredArgumentMissingError):
        subject.iot_dps_device_enrollment_group_update(
            cmd=MagicMock(),
            enrollment_id="gid",
            dps_name="dps",
            remove_certificate=True,
        )


def test_enrollment_group_update_cannot_remove_secondary(mocker, dps_sdk):
    record = _update_record(AttestationType.x509.value)
    dps_sdk.enrollment_group.get.return_value = record
    mocker.patch.object(subject, "_can_remove_primary_certificate", return_value=True)
    mocker.patch.object(subject, "_can_remove_secondary_certificate", return_value=False)
    with pytest.raises(RequiredArgumentMissingError):
        subject.iot_dps_device_enrollment_group_update(
            cmd=MagicMock(),
            enrollment_id="gid",
            dps_name="dps",
            remove_secondary_certificate=True,
        )


def test_enrollment_group_update_cert_and_root_ca_mutually_exclusive(dps_sdk):
    record = _update_record(AttestationType.x509.value)
    dps_sdk.enrollment_group.get.return_value = record
    with pytest.raises(MutuallyExclusiveArgumentError):
        subject.iot_dps_device_enrollment_group_update(
            cmd=MagicMock(),
            enrollment_id="gid",
            dps_name="dps",
            certificate_path="cert.pem",
            root_ca_name="rootca",
        )


def test_enrollment_group_update_credential_policy(dps_sdk):
    record = _update_record(AttestationType.symmetricKey.value)
    dps_sdk.enrollment_group.get.return_value = record
    subject.iot_dps_device_enrollment_group_update(
        cmd=MagicMock(),
        enrollment_id="gid",
        dps_name="dps",
        credential_policy_name="cred",
    )
    assert record.credential_policy_name == "cred"


def test_enrollment_group_update_service_error(dps_sdk, handle_exc):
    dps_sdk.enrollment_group.get.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_group_update(cmd=MagicMock(), enrollment_id="gid", dps_name="dps")
    handle_exc.assert_called_once()


def test_enrollment_group_delete_service_error(dps_sdk, handle_exc):
    dps_sdk.enrollment_group.delete.side_effect = _svc_exc()
    subject.iot_dps_device_enrollment_group_delete(cmd=MagicMock(), enrollment_id="gid", dps_name="dps")
    handle_exc.assert_called_once()


# --- compute device key service error ---------------------------------------


def test_compute_device_key_service_error(mocker):
    mocker.patch.object(subject, "DPSDiscovery")
    resolver = mocker.patch.object(subject, "SdkResolver")
    sdk = resolver.return_value.get_sdk.return_value
    sdk.enrollment_group.get_attestation_mechanism.side_effect = _svc_exc()
    with pytest.raises(AzureResponseError):
        subject.iot_dps_compute_device_key(
            cmd=MagicMock(), registration_id="reg", enrollment_id="grp", dps_name="dps"
        )


# --- connection string show_all + warning paths -----------------------------


def test_connection_string_show_all_policies(mocker):
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.find_resource.return_value = {
        "name": "mydps",
        "resourcegroup": "rg",
        "properties": {"serviceOperationsHostName": "host"},
    }
    discovery.get_policies.return_value = [
        {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}
    ]
    result = subject.iot_dps_connection_string_show(cmd=MagicMock(), dps_name="mydps", show_all=True)
    discovery.get_policies.assert_called_once()
    assert isinstance(result["connectionString"], list)


def test_connection_string_show_all_in_rg_policy_missing_warns(mocker):
    from azext_iot.common.shared import IoTDPSStateType

    warn = mocker.patch.object(subject.logger, "warning")
    discovery = mocker.patch.object(subject, "DPSDiscovery").return_value
    discovery.get_resources.return_value = [
        {
            "name": "active-dps",
            "resourcegroup": "rg",
            "properties": {"serviceOperationsHostName": "host", "state": IoTDPSStateType.Active.value},
        },
    ]
    discovery.find_policy.side_effect = Exception("no policy")
    result = subject.iot_dps_connection_string_show(cmd=MagicMock())
    assert result == []
    warn.assert_called_once()


# --- updated x509 client cert remove secondary ------------------------------


def test_updated_attestation_x509_client_cert_remove_secondary(mocker):
    mocker.patch.object(subject, "open_certificate", return_value="NEW")
    attestation = MagicMock()
    result = subject._get_updated_attestation_with_x509_client_cert(
        attestation,
        primary_certificate_path=None,
        secondary_certificate_path=None,
        remove_primary_certificate=False,
        remove_secondary_certificate=True,
    )
    assert result.x509.client_certificates.secondary is None


# --- validate allocation policy from current custom enrollment --------------


def test_allocation_policy_custom_from_current_enrollment():
    current = MagicMock()
    current.iot_hubs = None
    current.allocation_policy = AllocationType.custom.value
    current.custom_allocation_definition.webhook_url = "https://webhook"
    current.custom_allocation_definition.api_version = "2021-10-01"
    # No raise expected; webhook/api derived from current enrollment.
    subject._validate_allocation_policy_for_enrollment(
        None, None, None, None, None, current_enrollment=current
    )


# --- registration command service-error paths -------------------------------


def test_registration_list_service_error(mocker, dps_sdk, handle_exc):
    mocker.patch.object(subject, "_execute_query", side_effect=_svc_exc())
    subject.iot_dps_registration_list(cmd=MagicMock(), enrollment_id="eid", dps_name="dps")
    handle_exc.assert_called_once()


def test_registration_get_service_error(dps_sdk, handle_exc):
    dps_sdk.device_registration_state.get.side_effect = _svc_exc()
    subject.iot_dps_registration_get(cmd=MagicMock(), registration_id="reg", dps_name="dps")
    handle_exc.assert_called_once()


def test_registration_delete_service_error(dps_sdk, handle_exc):
    dps_sdk.device_registration_state.delete.side_effect = _svc_exc()
    subject.iot_dps_registration_delete(cmd=MagicMock(), registration_id="reg", dps_name="dps")
    handle_exc.assert_called_once()
