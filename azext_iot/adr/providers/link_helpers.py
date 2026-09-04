# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Pure parsing and serialization helpers for namespace links."""

from copy import deepcopy
from typing import Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from msrestazure.tools import is_valid_resource_id, parse_resource_id

from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
    IdentityType,
    build_mi_body,
    validate_uami_resource_id,
)
from azext_iot.adr.topology import (
    get_endpoints,
    writable_namespace_properties,
)

MI_MUTEX_MSG = (
    "Specify only one linked-resource identity: use --system-assigned-mi for "
    "its system-assigned identity, or --user-assigned-mi "
    "<uami-resource-id> for a user-assigned identity attached to that resource."
)

MI_REQUIRED_MSG = (
    "An inbound caller identity is required from the linked resource. Pass "
    "--system-assigned-mi for its system-assigned identity, or "
    "--user-assigned-mi <uami-resource-id> for an attached user-assigned identity."
)


def _parse_resource_id(
    resource_id: str,
    *,
    argument_name: str,
    provider_namespace: str,
    resource_type: str,
    bare_name_hint: Optional[str] = None,
) -> dict:
    raw = (resource_id or "").strip()
    expected = f"{provider_namespace}/{resource_type}"
    if not raw:
        raise InvalidArgumentValueError(
            f"{argument_name} is required and must be a {expected} ARM resource ID."
        )
    if bare_name_hint and "/" not in raw:
        raise InvalidArgumentValueError(bare_name_hint.format(value=raw))
    if not is_valid_resource_id(raw):
        raise InvalidArgumentValueError(
            f"'{resource_id}' is not a valid ARM resource ID."
        )
    parsed = parse_resource_id(raw)
    if (
        (parsed.get("namespace") or "").casefold()
        != provider_namespace.casefold()
        or (parsed.get("type") or "").casefold() != resource_type.casefold()
        or "child_name_1" in parsed
    ):
        raise InvalidArgumentValueError(
            f"'{resource_id}' is not a {expected} resource ID."
        )
    return {
        "subscription_id": parsed["subscription"],
        "resource_group_name": parsed["resource_group"],
        "name": parsed["name"],
    }


def parse_dps_resource_id(dps_resource_id: str) -> dict:
    result = _parse_resource_id(
        dps_resource_id,
        argument_name="--dps-id",
        provider_namespace="Microsoft.Devices",
        resource_type="provisioningServices",
        bare_name_hint=(
            "'{value}' looks like a bare DPS name. Pass the full ARM resource "
            "ID instead (use 'az iot dps show -n <dps> --query id -o tsv' to "
            "retrieve it)."
        ),
    )
    return result


def parse_hub_resource_id(hub_resource_id: str) -> dict:
    result = _parse_resource_id(
        hub_resource_id,
        argument_name="--hub-id",
        provider_namespace="Microsoft.Devices",
        resource_type="IotHubs",
    )
    return result


def parse_su_resource_id(su_resource_id: str) -> dict:
    result = _parse_resource_id(
        su_resource_id,
        argument_name="--su-id",
        provider_namespace="Microsoft.DeviceUpdate",
        resource_type="updateInstances",
        bare_name_hint=(
            "'{value}' looks like a bare Update Instance name. Pass the full "
            "ARM resource ID instead."
        ),
    )
    return result


def resolve_inbound_identity(
    mi_system_assigned: bool, mi_user_assigned: Optional[str]
) -> Optional[dict]:
    """Build an inbound identity, allowing neither option for update flows."""
    if mi_user_assigned is not None and not mi_user_assigned.strip():
        mi_user_assigned = None
    if mi_system_assigned and mi_user_assigned:
        raise ArgumentUsageError(MI_MUTEX_MSG)
    if mi_user_assigned:
        validate_uami_resource_id(mi_user_assigned)
    return build_mi_body(
        mi_system_assigned,
        mi_user_assigned,
        sami_type=IdentityType.system_assigned.value,
        uami_type=IdentityType.user_assigned.value,
    )


def build_inbound_identity(
    mi_system_assigned: bool, mi_user_assigned: Optional[str]
) -> dict:
    """Build the required inbound identity used by link-add operations."""
    body = resolve_inbound_identity(mi_system_assigned, mi_user_assigned)
    if body is None:
        raise RequiredArgumentMissingError(MI_REQUIRED_MSG)
    return body


def get_messaging_endpoints(namespace: dict) -> dict:
    return get_endpoints(namespace, "messaging")


def get_provisioning_endpoints(namespace: dict) -> dict:
    return get_endpoints(namespace, "provisioning")


def get_updating_endpoints(namespace: dict) -> dict:
    return get_endpoints(namespace, "updating")


def build_hub_endpoint_body(
    hub_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
    availability: Optional[str] = None,
    allocation_weight: Optional[int] = None,
) -> dict:
    body = {
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": hub_resource_id,
    }
    inbound_identity = resolve_inbound_identity(
        mi_system_assigned, mi_user_assigned
    )
    if inbound_identity is not None:
        body["inboundCallerIdentity"] = inbound_identity
    provisioning = {}
    if availability is not None:
        provisioning["availability"] = availability
    if allocation_weight is not None:
        provisioning["allocationWeight"] = allocation_weight
    if provisioning:
        body["provisioning"] = provisioning
    return body


def build_dps_endpoint_body(
    dps_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
) -> dict:
    return {
        "endpointType": DPS_ENDPOINT_TYPE,
        "resourceId": dps_resource_id,
        "inboundCallerIdentity": build_inbound_identity(
            mi_system_assigned, mi_user_assigned
        ),
    }


def build_su_endpoint_body(
    su_resource_id: str,
    mi_system_assigned: bool,
    mi_user_assigned: Optional[str],
) -> dict:
    return {
        "endpointType": SU_ENDPOINT_TYPE,
        "resourceId": su_resource_id,
        "inboundCallerIdentity": build_inbound_identity(
            mi_system_assigned, mi_user_assigned
        ),
    }


def endpoint_update_body(
    existing: Optional[dict],
    inbound_identity: Optional[dict] = None,
) -> dict:
    """Serialize a full endpoint identity for an update PATCH."""
    existing = existing or {}
    body = {
        "endpointType": existing.get("endpointType"),
        "resourceId": existing.get("resourceId"),
    }
    current_inbound = existing.get("inboundCallerIdentity")
    if current_inbound is not None:
        body["inboundCallerIdentity"] = current_inbound
    if inbound_identity is not None:
        body["inboundCallerIdentity"] = inbound_identity
    if existing.get("provisioning") is not None:
        body["provisioning"] = deepcopy(existing["provisioning"])
    return body


def sanitize_identity(identity: Optional[dict]) -> Optional[dict]:
    """Return only writable ARM managed-identity fields."""
    if not identity:
        return None
    result = {"type": identity.get("type")}
    user_assigned = identity.get("userAssignedIdentities")
    if user_assigned is not None:
        result["userAssignedIdentities"] = {
            resource_id: {} for resource_id in user_assigned
        }
    return result


def namespace_replace_body(namespace: dict) -> dict:
    """Build a namespace PUT body while preserving current writable state."""
    body = {
        key: deepcopy(namespace[key])
        for key in ("location", "tags")
        if key in namespace
    }
    identity = sanitize_identity(namespace.get("identity"))
    if identity is not None:
        body["identity"] = identity

    properties = writable_namespace_properties(
        namespace.get("properties") or {}
    )
    if properties:
        body["properties"] = properties
    if not body.get("location"):
        raise AzureResponseError(
            "The namespace GET response did not contain the location required "
            "to replace the namespace."
        )
    return body
