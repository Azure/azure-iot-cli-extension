# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    BadRequestError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    UnauthorizedError
)
from azext_iot.common._azure import IOT_SERVICE_CS_TEMPLATE
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import (
    SdkType,
    AttestationType,
    ReprovisionType,
    AllocationType,
    KeyType,
    IoTDPSStateType
)
from azext_iot.common.utility import compute_device_key, handle_service_exception, shell_safe_json_parse
from azext_iot.common.certops import open_certificate
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.generic import _execute_query
from azext_iot._factory import SdkResolver
from azext_iot.sdk.dps.service.models import (
    IndividualEnrollment,
    CustomAllocationDefinition,
    AttestationMechanism,
    TpmAttestation,
    SymmetricKeyAttestation,
    X509Attestation,
    X509Certificates,
    X509CertificateWithInfo,
    InitialTwin,
    TwinCollection,
    InitialTwinProperties,
    EnrollmentGroup,
    X509CAReferences,
    ReprovisionPolicy,
    DeviceCapabilities,
    ProvisioningServiceErrorDetailsException,
)

logger = get_logger(__name__)
GLOBAL_PROVISIONING_HOST = "global.azure-devices-provisioning.net"


# DPS Enrollments


def iot_dps_device_enrollment_list(
    cmd,
    dps_name=None,
    resource_group_name=None,
    top=None,
    login=None,
    auth_type_dataplane=None,
):
    from azext_iot.sdk.dps.service.models.query_specification import QuerySpecification

    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )

    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        query_command = "SELECT *"
        query = [QuerySpecification(query=query_command)]
        return _execute_query(query, sdk.individual_enrollment.query, top)
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_get(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
    show_keys=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment = sdk.individual_enrollment.get(
            enrollment_id, raw=True
        ).response.json()
        if show_keys:
            enrollment_type = enrollment["attestation"]["type"]
            if enrollment_type == AttestationType.symmetricKey.value:
                attestation = sdk.individual_enrollment.get_attestation_mechanism(
                    enrollment_id, raw=True
                ).response.json()
                enrollment["attestation"] = attestation
            else:
                logger.warning(
                    "--show-keys argument was provided, but requested enrollment has an attestation type of '{}'."
                    " Currently, --show-keys is only supported for symmetric key enrollments".format(
                        enrollment_type
                    )
                )
        return enrollment
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_create(
    cmd,
    enrollment_id,
    attestation_type,
    dps_name=None,
    resource_group_name=None,
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
    device_information=None,
    api_version=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        if attestation_type == AttestationType.tpm.value:
            if not endorsement_key:
                raise RequiredArgumentMissingError("Endorsement key [--endorsement-key] is required")
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
            optional_device_information=_get_twin_collection(device_information)
        )
        return sdk.individual_enrollment.create_or_update(enrollment_id, enrollment)
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_update(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
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
    device_information=None,
    api_version=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)
        enrollment_record = sdk.individual_enrollment.get(enrollment_id)

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
            enrollment_record.attestation = sdk.individual_enrollment.get_attestation_mechanism(
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
        if device_information:
            enrollment_record.optional_device_information = _get_twin_collection(device_information)

        return sdk.individual_enrollment.create_or_update(
            enrollment_id, enrollment_record, if_match=(etag if etag else "*")
        )
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_delete(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
    etag=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.individual_enrollment.delete(enrollment_id, if_match=(etag if etag else "*"))
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


# DPS Enrollments Group


def iot_dps_device_enrollment_group_list(
    cmd, dps_name=None, resource_group_name=None, top=None, login=None, auth_type_dataplane=None,
):
    from azext_iot.sdk.dps.service.models.query_specification import QuerySpecification

    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        query_command = "SELECT *"
        query1 = [QuerySpecification(query=query_command)]
        return _execute_query(query1, sdk.enrollment_group.query, top)
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_group_get(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
    show_keys=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment_group = sdk.enrollment_group.get(
            enrollment_id, raw=True
        ).response.json()
        if show_keys:
            enrollment_type = enrollment_group["attestation"]["type"]
            if enrollment_type == AttestationType.symmetricKey.value:
                attestation = sdk.enrollment_group.get_attestation_mechanism(
                    enrollment_id, raw=True
                ).response.json()
                enrollment_group["attestation"] = attestation
            else:
                logger.warning(
                    "--show-keys argument was provided, but requested enrollment group has an attestation type of '{}'."
                    " Currently, --show-keys is only supported for symmetric key enrollment groups".format(
                        enrollment_type
                    )
                )
        return enrollment_group
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_group_create(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
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
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
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
                raise MutuallyExclusiveArgumentError(
                    "Please provide either certificate path or certficate name"
                )
            attestation = _get_attestation_with_x509_signing_cert(
                certificate_path, secondary_certificate_path
            )
        if root_ca_name or secondary_root_ca_name:
            if certificate_path or secondary_certificate_path:
                raise MutuallyExclusiveArgumentError(
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
        return sdk.enrollment_group.create_or_update(enrollment_id, group_enrollment)
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_group_update(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
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
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        enrollment_record = sdk.enrollment_group.get(enrollment_id)
        # Update enrollment information
        if enrollment_record.attestation.type == AttestationType.symmetricKey.value:
            enrollment_record.attestation = sdk.enrollment_group.get_attestation_mechanism(
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
                        raise RequiredArgumentMissingError("Please provide at least one certificate")

                    if not _can_remove_primary_certificate(
                        remove_certificate, enrollment_record.attestation
                    ):
                        raise RequiredArgumentMissingError(
                            "Please provide at least one certificate while removing the only primary certificate"
                        )

                    if not _can_remove_secondary_certificate(
                        remove_secondary_certificate, enrollment_record.attestation
                    ):
                        raise RequiredArgumentMissingError(
                            "Please provide at least one certificate while removing the only secondary certificate"
                        )

            if certificate_path or secondary_certificate_path:
                if root_ca_name or secondary_root_ca_name:
                    raise MutuallyExclusiveArgumentError(
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
                    raise MutuallyExclusiveArgumentError(
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
        return sdk.enrollment_group.create_or_update(
            enrollment_id, enrollment_record, if_match=(etag if etag else "*")
        )
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_device_enrollment_group_delete(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
    etag=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.enrollment_group.delete(enrollment_id, if_match=(etag if etag else "*"))
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_compute_device_key(
    cmd,
    registration_id,
    enrollment_id=None,
    dps_name=None,
    resource_group_name=None,
    symmetric_key=None,
    login=None,
    auth_type_dataplane=None,
):
    if symmetric_key is None:
        if not all([dps_name, enrollment_id]):
            raise RequiredArgumentMissingError(
                "Please provide DPS enrollment group identifiers (Device Provisioning Service name via "
                "--dps-name and Enrollment ID via --enrollment-id) or the enrollment group symmetric key "
                "via --symmetric-key or --key."
            )

        discovery = DPSDiscovery(cmd)
        target = discovery.get_target(
            dps_name,
            resource_group_name,
            login=login,
            auth_type=auth_type_dataplane,
        )
        try:
            resolver = SdkResolver(target=target)
            sdk = resolver.get_sdk(SdkType.dps_sdk)
            attestation = sdk.enrollment_group.get_attestation_mechanism(
                enrollment_id, raw=True
            ).response.json()
            if attestation.get("type") != AttestationType.symmetricKey.value:
                raise BadRequestError(
                    "Requested enrollment group has an attestation type of '{}'. Currently, compute-device-key "
                    "is only supported for enrollment groups with symmetric key attestation type.".format(
                        attestation.get("type")
                    )
                )
            symmetric_key = attestation["symmetricKey"]["primaryKey"]
        except ProvisioningServiceErrorDetailsException as e:
            raise AzureResponseError(e)

    return compute_device_key(
        primary_key=symmetric_key, registration_id=registration_id
    )


# DPS Connection strings


def iot_dps_connection_string_show(
    cmd,
    dps_name=None,
    resource_group_name=None,
    policy_name="provisioningserviceowner",
    key_type=KeyType.primary.value,
    show_all=False,
):
    discovery = DPSDiscovery(cmd)

    if dps_name is None:
        dps = discovery.get_resources(resource_group_name)
        if dps is None:
            raise ResourceNotFoundError("No Device Provisioning Service found.")

        def conn_str_getter(dps):
            return _get_dps_connection_string(
                discovery, dps, policy_name, key_type, show_all
            )

        connection_strings = []
        for dps in dps:
            if dps.properties.state == IoTDPSStateType.Active.value:
                try:
                    connection_strings.append(
                        {
                            "name": dps.name,
                            "connectionString": conn_str_getter(dps)
                            if show_all
                            else conn_str_getter(dps)[0],
                        }
                    )
                except Exception:
                    logger.warning(
                        f"Warning: The DPS {dps.name} in resource group "
                        + f"{dps.additional_properties['resourcegroup']} does "
                        + f"not have the target policy {policy_name}."
                    )
            else:
                logger.warning(
                    f"Warning: The DPS {dps.name} in resource group "
                    + f"{dps.additional_properties['resourcegroup']} is skipped "
                    + "because the DPS is not active."
                )
        return connection_strings

    dps = discovery.find_resource(dps_name, resource_group_name)
    if dps:
        conn_str = _get_dps_connection_string(
            discovery, dps, policy_name, key_type, show_all
        )
        return {"connectionString": conn_str if show_all else conn_str[0]}


def _get_dps_connection_string(
    discovery, dps, policy_name, key_type, show_all
):
    policies = []
    if show_all:
        policies.extend(
            discovery.get_policies(dps.name, dps.additional_properties["resourcegroup"])
        )
    else:
        policies.append(
            discovery.find_policy(
                dps.name, dps.additional_properties["resourcegroup"], policy_name
            )
        )

    hostname = dps.properties.service_operations_host_name
    return [
        IOT_SERVICE_CS_TEMPLATE.format(
            hostname,
            p.key_name,
            p.secondary_key if key_type == KeyType.secondary.value else p.primary_key,
        )
        for p in policies
    ]


# DPS Registration


def iot_dps_registration_list(
    cmd, enrollment_id, dps_name=None, resource_group_name=None, login=None, auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.device_registration_state.query(
            enrollment_id, raw=True
        ).response.json()
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_registration_get(
    cmd, registration_id, dps_name=None, resource_group_name=None, login=None, auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.device_registration_state.get(
            registration_id, raw=True
        ).response.json()
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_dps_registration_delete(
    cmd,
    registration_id,
    dps_name=None,
    resource_group_name=None,
    etag=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        resolver = SdkResolver(target=target)
        sdk = resolver.get_sdk(SdkType.dps_sdk)

        return sdk.device_registration_state.delete(registration_id, if_match=(etag if etag else "*"))
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


### Device commands


def iot_device_registration_create(
    cmd,
    registration_id,
    group_id=None,
    device_symmetric_key=None,
    group_symmetric_key=None,
    dps_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        if not device_symmetric_key and not group_id:
            enrollment = iot_dps_device_enrollment_get(
                cmd=cmd,
                enrollment_id=registration_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                show_keys=True,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )
            device_symmetric_key = enrollment["attestation"]["symmetricKey"]["primaryKey"]
        elif group_id:
            device_symmetric_key = iot_dps_compute_device_key(
                cmd=cmd,
                registration_id=registration_id,
                enrollment_id=group_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                symmetric_key=group_symmetric_key,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )
        return _dps_connect_device(
            device_id=registration_id,
            id_scope=target['idscope'],
            key=device_symmetric_key
        )
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_device_registration_show(
    cmd,
    registration_id,
    group_id=None,
    device_symmetric_key=None,
    group_symmetric_key=None,
    dps_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        if not device_symmetric_key and not group_id:
            enrollment = iot_dps_device_enrollment_get(
                cmd=cmd,
                enrollment_id=registration_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                show_keys=True,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )
            device_symmetric_key = enrollment["attestation"]["symmetricKey"]["primaryKey"]
        elif group_id:
            device_symmetric_key = iot_dps_compute_device_key(
                cmd=cmd,
                registration_id=registration_id,
                enrollment_id=group_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                symmetric_key=group_symmetric_key,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )

        credentials = SasTokenAuthentication(
            uri=f"{target['idscope']}/registrations/{registration_id}",
            shared_access_policy_name=None,
            shared_access_key=device_symmetric_key,
        )

        resolver = SdkResolver(target=target, auth_override=credentials)
        sdk = resolver.get_sdk(SdkType.dps_device_sdk)

        return sdk.runtime_registration.device_registration_status_lookup(
            registration_id=registration_id,
            device_registration={},
            id_scope=target["idscope"]
        )
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def iot_device_registration_operation_show(
    cmd,
    registration_id,
    operation_id,
    group_id=None,
    device_symmetric_key=None,
    group_symmetric_key=None,
    dps_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
):
    discovery = DPSDiscovery(cmd)
    target = discovery.get_target(
        dps_name,
        resource_group_name,
        login=login,
        auth_type=auth_type_dataplane,
    )
    try:
        if not device_symmetric_key and not group_id:
            enrollment = iot_dps_device_enrollment_get(
                cmd=cmd,
                enrollment_id=registration_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                show_keys=True,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )
            device_symmetric_key = enrollment["attestation"]["symmetricKey"]["primaryKey"]
        elif group_id:
            device_symmetric_key = iot_dps_compute_device_key(
                cmd=cmd,
                registration_id=registration_id,
                enrollment_id=group_id,
                dps_name=dps_name,
                resource_group_name=resource_group_name,
                symmetric_key=group_symmetric_key,
                login=login,
                auth_type_dataplane=auth_type_dataplane,
            )

        credentials = SasTokenAuthentication(
            uri=f"{target['idscope']}/registrations/{registration_id}",
            shared_access_policy_name=None,
            shared_access_key=device_symmetric_key,
        )

        resolver = SdkResolver(target=target, auth_override=credentials)
        sdk = resolver.get_sdk(SdkType.dps_device_sdk)
        #registration_id, operation_id, id_scope,
        return sdk.runtime_registration.operation_status_lookup(
            registration_id=registration_id,
            operation_id=operation_id,
            id_scope=target["idscope"]
        )
    except ProvisioningServiceErrorDetailsException as e:
        handle_service_exception(e)


def _dps_connect_device(device_id: str, id_scope: str, key: str):
    from azure.iot.device import ProvisioningDeviceClient
    from azure.iot.device.exceptions import ClientError

    provisioning_device_client = ProvisioningDeviceClient.create_from_symmetric_key(
        provisioning_host=GLOBAL_PROVISIONING_HOST,
        registration_id=device_id,
        id_scope=id_scope,
        symmetric_key=key,
    )
    try:
        registration_state = provisioning_device_client.register()
    except ClientError as e:
        error_msg = str(e.__cause__)
        if error_msg.endswith('200'):
            raise AzureResponseError(
                "Created registration but device was not assigned to an IoT Hub. Please ensure that "
                "there is at least one avaliable linked IoT Hub and try again."
            )
        elif error_msg.endswith('401'):
            raise UnauthorizedError("Could not create registration. Please check provided credentials.")
    # note: vars can be used but will need to have the _ parsed out
    # device sdk uses getattr instead
    return {
        "operation_id": registration_state.operation_id,
        "status": registration_state.status,
        "registration_state": {
            "device_id": registration_state.registration_state.device_id,
            "assigned_hub": registration_state.registration_state.assigned_hub,
            "sub_status": registration_state.registration_state.sub_status,
            "created_date_time": registration_state.registration_state.created_date_time,
            "last_update_date_time": registration_state.registration_state.last_update_date_time,
            "etag": registration_state.registration_state.etag,
            "response_payload": registration_state.registration_state.response_payload,

        },
    }


def _get_twin_collection(properties):
    """Convert a json into TwinCollection for use with the API."""
    from azext_iot.common.utility import dict_clean

    if properties == "":
        properties = None
    elif properties:
        properties = dict_clean(shell_safe_json_parse(str(properties)))

    return TwinCollection(additional_properties=properties)


def _get_initial_twin(initial_twin_tags=None, initial_twin_properties=None):
    """Build up Inital Twin using given tags and properties."""
    return InitialTwin(
        tags=_get_twin_collection(initial_twin_tags),
        properties=InitialTwinProperties(
            desired=_get_twin_collection(initial_twin_properties)
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
        raise RequiredArgumentMissingError("Please provide at least one certificate path")
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
            raise InvalidArgumentValueError("Invalid Reprovision Policy.")
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
            raise ArgumentUsageError(
                "Cannot update certificate while enrollment is using tpm attestation mechanism"
            )
        if remove_certificate or remove_secondary_certificate:
            raise ArgumentUsageError(
                "Cannot remove certificate while enrollment is using tpm attestation mechanism"
            )
        if primary_key or secondary_key:
            raise ArgumentUsageError(
                "Cannot update primary or secondary key while enrollment is using tpm attestation mechanism"
            )
    elif attestation_type == AttestationType.x509.value:
        if endorsement_key:
            raise ArgumentUsageError(
                "Cannot update endorsement key while enrollment is using x509 attestation mechanism"
            )
        if primary_key or secondary_key:
            raise ArgumentUsageError(
                "Cannot update primary or secondary key while enrollment is using x509 attestation mechanism"
            )
    else:
        if certificate_path or secondary_certificate_path:
            raise ArgumentUsageError(
                "Cannot update certificate while enrollment is using symmetric key attestation mechanism"
            )
        if remove_certificate or remove_secondary_certificate:
            raise ArgumentUsageError(
                "Cannot remove certificate while enrollment is using symmetric key attestation mechanism"
            )
        if endorsement_key:
            raise ArgumentUsageError(
                "Cannot update endorsement key while enrollment is using symmetric key attestation mechanism"
            )


def _validate_allocation_policy_for_enrollment(
    allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
):
    if allocation_policy:
        if iot_hub_host_name is not None:
            raise MutuallyExclusiveArgumentError(
                "'iot_hub_host_name' is not required when allocation-policy is defined."
            )
        # Code to ensure geolatency still works after the enum fix.
        if not any(
            allocation_policy == allocation.value for allocation in AllocationType
        ):
            raise RequiredArgumentMissingError("Please provide valid allocation policy.")
        if allocation_policy == AllocationType.static.value:
            if iot_hub_list is None:
                raise RequiredArgumentMissingError("Please provide a hub to be assigned with device.")
            if iot_hub_list and len(iot_hub_list) > 1:
                raise InvalidArgumentValueError("Only one hub is required in static allocation policy.")
        if allocation_policy == AllocationType.custom.value:
            if webhook_url is None or api_version is None:
                raise RequiredArgumentMissingError(
                    "Please provide both the Azure function webhook url and provisioning"
                    " service api-version when the allocation-policy is defined as Custom."
                )
    else:
        if iot_hub_list:
            raise RequiredArgumentMissingError("Please provide allocation policy.")
