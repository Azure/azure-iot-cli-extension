# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import (SdkType,
                                     AttestationType)
from azext_iot.common.azure import get_iot_dps_connection_string
from azext_iot.common.utility import evaluate_literal
from azext_iot.common.certops import open_certificate
from azext_iot.operations.generic import execute_query
from azext_iot._factory import _bind_sdk

from azext_iot.dps_sdk.models.individual_enrollment import IndividualEnrollment
from azext_iot.dps_sdk.models.attestation_mechanism import AttestationMechanism
from azext_iot.dps_sdk.models.tpm_attestation import TpmAttestation
from azext_iot.dps_sdk.models.x509_attestation import X509Attestation
from azext_iot.dps_sdk.models.x509_certificates import X509Certificates
from azext_iot.dps_sdk.models.x509_certificate_with_info import X509CertificateWithInfo
from azext_iot.dps_sdk.models.initial_twin import InitialTwin
from azext_iot.dps_sdk.models.twin_collection import TwinCollection
from azext_iot.dps_sdk.models.initial_twin_properties import InitialTwinProperties
from azext_iot.dps_sdk.models.enrollment_group import EnrollmentGroup
from azext_iot.dps_sdk.models.x509_ca_references import X509CAReferences

logger = get_logger(__name__)


# DPS Enrollments

