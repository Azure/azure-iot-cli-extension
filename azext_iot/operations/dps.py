# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import (
    SdkType,
    AttestationType,
    ReprovisionType,
    AllocationType,
)
from azext_iot.common._azure import get_iot_dps_connection_string
from azext_iot.common.utility import shell_safe_json_parse
from azext_iot.common.certops import open_certificate
from azext_iot.common.utility import compute_device_key
from azext_iot.operations.generic import _execute_query
from azext_iot._factory import SdkResolver
from azext_iot.sdk.dps.service.models.individual_enrollment import IndividualEnrollment
from azext_iot.sdk.dps.service.models.custom_allocation_definition import (
    CustomAllocationDefinition,
)
from azext_iot.sdk.dps.service.models.attestation_mechanism import AttestationMechanism
from azext_iot.sdk.dps.service.models.tpm_attestation import TpmAttestation
from azext_iot.sdk.dps.service.models.symmetric_key_attestation import (
    SymmetricKeyAttestation,
)
from azext_iot.sdk.dps.service.models.x509_attestation import X509Attestation
from azext_iot.sdk.dps.service.models.x509_certificates import X509Certificates
from azext_iot.sdk.dps.service.models.x509_certificate_with_info import (
    X509CertificateWithInfo,
)
from azext_iot.sdk.dps.service.models.initial_twin import InitialTwin
from azext_iot.sdk.dps.service.models.twin_collection import TwinCollection
from azext_iot.sdk.dps.service.models.initial_twin_properties import (
    InitialTwinProperties,
)
from azext_iot.sdk.dps.service.models.enrollment_group import EnrollmentGroup
from azext_iot.sdk.dps.service.models.x509_ca_references import X509CAReferences
from azext_iot.sdk.dps.service.models.reprovision_policy import ReprovisionPolicy
from azext_iot.sdk.dps.service.models import DeviceCapabilities
from azext_iot.sdk.dps.service.models import (
    ProvisioningServiceErrorDetailsException,
)  # TODO: Regen SDK

logger = get_logger(__name__)


# DPS Enrollments


