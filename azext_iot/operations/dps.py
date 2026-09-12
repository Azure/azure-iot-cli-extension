# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import re

from knack.log import get_logger
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    BadRequestError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError
from azext_iot.common._azure import IOT_SERVICE_CS_TEMPLATE
from azext_iot.common.shared import (
    SdkType,
    AttestationType,
    ReprovisionType,
    AllocationType,
    KeyType,
    IoTDPSStateType
)
from azext_iot.common.arm import get_resource_group
from azext_iot.common.utility import compute_device_key, shell_safe_json_parse
from azext_iot.common.certops import open_certificate
from azext_iot.dps.services._enrollment import handle_service_error as handle_service_exception
from azext_iot.dps.services._enrollment_errors import handle_enrollment_error
from azext_iot.dps.services._enrollment_output import enrollment_group_output
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot._factory import SdkResolver

logger = get_logger(__name__)


def _drop_none(value):
    if isinstance(value, dict):
        return {
            key: _drop_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _clean_twin_collection(collection):
    if not isinstance(collection, dict):
        return {}
    readonly = {"$metadata", "$version", "count", "metadata", "version"}
    return {
        key: value
        for key, value in collection.items()
        if key not in readonly
    }


def _drop_readonly_enrollment(enrollment):
    """Remove service-owned fields, retaining info-only X.509 certificate identities."""
    result = deepcopy(enrollment)
    for key in (
        "createdDateTimeUtc",
        "lastUpdatedDateTimeUtc",
        "registrationState",
        "etag",
    ):
        result.pop(key, None)

    initial_twin = result.get("initialTwin") or {}
    if initial_twin:
        initial_twin["tags"] = _clean_twin_collection(initial_twin.get("tags"))
        properties = initial_twin.setdefault("properties", {})
        properties["desired"] = _clean_twin_collection(properties.get("desired"))

    if "optionalDeviceInformation" in result:
        result["optionalDeviceInformation"] = _clean_twin_collection(
            result.get("optionalDeviceInformation")
        )

    return _drop_none(result)


def _etag_arguments(etag=None):
    if etag:
        return {"etag": etag, "match_condition": MatchConditions.IfNotModified}
    return {"match_condition": MatchConditions.IfPresent}


def _execute_dps_query(query_method, query_args, top=None):
    """Execute a modeless DPS query while following continuation headers."""
    if top is not None and (isinstance(top, bool) or not isinstance(top, int) or top < 0):
        raise InvalidArgumentValueError("--top must be a non-negative integer.")
    payload = []
    continuation = None
    seen = set()

    def capture(pipeline_response, value, _headers):
        return value, pipeline_response.http_response.headers

    while top is None or len(payload) < top:
        max_items = None if top is None else top - len(payload)
        page, headers = query_method(
            *query_args,
            x_ms_max_item_count=max_items,
            x_ms_continuation=continuation,
            headers={"Cache-Control": "no-cache, must-revalidate"},
            cls=capture,
        )
        if not isinstance(page, list):
            raise AzureResponseError("DPS query returned an invalid page; expected a JSON array.")
        payload.extend(page if top is None else page[:top - len(payload)])
        continuation = headers.get("x-ms-continuation")
        if not continuation:
            break
        if continuation in seen:
            raise AzureResponseError("DPS query returned a repeated continuation token.")
        seen.add(continuation)
    return payload


def _validate_adr_certificate_reference(
    adr_namespace=None,
    adr_ca_name=None,
    adr_certificate_policy_name=None,
    credential_policy_name=None,
):
    """Validate and return the 2026-11-02 ADR certificate reference fields."""
    if (
        adr_certificate_policy_name is not None and credential_policy_name is not None
        and adr_certificate_policy_name != credential_policy_name
    ):
        raise MutuallyExclusiveArgumentError("Conflicting canonical and legacy certificate policy names.")
    policy_name = adr_certificate_policy_name if adr_certificate_policy_name is not None else credential_policy_name
    supplied = [adr_namespace, adr_ca_name, policy_name]
    if all(value is None for value in supplied):
        return {}
    if all(value == "" for value in supplied):
        return {"namespaceName": None, "certificateAuthorityName": None, "certificatePolicyName": None}
    if not all(supplied):
        raise RequiredArgumentMissingError(
            "ADR certificate enrollment requires --adr-namespace, --adr-ca-name, "
            "and --adr-cert-policy-name together."
        )
    for index, value in enumerate(supplied):
        namespace = index == 0
        pattern = r"[a-z0-9][a-z0-9-]*[a-z0-9]" if namespace else r"[0-9a-zA-Z][a-zA-Z0-9-]*"
        if not isinstance(value, str) or not 3 <= len(value) <= (64 if namespace else 63) or not re.fullmatch(pattern, value):
            raise InvalidArgumentValueError("Invalid ADR certificate reference name.")
    return {
        "namespaceName": adr_namespace,
        "certificateAuthorityName": adr_ca_name,
        "certificatePolicyName": policy_name,
    }


# DPS Enrollments


def iot_dps_device_enrollment_list(
    cmd,
    dps_name=None,
    resource_group_name=None,
    top=None,
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

        return _execute_dps_query(
            sdk.individual_enrollment.query, [{"query": "SELECT *"}], top
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "list enrollments", handle_service_exception)


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

        enrollment = sdk.individual_enrollment.get(enrollment_id)
        if show_keys:
            enrollment_type = enrollment["attestation"]["type"]
            if enrollment_type == AttestationType.symmetricKey.value:
                attestation = sdk.individual_enrollment.get_attestation_mechanism(
                    enrollment_id
                )
                enrollment["attestation"] = attestation
            else:
                logger.warning(
                    "--show-keys argument was provided, but requested enrollment has an attestation type of '{}'."
                    " Currently, --show-keys is only supported for symmetric key enrollments".format(
                        enrollment_type
                    )
                )
        return enrollment
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "show enrollment", handle_service_exception)


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
    adr_namespace=None,
    adr_ca_name=None,
    adr_certificate_policy_name=None,
    credential_policy_name=None,
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

        attestation = None
        if attestation_type == AttestationType.tpm.value:
            if not endorsement_key:
                raise RequiredArgumentMissingError("Endorsement key [--endorsement-key] is required")
            attestation = {
                "type": AttestationType.tpm.value,
                "tpm": {"endorsementKey": endorsement_key},
            }
        if attestation_type == AttestationType.x509.value:
            attestation = _get_attestation_with_x509_client_cert(
                certificate_path, secondary_certificate_path
            )
        if attestation_type == AttestationType.symmetricKey.value:
            attestation = {
                "type": AttestationType.symmetricKey.value,
                "symmetricKey": {
                    "primaryKey": primary_key,
                    "secondaryKey": secondary_key,
                },
            }
        reprovision = _get_reprovision_policy(reprovision_policy)
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        iot_hub_list = iot_hubs.split() if isinstance(iot_hubs, str) else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if iot_hub_host_name and allocation_policy is None:
            allocation_policy = AllocationType.static.value
            iot_hub_list = iot_hub_host_name.split()

        custom_allocation_definition = (
            {"webhookUrl": webhook_url, "apiVersion": api_version}
            if allocation_policy == AllocationType.custom.value
            else None
        )
        enrollment = {
            "registrationId": enrollment_id,
            "attestation": attestation,
            "capabilities": {"iotEdge": edge_enabled},
            "deviceId": device_id,
            "initialTwin": initial_twin,
            "provisioningStatus": provisioning_status,
            "reprovisionPolicy": reprovision,
            "allocationPolicy": allocation_policy,
            "iotHubs": iot_hub_list,
            "customAllocationDefinition": custom_allocation_definition,
            "optionalDeviceInformation": _get_twin_collection(device_information),
            **_validate_adr_certificate_reference(
                adr_namespace,
                adr_ca_name,
                adr_certificate_policy_name,
                credential_policy_name,
            ),
        }
        enrollment = _drop_none(enrollment)
        return sdk.individual_enrollment.create_or_update(enrollment_id, enrollment)
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "create enrollment", handle_service_exception)


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
    adr_namespace=None,
    adr_ca_name=None,
    adr_certificate_policy_name=None,
    credential_policy_name=None,
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
        attestation_type = (enrollment_record.get("attestation") or {}).get("type")
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
                enrollment_record["attestation"]["tpm"]["endorsementKey"] = endorsement_key
        elif attestation_type == AttestationType.x509.value:
            enrollment_record["attestation"] = _get_updated_attestation_with_x509_client_cert(
                enrollment_record["attestation"],
                certificate_path,
                secondary_certificate_path,
                remove_certificate,
                remove_secondary_certificate,
            )
        else:
            enrollment_record["attestation"] = sdk.individual_enrollment.get_attestation_mechanism(
                enrollment_id
            )
            if primary_key:
                enrollment_record["attestation"]["symmetricKey"]["primaryKey"] = primary_key
            if secondary_key:
                enrollment_record["attestation"]["symmetricKey"]["secondaryKey"] = secondary_key
        # Update enrollment information
        if iot_hub_host_name:
            enrollment_record["allocationPolicy"] = AllocationType.static.value
            enrollment_record["iotHubs"] = iot_hub_host_name.split()
            enrollment_record.pop("iotHubHostName", None)
        if device_id:
            enrollment_record["deviceId"] = device_id
        if provisioning_status:
            enrollment_record["provisioningStatus"] = provisioning_status
        enrollment_record.pop("registrationState", None)
        if reprovision_policy:
            enrollment_record["reprovisionPolicy"] = _get_reprovision_policy(
                reprovision_policy
            )
        enrollment_record["initialTwin"] = _get_updated_inital_twin(
            enrollment_record, initial_twin_tags, initial_twin_properties
        )
        iot_hub_list = iot_hubs.split() if isinstance(iot_hubs, str) else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy,
            iot_hub_host_name,
            iot_hub_list,
            webhook_url,
            api_version,
            current_enrollment=enrollment_record
        )
        if iot_hub_list:
            enrollment_record["iotHubs"] = iot_hub_list
            enrollment_record.pop("iotHubHostName", None)
        if allocation_policy:
            enrollment_record["allocationPolicy"] = allocation_policy
        if enrollment_record.get("allocationPolicy") == AllocationType.custom.value and any([
            webhook_url, api_version
        ]):
            current_custom = enrollment_record.get("customAllocationDefinition") or {}
            enrollment_record["customAllocationDefinition"] = {
                "webhookUrl": webhook_url or current_custom.get("webhookUrl"),
                "apiVersion": api_version or current_custom.get("apiVersion"),
            }
        if edge_enabled is not None:
            enrollment_record["capabilities"] = {"iotEdge": edge_enabled}
        if device_information:
            enrollment_record["optionalDeviceInformation"] = _get_twin_collection(device_information)

        reference_supplied = any(
            value is not None
            for value in (
                adr_namespace,
                adr_ca_name,
                adr_certificate_policy_name,
                credential_policy_name,
            )
        )
        if reference_supplied:
            enrollment_record.pop("credentialPolicyName", None)
            enrollment_record.update(
                _validate_adr_certificate_reference(
                    (
                        adr_namespace
                        if adr_namespace is not None
                        else enrollment_record.get("namespaceName")
                    ),
                    (
                        adr_ca_name
                        if adr_ca_name is not None
                        else enrollment_record.get("certificateAuthorityName")
                    ),
                    (
                        adr_certificate_policy_name
                        if adr_certificate_policy_name is not None
                        else (
                            credential_policy_name
                            if credential_policy_name is not None
                            else enrollment_record.get("certificatePolicyName")
                        )
                    ),
                    credential_policy_name,
                )
            )

        return sdk.individual_enrollment.create_or_update(
            enrollment_id, _drop_readonly_enrollment(enrollment_record), **_etag_arguments(etag)
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "update enrollment", handle_service_exception)


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

        return sdk.individual_enrollment.delete(
            enrollment_id, **_etag_arguments(etag)
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "delete enrollment", handle_service_exception)