def iot_dps_device_enrollment_list(client, dps_name, resource_group_name, top=None):
    from azext_iot.dps_sdk.models.query_specification import QuerySpecification
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        query_command = "SELECT *"
        query = QuerySpecification(query_command)
        return execute_query(query, m_sdk.device_enrollment.query, errors, top)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_get(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment.get(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_create(client,
                                     enrollment_id,
                                     attestation_type,
                                     dps_name,
                                     resource_group_name,
                                     endorsement_key=None,
                                     certificate_path=None,
                                     secondary_certificate_path=None,
                                     device_id=None,
                                     iot_hub_host_name=None,
                                     initial_twin_tags=None,
                                     initial_twin_properties=None,
                                     provisioning_status=None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        if attestation_type == AttestationType.tpm.value:
            if not endorsement_key:
                raise CLIError('Endorsement key is requried')
            tpm = TpmAttestation(endorsement_key)
            attestation = AttestationMechanism(AttestationType.tpm.value, tpm)
        if attestation_type == AttestationType.x509.value:
            attestation = _get_attestation_with_x509_client_cert(certificate_path, secondary_certificate_path)

        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        enrollment = IndividualEnrollment(enrollment_id,
                                          attestation,
                                          device_id,
                                          None,
                                          iot_hub_host_name,
                                          initial_twin,
                                          None,
                                          provisioning_status)

        return m_sdk.device_enrollment.create_or_update(enrollment_id, enrollment)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_update(client,
                                     enrollment_id,
                                     dps_name,
                                     resource_group_name,
                                     etag,
                                     endorsement_key=None,
                                     certificate_path=None,
                                     secondary_certificate_path=None,
                                     remove_certificate=None,
                                     remove_secondary_certificate=None,
                                     device_id=None,
                                     iot_hub_host_name=None,
                                     initial_twin_tags=None,
                                     initial_twin_properties=None,
                                     provisioning_status=None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        # Verify etag
        enrollment_record = m_sdk.device_enrollment.get(enrollment_id)
        if 'etag' not in enrollment_record:
            raise LookupError("enrollment etag not found.")
        if etag != enrollment_record['etag'].replace('"', ''):
            raise LookupError("enrollment etag doesn't match.")

        # Verify and update attestation information
        attestation_type = enrollment_record['attestation']['type']
        if attestation_type == AttestationType.tpm.value:
            if certificate_path or secondary_certificate_path:
                raise CLIError('Cannot update certificate while enrollment is using tpm attestation mechanism')
            if remove_certificate or remove_secondary_certificate:
                raise CLIError('Cannot remove certificate while enrollment is using tpm attestation mechanism')
            if endorsement_key:
                enrollment_record['attestation']['tpm']['endorsement_key'] = endorsement_key
        else:
            if endorsement_key:
                raise CLIError('Cannot update endorsement key while enrollment is using x509 attestation mechanism')
            enrollment_record['attestation'] = _get_updated_attestation_with_x509_client_cert(enrollment_record['attestation'],
                                                                                              certificate_path,
                                                                                              secondary_certificate_path,
                                                                                              remove_certificate,
                                                                                              remove_secondary_certificate)

        # Update enrollment information
        if iot_hub_host_name:
            enrollment_record['iotHubHostName'] = iot_hub_host_name
        if device_id:
            enrollment_record['deviceId'] = device_id
        if provisioning_status:
            enrollment_record['provisioningStatus'] = provisioning_status
        enrollment_record['registrationState'] = None

        enrollment_record['initialTwin'] = _get_updated_inital_twin(enrollment_record,
                                                                    initial_twin_tags,
                                                                    initial_twin_properties)

        return m_sdk.device_enrollment.create_or_update(enrollment_id, enrollment_record, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_delete(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment.delete(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# DPS Enrollments Group

def iot_dps_device_enrollment_group_list(client, dps_name, resource_group_name, top=None):
    from azext_iot.dps_sdk.models.query_specification import QuerySpecification
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        query_command = "SELECT *"
        query = QuerySpecification(query_command)
        return execute_query(query, m_sdk.device_enrollment_group.query, errors, top)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_get(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment_group.get(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_create(client,
                                           enrollment_id,
                                           dps_name,
                                           resource_group_name,
                                           certificate_path=None,
                                           secondary_certificate_path=None,
                                           certificate_name=None,
                                           secondary_certificate_name=None,
                                           iot_hub_host_name=None,
                                           initial_twin_tags=None,
                                           initial_twin_properties=None,
                                           provisioning_status=None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        if not certificate_path and not secondary_certificate_path:
            if not certificate_name and not secondary_certificate_name:
                raise CLIError('Please provide at least one certificate')

        if certificate_path or secondary_certificate_path:
            if certificate_name or secondary_certificate_name:
                raise CLIError('Please provide either certificate path or certficate name')
            attestation = _get_attestation_with_x509_signing_cert(certificate_path, secondary_certificate_path)

        if certificate_name or secondary_certificate_name:
            if certificate_path or secondary_certificate_path:
                raise CLIError('Please provide either certificate path or certficate name')
            attestation = _get_attestation_with_x509_ca_cert(certificate_name, secondary_certificate_name)

        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        group_enrollment = EnrollmentGroup(enrollment_id,
                                           attestation,
                                           iot_hub_host_name,
                                           initial_twin,
                                           None,
                                           provisioning_status)

        return m_sdk.device_enrollment_group.create_or_update(enrollment_id, group_enrollment)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_update(client,
                                           enrollment_id,
                                           dps_name,
                                           resource_group_name,
                                           etag,
                                           certificate_path=None,
                                           secondary_certificate_path=None,
                                           certificate_name=None,
                                           secondary_certificate_name=None,
                                           remove_certificate=None,
                                           remove_secondary_certificate=None,
                                           iot_hub_host_name=None,
                                           initial_twin_tags=None,
                                           initial_twin_properties=None,
                                           provisioning_status=None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)

        # Verify etag
        enrollment_record = m_sdk.device_enrollment_group.get(enrollment_id)
        if 'etag' not in enrollment_record:
            raise LookupError("enrollment etag not found.")
        if etag != enrollment_record['etag'].replace('"', ''):
            raise LookupError("enrollment etag doesn't match.")

        # Update enrollment information
        if not certificate_path and not secondary_certificate_path:
            if not certificate_name and not secondary_certificate_name:
                # Check if certificate can be safely removed while no new certificate has been provided
                if remove_certificate and remove_secondary_certificate:
                    raise CLIError('Please provide at least one certificate')

                if not _can_remove_primary_certificate(remove_certificate, enrollment_record['attestation']):
                    raise CLIError('Please provide at least one certificate while removing the only primary certificate')

                if not _can_remove_secondary_certificate(remove_secondary_certificate, enrollment_record['attestation']):
                    raise CLIError('Please provide at least one certificate while removing the only secondary certificate')

        if certificate_path or secondary_certificate_path:
            if certificate_name or secondary_certificate_name:
                raise CLIError('Please provide either certificate path or certficate name')
            enrollment_record['attestation'] = _get_updated_attestation_with_x509_signing_cert(enrollment_record['attestation'],
                                                                                               certificate_path,
                                                                                               secondary_certificate_path,
                                                                                               remove_certificate,
                                                                                               remove_secondary_certificate)

        if certificate_name or secondary_certificate_name:
            if certificate_path or secondary_certificate_path:
                raise CLIError('Please provide either certificate path or certficate name')
            enrollment_record['attestation'] = _get_updated_attestation_with_x509_ca_cert(enrollment_record['attestation'],
                                                                                          certificate_name,
                                                                                          secondary_certificate_name,
                                                                                          remove_certificate,
                                                                                          remove_secondary_certificate)

        if iot_hub_host_name:
            enrollment_record['iotHubHostName'] = iot_hub_host_name
        if provisioning_status:
            enrollment_record['provisioningStatus'] = provisioning_status

        enrollment_record['initialTwin'] = _get_updated_inital_twin(enrollment_record,
                                                                    initial_twin_tags,
                                                                    initial_twin_properties)

        return m_sdk.device_enrollment_group.create_or_update(enrollment_id, enrollment_record, etag)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_delete(client, enrollment_id, dps_name, resource_group_name):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.device_enrollment_group.delete(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


# DPS Registration

def iot_dps_registration_list(client, dps_name, resource_group_name, enrollment_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.query_registration_state(enrollment_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_registration_get(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.get_registration_state(registration_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_registration_delete(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        m_sdk, errors = _bind_sdk(target, SdkType.dps_sdk)
        return m_sdk.registration_status.delete_registration_state(registration_id)
    except errors.ErrorDetailsException as e:
        raise CLIError(e)


def _get_initial_twin(initial_twin_tags=None, initial_twin_properties=None):
    if initial_twin_tags == "":
        initial_twin_tags = None
    elif initial_twin_tags:
        initial_twin_tags = evaluate_literal(str(initial_twin_tags), dict)

    if initial_twin_properties == "":
        initial_twin_properties = None
    elif initial_twin_properties:
        initial_twin_properties = evaluate_literal(str(initial_twin_properties), dict)

    return InitialTwin(TwinCollection(initial_twin_tags),
                       InitialTwinProperties(TwinCollection(initial_twin_properties)))


def _get_updated_inital_twin(enrollment_record, initial_twin_tags=None, initial_twin_properties=None):
    if initial_twin_properties != "" and not initial_twin_tags:
        if 'initialTwin' in enrollment_record:
            if 'tags' in enrollment_record['initialTwin']:
                initial_twin_tags = enrollment_record['initialTwin']['tags']
    if initial_twin_properties != "" and not initial_twin_properties:
        if 'initialTwin' in enrollment_record:
            if 'properties' in enrollment_record['initialTwin']:
                if 'desired' in enrollment_record['initialTwin']['properties']:
                    initial_twin_properties = enrollment_record['initialTwin']['properties']['desired']
    return _get_initial_twin(initial_twin_tags, initial_twin_properties)


def _get_x509_certificate(certificate_path, secondary_certificate_path):
    x509certificate = X509Certificates(_get_certificate_info(certificate_path),
                                       _get_certificate_info(secondary_certificate_path))

    return x509certificate


def _get_certificate_info(certificate_path):
    if not certificate_path:
        return None

    certificate_content = open_certificate(certificate_path)
    certificate_with_info = X509CertificateWithInfo(certificate_content)
    return certificate_with_info


def _get_attestation_with_x509_client_cert(primary_certificate_path, secondary_certificate_path):
    if not primary_certificate_path and not secondary_certificate_path:
        raise CLIError('Please provide at least one certificate path')
    certificate = _get_x509_certificate(primary_certificate_path, secondary_certificate_path)
    x509Attestation = X509Attestation(certificate)
    attestation = AttestationMechanism(AttestationType.x509.value, None, x509Attestation)

    return attestation


def _get_updated_attestation_with_x509_client_cert(attestation,
                                                   primary_certificate_path,
                                                   secondary_certificate_path,
                                                   remove_primary_certificate,
                                                   remove_secondary_certificate):
    if remove_primary_certificate:
        attestation['x509']['clientCertificates']['primary'] = None
    if remove_secondary_certificate:
        attestation['x509']['clientCertificates']['secondary'] = None
    if primary_certificate_path:
        attestation['x509']['clientCertificates']['primary'] = _get_certificate_info(primary_certificate_path)
    if secondary_certificate_path:
        attestation['x509']['clientCertificates']['secondary'] = _get_certificate_info(secondary_certificate_path)

    return attestation


def _get_attestation_with_x509_signing_cert(primary_certificate_path,
                                            secondary_certificate_path):
    certificate = _get_x509_certificate(primary_certificate_path, secondary_certificate_path)
    x509Attestation = X509Attestation(None, certificate)
    attestation = AttestationMechanism(AttestationType.x509.value, None, x509Attestation)

    return attestation


def _get_attestation_with_x509_ca_cert(primary_certificate_name,
                                       secondary_certificate_name):
    certificate = X509CAReferences(primary_certificate_name, secondary_certificate_name)
    x509Attestation = X509Attestation(None, None, certificate)
    attestation = AttestationMechanism(AttestationType.x509.value, None, x509Attestation)

    return attestation


def _get_updated_attestation_with_x509_signing_cert(attestation,
                                                    primary_certificate_path,
                                                    secondary_certificate_path,
                                                    remove_primary_certificate,
                                                    remove_secondary_certificate):
    if 'signingCertificates' in attestation['x509']:
        if remove_primary_certificate:
            attestation['x509']['signingCertificates']['primary'] = None
        if remove_secondary_certificate:
            attestation['x509']['signingCertificates']['secondary'] = None
        if primary_certificate_path:
            attestation['x509']['signingCertificates']['primary'] = _get_certificate_info(primary_certificate_path)
        if secondary_certificate_path:
            attestation['x509']['signingCertificates']['secondary'] = _get_certificate_info(secondary_certificate_path)

        return attestation

    return _get_attestation_with_x509_signing_cert(primary_certificate_path, secondary_certificate_path)


def _get_updated_attestation_with_x509_ca_cert(attestation,
                                               primary_certificate_name,
                                               secondary_certificate_name,
                                               remove_primary_certificate,
                                               remove_secondary_certificate):
    if 'caReferences' in attestation['x509']:
        if remove_primary_certificate:
            attestation['x509']['caReferences']['primary'] = None
        if remove_secondary_certificate:
            attestation['x509']['caReferences']['secondary'] = None
        if primary_certificate_name:
            attestation['x509']['caReferences']['primary'] = primary_certificate_name
        if secondary_certificate_name:
            attestation['x509']['caReferences']['secondary'] = secondary_certificate_name

        return attestation

    return _get_attestation_with_x509_ca_cert(primary_certificate_name, secondary_certificate_name)


def _can_remove_primary_certificate(remove_certificate,
                                    attestation):
    if remove_certificate:
        if 'signingCertificates' in attestation['x509']:
            if ('secondary' not in attestation['x509']['signingCertificates'] or
                    not attestation['x509']['signingCertificates']['secondary']):
                return False
        if 'caReferences' in attestation['x509']:
            if ('secondary' not in attestation['x509']['caReferences'] or
                    not attestation['x509']['caReferences']['secondary']):
                return False
    return True


def _can_remove_secondary_certificate(remove_certificate,
                                      attestation):
    if remove_certificate:
        if 'signingCertificates' in attestation['x509']:
            if ('primary' not in attestation['x509']['signingCertificates'] or
                    not attestation['x509']['signingCertificates']['primary']):
                return False
        if 'caReferences' in attestation['x509']:
            if ('primary' not in attestation['x509']['caReferences'] or
                    not attestation['x509']['caReferences']['primary']):
                return False
    return True