def iot_dps_device_enrollment_list(client, dps_name, resource_group_name, top=None):
    from azext_iot.sdk.dps.service.models.query_specification import QuerySpecification

    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)

    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        query_command = "SELECT *"
        query = [QuerySpecification(query=query_command)]
        return _execute_query(query, sdk.query_individual_enrollments, top)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_get(client, enrollment_id, dps_name, resource_group_name, show_keys=None):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment = sdk.get_individual_enrollment(enrollment_id, raw=True).response.json()
        if show_keys:
            attestation = sdk.get_individual_enrollment_attestation_mechanism(enrollment_id, raw=True).response.json()
            enrollment['attestation'] = attestation
        return enrollment
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_create(
    client,
    enrollment_id,
    attestation_type,
    dps_name,
    resource_group_name,
    endorsement_key=None,
    certificate_path=None,
    secondary_certificate_path=None,
    primary_key=None,
    secondary_key=None,
    device_id=None,
    iot_hub_host_name=None,
    initial_twin_tags=None,
    initial_twin_properties=None,
    provisioning_status=None,
    reprovision_policy=None,
    allocation_policy=None,
    iot_hubs=None,
    edge_enabled=False,
    webhook_url=None,
    api_version=None,
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        if attestation_type == AttestationType.tpm.value:
            if not endorsement_key:
                raise CLIError("Endorsement key is requried")
            attestation = AttestationMechanism(
                type=AttestationType.tpm.value,
                tpm=TpmAttestation(endorsement_key=endorsement_key),
            )
        if attestation_type == AttestationType.x509.value:
            attestation = _get_attestation_with_x509_client_cert(
                certificate_path, secondary_certificate_path
            )
        if attestation_type == AttestationType.symmetricKey.value:
            attestation = AttestationMechanism(
                type=AttestationType.symmetricKey.value,
                symmetric_key=SymmetricKeyAttestation(
                    primary_key=primary_key, secondary_key=secondary_key
                ),
            )
        reprovision = _get_reprovision_policy(reprovision_policy)
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        iot_hub_list = iot_hubs.split() if iot_hubs else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if iot_hub_host_name and allocation_policy is None:
            allocation_policy = AllocationType.static.value
            iot_hub_list = iot_hub_host_name.split()

        custom_allocation_definition = (
            CustomAllocationDefinition(webhook_url=webhook_url, api_version=api_version)
            if allocation_policy == AllocationType.custom.value
            else None
        )
        capabilities = DeviceCapabilities(iot_edge=edge_enabled)
        enrollment = IndividualEnrollment(
            registration_id=enrollment_id,
            attestation=attestation,
            capabilities=capabilities,
            device_id=device_id,
            initial_twin=initial_twin,
            provisioning_status=provisioning_status,
            reprovision_policy=reprovision,
            allocation_policy=allocation_policy,
            iot_hubs=iot_hub_list,
            custom_allocation_definition=custom_allocation_definition,
        )
        return sdk.create_or_update_individual_enrollment(enrollment_id, enrollment)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_update(
    client,
    enrollment_id,
    dps_name,
    resource_group_name,
    etag=None,
    endorsement_key=None,
    certificate_path=None,
    secondary_certificate_path=None,
    remove_certificate=None,
    remove_secondary_certificate=None,
    primary_key=None,
    secondary_key=None,
    device_id=None,
    iot_hub_host_name=None,
    initial_twin_tags=None,
    initial_twin_properties=None,
    provisioning_status=None,
    reprovision_policy=None,
    allocation_policy=None,
    iot_hubs=None,
    edge_enabled=None,
    webhook_url=None,
    api_version=None,
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment_record = sdk.get_individual_enrollment(enrollment_id)
        # Verify etag
        if (
            etag
            and hasattr(enrollment_record, "etag")
            and etag != enrollment_record.etag.replace('"', "")
        ):
            raise LookupError("enrollment etag doesn't match.")
        if not etag:
            etag = enrollment_record.etag.replace('"', "")
        # Verify and update attestation information
        attestation_type = enrollment_record.attestation.type
        _validate_arguments_for_attestation_mechanism(
            attestation_type,
            endorsement_key,
            certificate_path,
            secondary_certificate_path,
            remove_certificate,
            remove_secondary_certificate,
            primary_key,
            secondary_key,
        )
        if attestation_type == AttestationType.tpm.value:
            if endorsement_key:
                enrollment_record.attestation.tpm.endorsement_key = endorsement_key
        elif attestation_type == AttestationType.x509.value:
            enrollment_record.attestation = _get_updated_attestation_with_x509_client_cert(
                enrollment_record.attestation,
                certificate_path,
                secondary_certificate_path,
                remove_certificate,
                remove_secondary_certificate,
            )
        else:
            enrollment_record.attestation = sdk.get_individual_enrollment_attestation_mechanism(
                enrollment_id
            )
            if primary_key:
                enrollment_record.attestation.symmetric_key.primary_key = primary_key
            if secondary_key:
                enrollment_record.attestation.symmetric_key.secondary_key = (
                    secondary_key
                )
        # Update enrollment information
        if iot_hub_host_name:
            enrollment_record.allocation_policy = AllocationType.static.value
            enrollment_record.iot_hubs = iot_hub_host_name.split()
            enrollment_record.iot_hub_host_name = None
        if device_id:
            enrollment_record.device_id = device_id
        if provisioning_status:
            enrollment_record.provisioning_status = provisioning_status
        enrollment_record.registrationState = None
        if reprovision_policy:
            enrollment_record.reprovision_policy = _get_reprovision_policy(
                reprovision_policy
            )
        enrollment_record.initial_twin = _get_updated_inital_twin(
            enrollment_record, initial_twin_tags, initial_twin_properties
        )
        iot_hub_list = iot_hubs.split() if iot_hubs else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if allocation_policy:
            enrollment_record.allocation_policy = allocation_policy
            enrollment_record.iot_hubs = iot_hub_list
            enrollment_record.iot_hub_host_name = None
            if allocation_policy == AllocationType.custom.value:
                enrollment_record.custom_allocation_definition = CustomAllocationDefinition(
                    webhook_url=webhook_url, api_version=api_version
                )
        if edge_enabled is not None:
            enrollment_record.capabilities = DeviceCapabilities(iot_edge=edge_enabled)

        return sdk.create_or_update_individual_enrollment(
            enrollment_id, enrollment_record, etag
        )
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_delete(
    client, enrollment_id, dps_name, resource_group_name
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.delete_individual_enrollment(enrollment_id)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


# DPS Enrollments Group


def iot_dps_device_enrollment_group_list(
    client, dps_name, resource_group_name, top=None
):
    from azext_iot.sdk.dps.service.models.query_specification import QuerySpecification

    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        query_command = "SELECT *"
        query1 = [QuerySpecification(query=query_command)]
        return _execute_query(query1, sdk.query_enrollment_groups, top)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_get(
    client, enrollment_id, dps_name, resource_group_name, show_keys=None
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment_group = sdk.get_enrollment_group(enrollment_id, raw=True).response.json()
        if show_keys:
            attestation = sdk.get_enrollment_group_attestation_mechanism(enrollment_id, raw=True).response.json()
            enrollment_group['attestation'] = attestation
        return enrollment_group
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_create(
    client,
    enrollment_id,
    dps_name,
    resource_group_name,
    certificate_path=None,
    secondary_certificate_path=None,
    root_ca_name=None,
    secondary_root_ca_name=None,
    primary_key=None,
    secondary_key=None,
    iot_hub_host_name=None,
    initial_twin_tags=None,
    initial_twin_properties=None,
    provisioning_status=None,
    reprovision_policy=None,
    allocation_policy=None,
    iot_hubs=None,
    edge_enabled=False,
    webhook_url=None,
    api_version=None,
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        if not certificate_path and not secondary_certificate_path:
            if not root_ca_name and not secondary_root_ca_name:
                attestation = AttestationMechanism(
                    type=AttestationType.symmetricKey.value,
                    symmetric_key=SymmetricKeyAttestation(
                        primary_key=primary_key, secondary_key=secondary_key
                    ),
                )
        if certificate_path or secondary_certificate_path:
            if root_ca_name or secondary_root_ca_name:
                raise CLIError(
                    "Please provide either certificate path or certficate name"
                )
            attestation = _get_attestation_with_x509_signing_cert(
                certificate_path, secondary_certificate_path
            )
        if root_ca_name or secondary_root_ca_name:
            if certificate_path or secondary_certificate_path:
                raise CLIError(
                    "Please provide either certificate path or certficate name"
                )
            attestation = _get_attestation_with_x509_ca_cert(
                root_ca_name, secondary_root_ca_name
            )
        reprovision = _get_reprovision_policy(reprovision_policy)
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        iot_hub_list = iot_hubs.split() if iot_hubs else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if iot_hub_host_name and allocation_policy is None:
            allocation_policy = AllocationType.static.value
            iot_hub_list = iot_hub_host_name.split()

        custom_allocation_definition = (
            CustomAllocationDefinition(webhook_url=webhook_url, api_version=api_version)
            if allocation_policy == AllocationType.custom.value
            else None
        )

        capabilities = DeviceCapabilities(iot_edge=edge_enabled)
        group_enrollment = EnrollmentGroup(
            enrollment_group_id=enrollment_id,
            attestation=attestation,
            capabilities=capabilities,
            initial_twin=initial_twin,
            provisioning_status=provisioning_status,
            reprovision_policy=reprovision,
            allocation_policy=allocation_policy,
            iot_hubs=iot_hub_list,
            custom_allocation_definition=custom_allocation_definition,
        )
        return sdk.create_or_update_enrollment_group(enrollment_id, group_enrollment)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_update(
    client,
    enrollment_id,
    dps_name,
    resource_group_name,
    etag=None,
    certificate_path=None,
    secondary_certificate_path=None,
    root_ca_name=None,
    secondary_root_ca_name=None,
    remove_certificate=None,
    remove_secondary_certificate=None,
    primary_key=None,
    secondary_key=None,
    iot_hub_host_name=None,
    initial_twin_tags=None,
    initial_twin_properties=None,
    provisioning_status=None,
    reprovision_policy=None,
    allocation_policy=None,
    iot_hubs=None,
    edge_enabled=None,
    webhook_url=None,
    api_version=None,
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment_record = sdk.get_enrollment_group(enrollment_id)
        # Verify etag
        if (
            etag
            and hasattr(enrollment_record, "etag")
            and etag != enrollment_record.etag.replace('"', "")
        ):
            raise LookupError("enrollment etag doesn't match.")
        if not etag:
            etag = enrollment_record.etag.replace('"', "")
        # Update enrollment information
        if enrollment_record.attestation.type == AttestationType.symmetricKey.value:
            enrollment_record.attestation = sdk.get_enrollment_group_attestation_mechanism(
                enrollment_id
            )
            if primary_key:
                enrollment_record.attestation.symmetric_key.primary_key = primary_key
            if secondary_key:
                enrollment_record.attestation.symmetric_key.secondary_key = (
                    secondary_key
                )

        if enrollment_record.attestation.type == AttestationType.x509.value:
            if not certificate_path and not secondary_certificate_path:
                if not root_ca_name and not secondary_root_ca_name:
                    # Check if certificate can be safely removed while no new certificate has been provided
                    if remove_certificate and remove_secondary_certificate:
                        raise CLIError("Please provide at least one certificate")

                    if not _can_remove_primary_certificate(
                        remove_certificate, enrollment_record.attestation
                    ):
                        raise CLIError(
                            "Please provide at least one certificate while removing the only primary certificate"
                        )

                    if not _can_remove_secondary_certificate(
                        remove_secondary_certificate, enrollment_record.attestation
                    ):
                        raise CLIError(
                            "Please provide at least one certificate while removing the only secondary certificate"
                        )

            if certificate_path or secondary_certificate_path:
                if root_ca_name or secondary_root_ca_name:
                    raise CLIError(
                        "Please provide either certificate path or certficate name"
                    )
                enrollment_record.attestation = _get_updated_attestation_with_x509_signing_cert(
                    enrollment_record.attestation,
                    certificate_path,
                    secondary_certificate_path,
                    remove_certificate,
                    remove_secondary_certificate,
                )
            if root_ca_name or secondary_root_ca_name:
                if certificate_path or secondary_certificate_path:
                    raise CLIError(
                        "Please provide either certificate path or certficate name"
                    )
                enrollment_record.attestation = _get_updated_attestation_with_x509_ca_cert(
                    enrollment_record.attestation,
                    root_ca_name,
                    secondary_root_ca_name,
                    remove_certificate,
                    remove_secondary_certificate,
                )
        if iot_hub_host_name:
            enrollment_record.allocation_policy = AllocationType.static.value
            enrollment_record.iot_hubs = iot_hub_host_name.split()
            enrollment_record.iot_hub_host_name = None
        if provisioning_status:
            enrollment_record.provisioning_status = provisioning_status
        if reprovision_policy:
            enrollment_record.reprovision_policy = _get_reprovision_policy(
                reprovision_policy
            )
        enrollment_record.initial_twin = _get_updated_inital_twin(
            enrollment_record, initial_twin_tags, initial_twin_properties
        )
        iot_hub_list = iot_hubs.split() if iot_hubs else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if allocation_policy:
            enrollment_record.allocation_policy = allocation_policy
            enrollment_record.iot_hubs = iot_hub_list
            enrollment_record.iot_hub_host_name = None
            if allocation_policy == AllocationType.custom.value:
                enrollment_record.custom_allocation_definition = CustomAllocationDefinition(
                    webhook_url=webhook_url, api_version=api_version
                )
        if edge_enabled is not None:
            enrollment_record.capabilities = DeviceCapabilities(iot_edge=edge_enabled)
        return sdk.create_or_update_enrollment_group(
            enrollment_id, enrollment_record, etag
        )
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_device_enrollment_group_delete(
    client, enrollment_id, dps_name, resource_group_name
):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.delete_enrollment_group(enrollment_id)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_compute_device_key(
    cmd, primary_key, registration_id,
):
    return compute_device_key(primary_key=primary_key, registration_id=registration_id)


# DPS Registration


def iot_dps_registration_list(client, dps_name, resource_group_name, enrollment_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.query_device_registration_states(enrollment_id, raw=True).response.json()
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_registration_get(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.get_device_registration_state(registration_id, raw=True).response.json()
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def iot_dps_registration_delete(client, dps_name, resource_group_name, registration_id):
    target = get_iot_dps_connection_string(client, dps_name, resource_group_name)
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.delete_device_registration_state(registration_id)
    except ProvisioningServiceErrorDetailsException as e:
        raise CLIError(e)


def _get_initial_twin(initial_twin_tags=None, initial_twin_properties=None):
    from azext_iot.common.utility import dict_clean

    if initial_twin_tags == "":
        initial_twin_tags = None
    elif initial_twin_tags:
        initial_twin_tags = dict_clean(shell_safe_json_parse(str(initial_twin_tags)))

    if initial_twin_properties == "":
        initial_twin_properties = None
    elif initial_twin_properties:
        initial_twin_properties = dict_clean(
            shell_safe_json_parse(str(initial_twin_properties))
        )

    return InitialTwin(
        tags=TwinCollection(additional_properties=initial_twin_tags),
        properties=InitialTwinProperties(
            desired=TwinCollection(additional_properties=initial_twin_properties)
        ),
    )


def _get_updated_inital_twin(
    enrollment_record, initial_twin_tags=None, initial_twin_properties=None
):
    if initial_twin_properties != "" and not initial_twin_tags:
        if hasattr(enrollment_record, "initial_twin"):
            if hasattr(enrollment_record.initial_twin, "tags"):
                initial_twin_tags = enrollment_record.initial_twin.tags
    if initial_twin_properties != "" and not initial_twin_properties:
        if hasattr(enrollment_record, "initial_twin"):
            if hasattr(enrollment_record.initial_twin, "properties"):
                if hasattr(enrollment_record.initial_twin.properties, "desired"):
                    initial_twin_properties = (
                        enrollment_record.initial_twin.properties.desired
                    )
    return _get_initial_twin(initial_twin_tags, initial_twin_properties)


def _get_x509_certificate(certificate_path, secondary_certificate_path):
    x509certificate = X509Certificates(
        primary=_get_certificate_info(certificate_path),
        secondary=_get_certificate_info(secondary_certificate_path),
    )
    return x509certificate


def _get_certificate_info(certificate_path):
    if not certificate_path:
        return None
    certificate_content = open_certificate(certificate_path)
    certificate_with_info = X509CertificateWithInfo(certificate=certificate_content)
    return certificate_with_info


def _get_attestation_with_x509_client_cert(
    primary_certificate_path, secondary_certificate_path
):
    if not primary_certificate_path and not secondary_certificate_path:
        raise CLIError("Please provide at least one certificate path")
    certificate = _get_x509_certificate(
        primary_certificate_path, secondary_certificate_path
    )
    x509Attestation = X509Attestation(client_certificates=certificate)
    attestation = AttestationMechanism(
        type=AttestationType.x509.value, x509=x509Attestation
    )
    return attestation


def _get_updated_attestation_with_x509_client_cert(
    attestation,
    primary_certificate_path,
    secondary_certificate_path,
    remove_primary_certificate,
    remove_secondary_certificate,
):
    if remove_primary_certificate:
        attestation.x509.client_certificates.primary = None
    if remove_secondary_certificate:
        attestation.x509.client_certificates.secondary = None
    if primary_certificate_path:
        attestation.x509.client_certificates.primary = _get_certificate_info(
            primary_certificate_path
        )
    if secondary_certificate_path:
        attestation.x509.client_certificates.secondary = _get_certificate_info(
            secondary_certificate_path
        )
    return attestation


def _get_attestation_with_x509_signing_cert(
    primary_certificate_path, secondary_certificate_path
):
    certificate = _get_x509_certificate(
        primary_certificate_path, secondary_certificate_path
    )
    x509Attestation = X509Attestation(signing_certificates=certificate)
    attestation = AttestationMechanism(
        type=AttestationType.x509.value, x509=x509Attestation
    )
    return attestation


def _get_attestation_with_x509_ca_cert(root_ca_name, secondary_root_ca_name):
    certificate = X509CAReferences(
        primary=root_ca_name, secondary=secondary_root_ca_name
    )
    x509Attestation = X509Attestation(ca_references=certificate)
    attestation = AttestationMechanism(
        type=AttestationType.x509.value, x509=x509Attestation
    )
    return attestation


def _get_updated_attestation_with_x509_signing_cert(
    attestation,
    primary_certificate_path,
    secondary_certificate_path,
    remove_primary_certificate,
    remove_secondary_certificate,
):
    if hasattr(attestation.x509, "signing_certificates"):
        if remove_primary_certificate:
            attestation.x509.signing_certificates.primary = None
        if remove_secondary_certificate:
            attestation.x509.signing_certificates.secondary = None
        if primary_certificate_path:
            attestation.x509.signing_certificates.primary = _get_certificate_info(
                primary_certificate_path
            )
        if secondary_certificate_path:
            attestation.x509.signing_certificates.secondary = _get_certificate_info(
                secondary_certificate_path
            )
        return attestation
    return _get_attestation_with_x509_signing_cert(
        primary_certificate_path, secondary_certificate_path
    )


def _get_updated_attestation_with_x509_ca_cert(
    attestation,
    root_ca_name,
    secondary_root_ca_name,
    remove_primary_certificate,
    remove_secondary_certificate,
):
    if (
        hasattr(attestation.x509, "ca_references")
        and attestation.x509.ca_references is not None
    ):
        if remove_primary_certificate:
            attestation.x509.ca_references.primary = None
        if remove_secondary_certificate:
            attestation.x509.ca_references.secondary = None
        if root_ca_name:
            attestation.x509.ca_references.primary = root_ca_name
        if secondary_root_ca_name:
            attestation.x509.ca_references.secondary = secondary_root_ca_name
        return attestation
    return _get_attestation_with_x509_ca_cert(root_ca_name, secondary_root_ca_name)


def _can_remove_primary_certificate(remove_certificate, attestation):
    if remove_certificate:
        if hasattr(attestation.x509, "signing_certificates"):
            if (
                not hasattr(attestation.x509.signing_certificates, "secondary")
                or not attestation.x509.signing_certificates.secondary
            ):
                return False
        if hasattr(attestation.x509, "ca_references"):
            if (
                not hasattr(attestation.x509.ca_references, "secondary")
                or not attestation.x509.ca_references.secondary
            ):
                return False
    return True


def _can_remove_secondary_certificate(remove_certificate, attestation):
    if remove_certificate:
        if hasattr(attestation.x509, "signing_certificates"):
            if (
                not hasattr(attestation.x509.signing_certificates, "primary")
                or not attestation.x509.signing_certificates.primary
            ):
                return False
        if hasattr(attestation.x509, "ca_references"):
            if (
                not hasattr(attestation.x509.ca_references, "primary")
                or not attestation.x509.ca_references.primary
            ):
                return False
    return True


def _get_reprovision_policy(reprovision_policy):
    if reprovision_policy:
        if reprovision_policy == ReprovisionType.reprovisionandmigratedata.value:
            reprovision = ReprovisionPolicy(
                update_hub_assignment=True, migrate_device_data=True
            )
        elif reprovision_policy == ReprovisionType.reprovisionandresetdata.value:
            reprovision = ReprovisionPolicy(
                update_hub_assignment=True, migrate_device_data=False
            )
        elif reprovision_policy == ReprovisionType.never.value:
            reprovision = ReprovisionPolicy(
                update_hub_assignment=False, migrate_device_data=False
            )
        else:
            raise CLIError("Invalid Reprovision Policy.")
    else:
        reprovision = ReprovisionPolicy(
            update_hub_assignment=True, migrate_device_data=True
        )
    return reprovision


def _validate_arguments_for_attestation_mechanism(
    attestation_type,
    endorsement_key,
    certificate_path,
    secondary_certificate_path,
    remove_certificate,
    remove_secondary_certificate,
    primary_key,
    secondary_key,
):
    if attestation_type == AttestationType.tpm.value:
        if certificate_path or secondary_certificate_path:
            raise CLIError(
                "Cannot update certificate while enrollment is using tpm attestation mechanism"
            )
        if remove_certificate or remove_secondary_certificate:
            raise CLIError(
                "Cannot remove certificate while enrollment is using tpm attestation mechanism"
            )
        if primary_key or secondary_key:
            raise CLIError(
                "Cannot update primary or secondary key while enrollment is using tpm attestation mechanism"
            )
    elif attestation_type == AttestationType.x509.value:
        if endorsement_key:
            raise CLIError(
                "Cannot update endorsement key while enrollment is using x509 attestation mechanism"
            )
        if primary_key or secondary_key:
            raise CLIError(
                "Cannot update primary or secondary key while enrollment is using x509 attestation mechanism"
            )
    else:
        if certificate_path or secondary_certificate_path:
            raise CLIError(
                "Cannot update certificate while enrollment is using symmetric key attestation mechanism"
            )
        if remove_certificate or remove_secondary_certificate:
            raise CLIError(
                "Cannot remove certificate while enrollment is using symmetric key attestation mechanism"
            )
        if endorsement_key:
            raise CLIError(
                "Cannot update endorsement key while enrollment is using symmetric key attestation mechanism"
            )


def _validate_allocation_policy_for_enrollment(
    allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
):
    if allocation_policy:
        if iot_hub_host_name is not None:
            raise CLIError(
                "'iot_hub_host_name' is not required when allocation-policy is defined."
            )
        if not any(
            allocation_policy == allocation.value for allocation in AllocationType
        ):
            raise CLIError("Please provide valid allocation policy.")
        if allocation_policy == AllocationType.static.value:
            if iot_hub_list is None:
                raise CLIError("Please provide a hub to be assigned with device.")
            if iot_hub_list and len(iot_hub_list) > 1:
                raise CLIError("Only one hub is required in static allocation policy.")
        if allocation_policy == AllocationType.custom.value:
            if webhook_url is None or api_version is None:
                raise CLIError(
                    "Please provide both the Azure function webhook url and provisioning"
                    " service api-version when the allocation-policy is defined as Custom."
                )
    else:
        if iot_hub_list:
            raise CLIError("Please provide allocation policy.")