# DPS Enrollments Group


def iot_dps_device_enrollment_group_list(
    cmd, dps_name=None, resource_group_name=None, top=None, login=None, auth_type_dataplane=None,
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

        return _execute_dps_query(
            sdk.enrollment_group.query, [{"query": "SELECT *"}], top
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "list enrollment groups", handle_service_exception)


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

        enrollment_group = sdk.enrollment_group.get(enrollment_id)
        if show_keys:
            enrollment_type = enrollment_group["attestation"]["type"]
            if enrollment_type == AttestationType.symmetricKey.value:
                attestation = sdk.enrollment_group.get_attestation_mechanism(
                    enrollment_id
                )
                enrollment_group["attestation"] = attestation
            else:
                logger.warning(
                    "--show-keys argument was provided, but requested enrollment group has an attestation type of '{}'."
                    " Currently, --show-keys is only supported for symmetric key enrollment groups".format(
                        enrollment_type
                    )
                )
        return enrollment_group_output(enrollment_group, show_keys)
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "show enrollment group", handle_service_exception)


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
    adr_namespace=None,
    adr_ca_name=None,
    adr_certificate_policy_name=None,
    credential_policy_name=None,
    api_version=None,
    login=None,
    auth_type_dataplane=None,
    show_keys=False,
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

        attestation = None
        if not certificate_path and not secondary_certificate_path:
            if not root_ca_name and not secondary_root_ca_name:
                attestation = {
                    "type": AttestationType.symmetricKey.value,
                    "symmetricKey": {
                        "primaryKey": primary_key,
                        "secondaryKey": secondary_key,
                    },
                }
        if certificate_path or secondary_certificate_path:
            if root_ca_name or secondary_root_ca_name:
                raise MutuallyExclusiveArgumentError(
                    "Please provide either certificate path or certficate name"
                )
            attestation = _get_attestation_with_x509_signing_cert(
                certificate_path, secondary_certificate_path
            )
        if root_ca_name or secondary_root_ca_name:
            attestation = _get_attestation_with_x509_ca_cert(
                root_ca_name, secondary_root_ca_name
            )
        reprovision = _get_reprovision_policy(reprovision_policy)
        initial_twin = _get_initial_twin(initial_twin_tags, initial_twin_properties)
        iot_hub_list = iot_hubs.split() if isinstance(iot_hubs, str) else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version
        )
        if iot_hub_host_name and allocation_policy is None:
            allocation_policy = AllocationType.static.value
            iot_hub_list = iot_hub_host_name.split()

        custom_allocation_definition = (
            {"webhookUrl": webhook_url, "apiVersion": api_version}
            if allocation_policy == AllocationType.custom.value
            else None
        )

        group_enrollment = {
            "enrollmentGroupId": enrollment_id,
            "attestation": attestation,
            "capabilities": {"iotEdge": edge_enabled},
            "initialTwin": initial_twin,
            "provisioningStatus": provisioning_status,
            "reprovisionPolicy": reprovision,
            "allocationPolicy": allocation_policy,
            "iotHubs": iot_hub_list,
            "customAllocationDefinition": custom_allocation_definition,
            **_validate_adr_certificate_reference(
                adr_namespace,
                adr_ca_name,
                adr_certificate_policy_name,
                credential_policy_name,
            ),
        }
        return enrollment_group_output(
            sdk.enrollment_group.create_or_update(enrollment_id, _drop_none(group_enrollment)), show_keys
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "create enrollment group", handle_service_exception)


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
    adr_namespace=None,
    adr_ca_name=None,
    adr_certificate_policy_name=None,
    credential_policy_name=None,
    api_version=None,
    login=None,
    auth_type_dataplane=None,
    show_keys=False,
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
        if enrollment_record["attestation"]["type"] == AttestationType.symmetricKey.value:
            enrollment_record["attestation"] = sdk.enrollment_group.get_attestation_mechanism(
                enrollment_id
            )
            if primary_key:
                enrollment_record["attestation"]["symmetricKey"]["primaryKey"] = primary_key
            if secondary_key:
                enrollment_record["attestation"]["symmetricKey"]["secondaryKey"] = secondary_key

        if enrollment_record["attestation"]["type"] == AttestationType.x509.value:
            if not certificate_path and not secondary_certificate_path:
                if not root_ca_name and not secondary_root_ca_name:
                    # Check if certificate can be safely removed while no new certificate has been provided
                    if remove_certificate and remove_secondary_certificate:
                        raise RequiredArgumentMissingError("Please provide at least one certificate")

                    if not _can_remove_primary_certificate(
                        remove_certificate, enrollment_record["attestation"]
                    ):
                        raise RequiredArgumentMissingError(
                            "Please provide at least one certificate while removing the only primary certificate"
                        )

                    if not _can_remove_secondary_certificate(
                        remove_secondary_certificate, enrollment_record["attestation"]
                    ):
                        raise RequiredArgumentMissingError(
                            "Please provide at least one certificate while removing the only secondary certificate"
                        )

            if certificate_path or secondary_certificate_path or (
                (remove_certificate or remove_secondary_certificate)
                and not (root_ca_name or secondary_root_ca_name)
                and "signingCertificates" in enrollment_record["attestation"].get("x509", {})
            ):
                if root_ca_name or secondary_root_ca_name:
                    raise MutuallyExclusiveArgumentError(
                        "Please provide either certificate path or certficate name"
                    )
                enrollment_record["attestation"] = _get_updated_attestation_with_x509_signing_cert(
                    enrollment_record["attestation"],
                    certificate_path,
                    secondary_certificate_path,
                    remove_certificate,
                    remove_secondary_certificate,
                )
            if root_ca_name or secondary_root_ca_name or (
                (remove_certificate or remove_secondary_certificate)
                and not (certificate_path or secondary_certificate_path)
                and "caReferences" in enrollment_record["attestation"].get("x509", {})
            ):
                enrollment_record["attestation"] = _get_updated_attestation_with_x509_ca_cert(
                    enrollment_record["attestation"],
                    root_ca_name,
                    secondary_root_ca_name,
                    remove_certificate,
                    remove_secondary_certificate,
                )
        if iot_hub_host_name:
            enrollment_record["allocationPolicy"] = AllocationType.static.value
            enrollment_record["iotHubs"] = iot_hub_host_name.split()
            enrollment_record.pop("iotHubHostName", None)
        if provisioning_status:
            enrollment_record["provisioningStatus"] = provisioning_status
        if reprovision_policy:
            enrollment_record["reprovisionPolicy"] = _get_reprovision_policy(
                reprovision_policy
            )
        enrollment_record["initialTwin"] = _get_updated_inital_twin(
            enrollment_record, initial_twin_tags, initial_twin_properties
        )
        iot_hub_list = iot_hubs.split() if isinstance(iot_hubs, str) else iot_hubs
        _validate_allocation_policy_for_enrollment(
            allocation_policy,
            iot_hub_host_name,
            iot_hub_list,
            webhook_url,
            api_version,
            current_enrollment=enrollment_record
        )
        if iot_hub_list:
            enrollment_record["iotHubs"] = iot_hub_list
            enrollment_record.pop("iotHubHostName", None)
        if allocation_policy:
            enrollment_record["allocationPolicy"] = allocation_policy
        if enrollment_record.get("allocationPolicy") == AllocationType.custom.value and any([
            webhook_url, api_version
        ]):
            current_custom = enrollment_record.get("customAllocationDefinition") or {}
            enrollment_record["customAllocationDefinition"] = {
                "webhookUrl": webhook_url or current_custom.get("webhookUrl"),
                "apiVersion": api_version or current_custom.get("apiVersion"),
            }
        if edge_enabled is not None:
            enrollment_record["capabilities"] = {"iotEdge": edge_enabled}
        if any(
            value is not None
            for value in (
                adr_namespace,
                adr_ca_name,
                adr_certificate_policy_name,
                credential_policy_name,
            )
        ):
            enrollment_record.pop("credentialPolicyName", None)
            enrollment_record.update(
                _validate_adr_certificate_reference(
                    (
                        adr_namespace
                        if adr_namespace is not None
                        else enrollment_record.get("namespaceName")
                    ),
                    (
                        adr_ca_name
                        if adr_ca_name is not None
                        else enrollment_record.get("certificateAuthorityName")
                    ),
                    (
                        adr_certificate_policy_name
                        if adr_certificate_policy_name is not None
                        else (
                            credential_policy_name
                            if credential_policy_name is not None
                            else enrollment_record.get("certificatePolicyName")
                        )
                    ),
                    credential_policy_name,
                )
            )
        return enrollment_group_output(
            sdk.enrollment_group.create_or_update(
                enrollment_id, _drop_readonly_enrollment(enrollment_record), **_etag_arguments(etag),
            ),
            show_keys,
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "update enrollment group", handle_service_exception)


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

        return sdk.enrollment_group.delete(
            enrollment_id, **_etag_arguments(etag)
        )
    except HttpResponseError as e:
        handle_enrollment_error(e, target, "delete enrollment group", handle_service_exception)


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
                enrollment_id
            )
            if attestation.get("type") != AttestationType.symmetricKey.value:
                raise BadRequestError(
                    "Requested enrollment group has an attestation type of '{}'. Currently, compute-device-key "
                    "is only supported for enrollment groups with symmetric key attestation type.".format(
                        attestation.get("type")
                    )
                )
            symmetric_key = attestation["symmetricKey"]["primaryKey"]
        except HttpResponseError as e:
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
                discovery,
                dps,
                policy_name,
                key_type,
                show_all,
                resource_group_name=resource_group_name,
            )

        connection_strings = []
        for dps in dps:
            dps_resource_group = get_resource_group(
                dps,
                fallback=resource_group_name,
                resource_label="DPS",
            )
            if dps["properties"]["state"] == IoTDPSStateType.Active.value:
                try:
                    connection_strings.append(
                        {
                            "name": dps["name"],
                            "connectionString": conn_str_getter(dps)
                            if show_all
                            else conn_str_getter(dps)[0],
                        }
                    )
                except Exception:
                    logger.warning(
                        f"Warning: The DPS {dps['name']} in resource group "
                        + f"{dps_resource_group} does "
                        + f"not have the target policy {policy_name}."
                    )
            else:
                logger.warning(
                    f"Warning: The DPS {dps['name']} in resource group "
                    + f"{dps_resource_group} is skipped "
                    + "because the DPS is not active."
                )
        return connection_strings

    dps = discovery.find_resource(dps_name, resource_group_name)
    if dps:
        conn_str = _get_dps_connection_string(
            discovery,
            dps,
            policy_name,
            key_type,
            show_all,
            resource_group_name=resource_group_name,
        )
        return {"connectionString": conn_str if show_all else conn_str[0]}


