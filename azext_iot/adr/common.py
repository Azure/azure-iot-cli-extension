# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum
from typing import Optional, Sequence

import isodate
from azure.cli.core.azclierror import InvalidArgumentValueError
from msrestazure.tools import is_valid_resource_id, parse_resource_id


class IdentityType(Enum):
    system_assigned = "SystemAssigned"
    user_assigned = "UserAssigned"


class ManagedServiceIdentityType(Enum):
    none = "None"
    system_assigned = "SystemAssigned"
    user_assigned = "UserAssigned"
    system_assigned_user_assigned = "SystemAssigned,UserAssigned"


class MessagingEndpointAvailability(Enum):
    available = "Available"
    disabled = "Disabled"


class GroupType(Enum):
    """Type of a Device Registry group.

    Only ``RegistryDevice`` is currently defined; the enum is kept forward-compatible
    so future group types can be added without churn.
    """
    registry_device = "RegistryDevice"


class RegistryDeviceEnablementState(Enum):
    enabled = "Enabled"
    disabled = "Disabled"


class RegistryDeviceAuthenticationType(Enum):
    certificate_authority_signed_x509_certificate = (
        "CertificateAuthoritySignedX509Certificate"
    )
    self_signed_x509_certificate = "SelfSignedX509Certificate"
    symmetric_key = "SymmetricKey"


class DeviceAttributeReportedType(Enum):
    """Cloud service that reports a Registry Device attribute.

    `Microsoft.DeviceUpdate` attributes are service-materialized; customers
    author `User` attributes.
    """

    adu = "Microsoft.DeviceUpdate"
    user = "User"


# Azure Device Update materializes its device attribute under this reserved ARM
# resource name. The name is service-owned: it is the URL path segment and is
# echoed back in the resource's `name` and `id`, so the CLI cannot rename it.
ADU_ATTRIBUTE_NAME = "update"


def is_adu_attribute_alias(attribute_name: str) -> bool:
    """Return True for the friendlier `software-update` spellings of `update`.

    `az iot adr ns registry-device attribute show` accepts these as an alias.
    Matching is case-insensitive and ignores `-` and `_`, so `software-update`,
    `software_update` and `softwareUpdate` all qualify.
    """
    normalized = attribute_name.replace("-", "").replace("_", "").lower()
    return normalized == "softwareupdate"


class JobType(Enum):
    software_update = "SoftwareUpdate"
    onboarding_update = "OnboardingUpdate"


class JobSchedulingType(Enum):
    continuous = "Continuous"


class ReportType(Enum):
    namespace_update_compliance = "NamespaceUpdateComplianceReport"
    group_best_updates_compliance = "GroupBestUpdatesComplianceReport"
    group_installable_updates = "GroupInstallableUpdatesReport"


class CertificateAuthorityType(Enum):
    root = "Root"
    ica = "ICA"


class CertificateAuthorityKeyType(Enum):
    ecc = "ECC"


class CertificateAuthorityIssuerType(Enum):
    microsoft = "Microsoft"
    external = "External"


# Endpoint type discriminators on Namespace messaging / provisioning / updating endpoints
IOT_HUB_ENDPOINT_TYPE = "Microsoft.Devices/IotHubs"
DPS_ENDPOINT_TYPE = "Microsoft.Devices/provisioningServices"
SU_ENDPOINT_TYPE = "Microsoft.DeviceUpdate/updateInstances"


DEFAULT_NS_CA_KEY_TYPE = CertificateAuthorityKeyType.ecc.value


def validate_uami_resource_id(resource_id: str) -> str:
    """Validate and return a user-assigned managed identity ARM ID."""
    if not is_valid_resource_id(resource_id):
        raise InvalidArgumentValueError(
            f"'{resource_id}' is not a valid user-assigned managed identity "
            "resource ID."
        )
    parsed = parse_resource_id(resource_id)
    if (
        (parsed.get("namespace") or "").lower()
        != "microsoft.managedidentity"
        or (parsed.get("type") or "").lower() != "userassignedidentities"
        or "child_name_1" in parsed
    ):
        raise InvalidArgumentValueError(
            f"'{resource_id}' is not a Microsoft.ManagedIdentity/"
            "userAssignedIdentities resource ID."
        )
    return resource_id


def build_managed_service_identity(
    system_assigned: Optional[bool],
    user_assigned_identities: Optional[Sequence[str]],
) -> Optional[dict]:
    """Build the complete desired ARM managed identity state."""
    identities = {}
    for resource_id in user_assigned_identities or []:
        validated_id = validate_uami_resource_id(resource_id)
        identities.setdefault(validated_id.rstrip("/").casefold(), validated_id)

    if system_assigned is None and not identities:
        return None
    if system_assigned and identities:
        identity_type = ManagedServiceIdentityType.system_assigned_user_assigned.value
    elif system_assigned:
        identity_type = ManagedServiceIdentityType.system_assigned.value
    elif identities:
        identity_type = ManagedServiceIdentityType.user_assigned.value
    else:
        identity_type = ManagedServiceIdentityType.none.value

    identity = {"type": identity_type}
    if identities:
        identity["userAssignedIdentities"] = {
            resource_id: {} for resource_id in identities.values()
        }
    return identity


def build_mi_body(
    mi_system_assigned: Optional[bool],
    mi_user_assigned: Optional[str],
    *,
    sami_type: str,
    uami_type: str,
) -> Optional[dict]:
    """Build a managed-identity body dict, or None if neither flag is set.

    Shared by the link endpoint (InboundCallerIdentity) and namespace
    (OutboundIdentity) surfaces. Callers are responsible for SAMI/UAMI mutex
    enforcement, required-argument checks, and any surface-specific UAMI
    restrictions (the contracts vary).

    Empty/whitespace ``mi_user_assigned`` is treated as "not provided" so a
    stray ``--…-mi-user-assigned ""`` does not emit a malformed body.
    """
    if mi_user_assigned is not None and not mi_user_assigned.strip():
        mi_user_assigned = None
    if mi_user_assigned:
        return {"type": uami_type, "userAssignedIdentity": mi_user_assigned}
    if mi_system_assigned:
        return {"type": sami_type}
    return None


CA_PARENT_RESOURCE_NOT_FOUND_MSG = (
    "No certificate authority '{certificate_authority_name}' exists on namespace '{namespace_name}' "
    "in resource group '{resource_group_name}'. "
    "Please create one using 'az iot adr ns ca create --name {certificate_authority_name} "
    "--ns {namespace_name} -g {resource_group_name}' to manage certificate policies."
)


def compose_namespace_child_arm_id(
    subscription_id: str,
    resource_group_name: str,
    namespace_name: str,
    child_type: str,
    child_name: str,
) -> str:
    """Compose the ARM resource ID for a Device Registry namespace child resource.

    ``child_type`` is the resource type segment as it appears in the ARM path,
    e.g. ``groups`` or ``certificateAuthorities``.
    """
    return (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group_name}"
        f"/providers/Microsoft.DeviceRegistry"
        f"/namespaces/{namespace_name}"
        f"/{child_type}/{child_name}"
    )


INVALID_SCHEDULED_TIME_MSG = (
    "--scheduled-time must be a valid ISO 8601 UTC datetime (e.g. '2025-12-01T08:00:00Z'). "
    "Provided value: '{value}'."
)


def validate_iso8601_datetime(value: str) -> None:
    """Validate that *value* is an absolute ISO 8601 datetime string.

    The service requires an absolute time, so a timezone offset is mandatory.
    """
    try:
        parsed = isodate.parse_datetime(value)
        if parsed.utcoffset() is None:
            raise ValueError("timezone offset is required")
    except Exception:  # noqa: BLE001 - any parse error is invalid input
        raise InvalidArgumentValueError(INVALID_SCHEDULED_TIME_MSG.format(value=value))