def _get_dps_connection_string(
    discovery,
    dps,
    policy_name,
    key_type,
    show_all,
    resource_group_name=None,
):
    policies = []
    dps_resource_group = get_resource_group(
        dps,
        fallback=resource_group_name,
        resource_label="DPS",
    )
    if show_all:
        policies.extend(
            discovery.get_policies(dps["name"], dps_resource_group)
        )
    else:
        policies.append(
            discovery.find_policy(
                dps["name"], dps_resource_group, policy_name
            )
        )

    hostname = dps["properties"]["serviceOperationsHostName"]
    return [
        IOT_SERVICE_CS_TEMPLATE.format(
            hostname,
            p["keyName"],
            p["secondaryKey"] if key_type == KeyType.secondary.value else p["primaryKey"],
        )
        for p in policies
    ]


# DPS Registration
def iot_dps_registration_list(
    cmd,
    enrollment_id,
    dps_name=None,
    resource_group_name=None,
    top=None,
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
        return _execute_dps_query(
            sdk.device_registration_state.query, [enrollment_id], top
        )
    except HttpResponseError as e:
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

        return sdk.device_registration_state.get(registration_id)
    except HttpResponseError as e:
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

        return sdk.device_registration_state.delete(
            registration_id, **_etag_arguments(etag)
        )
    except HttpResponseError as e:
        handle_service_exception(e)


def _get_twin_collection(properties):
    """Convert shell JSON into the raw mapping expected by the modeless SDK."""
    from azext_iot.common.utility import dict_clean

    if properties == "":
        return {}
    elif properties:
        properties = dict_clean(shell_safe_json_parse(str(properties)))
    return properties or {}


def _get_initial_twin(initial_twin_tags=None, initial_twin_properties=None):
    """Build up Inital Twin using given tags and properties."""
    return {
        "tags": _get_twin_collection(initial_twin_tags),
        "properties": {
            "desired": _get_twin_collection(initial_twin_properties)
        },
    }


def _get_updated_inital_twin(
    enrollment_record, initial_twin_tags=None, initial_twin_properties=None
):
    # in both cases, we want to grab the original tags and properties
    # if the parameters are not provided. The user should be able to
    # empty out tags/properties by passing in an empty string.
    current_twin = enrollment_record.get("initialTwin") or {}
    if initial_twin_tags is None:
        initial_twin_tags = _clean_twin_collection(current_twin.get("tags"))
    if initial_twin_properties is None:
        initial_twin_properties = _clean_twin_collection(
            (current_twin.get("properties") or {}).get("desired")
        )
    result = deepcopy(current_twin)
    result["tags"] = _get_twin_collection(initial_twin_tags)
    properties = result.get("properties") or {}
    properties["desired"] = _get_twin_collection(initial_twin_properties)
    result["properties"] = properties
    return result


def _get_x509_certificate(certificate_path, secondary_certificate_path):
    return _drop_none(
        {
            "primary": _get_certificate_info(certificate_path),
            "secondary": _get_certificate_info(secondary_certificate_path),
        }
    )


def _get_certificate_info(certificate_path):
    if not certificate_path:
        return None
    certificate_content = open_certificate(certificate_path)
    return {"certificate": certificate_content}


def _get_attestation_with_x509_client_cert(
    primary_certificate_path, secondary_certificate_path
):
    if not primary_certificate_path and not secondary_certificate_path:
        raise RequiredArgumentMissingError("Please provide at least one certificate path")
    certificate = _get_x509_certificate(
        primary_certificate_path, secondary_certificate_path
    )
    return {
        "type": AttestationType.x509.value,
        "x509": {"clientCertificates": certificate},
    }


def _get_updated_attestation_with_x509_client_cert(
    attestation,
    primary_certificate_path,
    secondary_certificate_path,
    remove_primary_certificate,
    remove_secondary_certificate,
):
    client_certificates = (
        attestation.setdefault("x509", {}).setdefault("clientCertificates", {})
    )
    if remove_primary_certificate:
        client_certificates.pop("primary", None)
    if remove_secondary_certificate:
        client_certificates.pop("secondary", None)
    if primary_certificate_path:
        client_certificates["primary"] = _get_certificate_info(primary_certificate_path)
    if secondary_certificate_path:
        client_certificates["secondary"] = _get_certificate_info(secondary_certificate_path)
    return attestation


def _get_attestation_with_x509_signing_cert(
    primary_certificate_path, secondary_certificate_path
):
    certificate = _get_x509_certificate(
        primary_certificate_path, secondary_certificate_path
    )
    return {
        "type": AttestationType.x509.value,
        "x509": {"signingCertificates": certificate},
    }


def _get_attestation_with_x509_ca_cert(root_ca_name, secondary_root_ca_name):
    certificate = _drop_none(
        {"primary": root_ca_name, "secondary": secondary_root_ca_name}
    )
    return {
        "type": AttestationType.x509.value,
        "x509": {"caReferences": certificate},
    }


def _get_updated_attestation_with_x509_signing_cert(
    attestation,
    primary_certificate_path,
    secondary_certificate_path,
    remove_primary_certificate,
    remove_secondary_certificate,
):
    signing_certificates = (attestation.get("x509") or {}).get(
        "signingCertificates"
    )
    if signing_certificates is not None:
        if remove_primary_certificate:
            signing_certificates.pop("primary", None)
        if remove_secondary_certificate:
            signing_certificates.pop("secondary", None)
        if primary_certificate_path:
            signing_certificates["primary"] = _get_certificate_info(primary_certificate_path)
        if secondary_certificate_path:
            signing_certificates["secondary"] = _get_certificate_info(secondary_certificate_path)
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
    ca_references = (attestation.get("x509") or {}).get("caReferences")
    if ca_references is not None:
        if remove_primary_certificate:
            ca_references.pop("primary", None)
        if remove_secondary_certificate:
            ca_references.pop("secondary", None)
        if root_ca_name:
            ca_references["primary"] = root_ca_name
        if secondary_root_ca_name:
            ca_references["secondary"] = secondary_root_ca_name
        return attestation
    return _get_attestation_with_x509_ca_cert(root_ca_name, secondary_root_ca_name)


def _can_remove_primary_certificate(remove_certificate, attestation):
    if remove_certificate:
        x509 = attestation.get("x509") or {}
        if "signingCertificates" in x509:
            if not (x509.get("signingCertificates") or {}).get("secondary"):
                return False
        if "caReferences" in x509:
            if not (x509.get("caReferences") or {}).get("secondary"):
                return False
    return True


def _can_remove_secondary_certificate(remove_certificate, attestation):
    if remove_certificate:
        x509 = attestation.get("x509") or {}
        if "signingCertificates" in x509:
            if not (x509.get("signingCertificates") or {}).get("primary"):
                return False
        if "caReferences" in x509:
            if not (x509.get("caReferences") or {}).get("primary"):
                return False
    return True


def _get_reprovision_policy(reprovision_policy):
    if reprovision_policy:
        if reprovision_policy == ReprovisionType.reprovisionandmigratedata.value:
            reprovision = {
                "updateHubAssignment": True,
                "migrateDeviceData": True,
            }
        elif reprovision_policy == ReprovisionType.reprovisionandresetdata.value:
            reprovision = {
                "updateHubAssignment": True,
                "migrateDeviceData": False,
            }
        elif reprovision_policy == ReprovisionType.never.value:
            reprovision = {
                "updateHubAssignment": False,
                "migrateDeviceData": False,
            }
        else:
            raise InvalidArgumentValueError("Invalid Reprovision Policy.")
    else:
        reprovision = {
            "updateHubAssignment": True,
            "migrateDeviceData": True,
        }
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
    allocation_policy, iot_hub_host_name, iot_hub_list, webhook_url, api_version, current_enrollment=None
):
    explicitly_selected_policy = allocation_policy is not None
    # get the enrollment values if not provided but present
    if current_enrollment:
        iot_hub_list = iot_hub_list or current_enrollment.get("iotHubs")
        allocation_policy = allocation_policy or current_enrollment.get(
            "allocationPolicy"
        )
        if current_enrollment.get("allocationPolicy") == AllocationType.custom.value:
            custom = current_enrollment.get("customAllocationDefinition") or {}
            webhook_url = webhook_url or custom.get("webhookUrl")
            api_version = api_version or custom.get("apiVersion")

    if allocation_policy:
        if explicitly_selected_policy and iot_hub_host_name is not None:
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
    elif iot_hub_list and not current_enrollment:
        raise RequiredArgumentMissingError("Please provide allocation policy.")
