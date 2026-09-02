# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared namespace endpoint-topology validation."""

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
)

from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
)


DPS_REQUIRED_MSG = (
    "A DPS link is required before adding a new Hub or retrying a failed Hub. "
    "Run 'az iot adr ns link dps add ...' or "
    "'az iot adr ns link add ...' to add both at once."
)

DPS_CAP_EXCEEDED_MSG = (
    "Namespace already has a linked DPS; update the existing DPS endpoint "
    "instead. Only one DPS may be linked per namespace."
)

SU_CAP_EXCEEDED_MSG = (
    "Namespace already has a linked Software Updates instance; only one may be "
    "linked per namespace. Use 'az iot adr ns link su update' to modify the "
    "existing link. To unlink it without deleting the Update Instance, run "
    "'az iot adr ns update --updating-endpoints "
    "\"{\\\"<endpoint-name>\\\": null}\"'. Use destructive "
    "'az iot adr ns link su delete' only to permanently delete the linked "
    "Update Instance."
)


def endpoint_is_type(endpoint, endpoint_type: str) -> bool:
    """Compare an endpoint's type case-insensitively."""
    value = endpoint.get("endpointType") if isinstance(endpoint, dict) else None
    return (
        isinstance(value, str)
        and value.casefold() == endpoint_type.casefold()
    )


def get_endpoints(namespace: dict, section: str) -> dict:
    return (
        (((namespace or {}).get("properties") or {}).get(section) or {}).get(
            "endpoints"
        )
        or {}
    )


def has_dps_endpoint(namespace: dict) -> bool:
    """Return whether the namespace contains a DPS-typed provisioning endpoint."""
    return any(
        endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE)
        for endpoint in get_endpoints(namespace, "provisioning").values()
    )


def has_su_endpoint(namespace: dict) -> bool:
    """Return whether the namespace contains an SU-typed updating endpoint."""
    return any(
        endpoint_is_type(endpoint, SU_ENDPOINT_TYPE)
        for endpoint in get_endpoints(namespace, "updating").values()
    )


def is_failed_hub_endpoint(endpoint) -> bool:
    """Return whether an endpoint is a Hub whose linking state is Failed."""
    return endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE) and (
        endpoint.get("linkingState") or ""
    ).casefold() == "failed"


def validate_create_endpoint_topology(properties: dict):
    """Validate endpoint dictionaries submitted in a namespace full PUT."""
    messaging = ((properties.get("messaging") or {}).get("endpoints")) or {}
    provisioning = (
        (properties.get("provisioning") or {}).get("endpoints")
    ) or {}
    updating = ((properties.get("updating") or {}).get("endpoints")) or {}
    dps_count = sum(
        _patched_endpoint_type(name, endpoint, {}).casefold()
        == DPS_ENDPOINT_TYPE.casefold()
        for name, endpoint in provisioning.items()
    )
    if dps_count > 1:
        raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)
    if any(
        _patched_endpoint_type(name, endpoint, {}).casefold()
        == IOT_HUB_ENDPOINT_TYPE.casefold()
        for name, endpoint in messaging.items()
    ) and not dps_count:
        raise ArgumentUsageError(DPS_REQUIRED_MSG)
    su_count = sum(
        _patched_endpoint_type(name, endpoint, {}).casefold()
        == SU_ENDPOINT_TYPE.casefold()
        for name, endpoint in updating.items()
    )
    if su_count > 1:
        raise ArgumentUsageError(SU_CAP_EXCEEDED_MSG)


def update_topology_validation_required(properties: dict) -> bool:
    """Return whether a namespace endpoint PATCH requires current endpoint state."""
    return any(
        ((properties.get(section) or {}).get("endpoints")) or {}
        for section in ("messaging", "provisioning", "updating")
    )


def _patched_endpoint_type(endpoint_name: str, endpoint, existing: dict) -> str:
    if isinstance(endpoint, dict) and "endpointType" in endpoint:
        endpoint_type = endpoint["endpointType"]
        if not isinstance(endpoint_type, str):
            raise InvalidArgumentValueError(
                f"Endpoint '{endpoint_name}' property 'endpointType' must be "
                "a string."
            )
        return endpoint_type
    current = existing.get(endpoint_name)
    if isinstance(current, dict):
        current_type = current.get("endpointType")
        return current_type if isinstance(current_type, str) else ""
    raise InvalidArgumentValueError(
        f"Endpoint '{endpoint_name}' must include a string 'endpointType' "
        "when adding a new endpoint."
    )


def validate_update_endpoint_topology(properties: dict, namespace: dict):
    """Validate the effective DPS/Hub/SU topology for an endpoint PATCH."""
    existing_messaging = get_endpoints(namespace, "messaging")
    existing_provisioning = get_endpoints(namespace, "provisioning")
    existing_updating = get_endpoints(namespace, "updating")
    messaging_patch = (
        (properties.get("messaging") or {}).get("endpoints")
    ) or {}
    provisioning_patch = (
        (properties.get("provisioning") or {}).get("endpoints")
    ) or {}
    updating_patch = (
        (properties.get("updating") or {}).get("endpoints")
    ) or {}

    effective_dps_names = {
        name
        for name, endpoint in existing_provisioning.items()
        if endpoint_is_type(endpoint, DPS_ENDPOINT_TYPE)
    }
    for name, endpoint in provisioning_patch.items():
        if endpoint is None:
            effective_dps_names.discard(name)
            continue
        patched_type = _patched_endpoint_type(
            name, endpoint, existing_provisioning
        )
        if patched_type.casefold() == DPS_ENDPOINT_TYPE.casefold():
            effective_dps_names.add(name)
        else:
            effective_dps_names.discard(name)

    if len(effective_dps_names) > 1:
        raise ArgumentUsageError(DPS_CAP_EXCEEDED_MSG)

    has_dps = bool(effective_dps_names)
    for name, endpoint in messaging_patch.items():
        if endpoint is None:
            continue
        current = existing_messaging.get(name)
        is_new_hub = (
            not endpoint_is_type(current, IOT_HUB_ENDPOINT_TYPE)
            and _patched_endpoint_type(
                name, endpoint, existing_messaging
            ).casefold()
            == IOT_HUB_ENDPOINT_TYPE.casefold()
        )
        if (is_new_hub or is_failed_hub_endpoint(current)) and not has_dps:
            raise ArgumentUsageError(DPS_REQUIRED_MSG)

    effective_su_names = {
        name
        for name, endpoint in existing_updating.items()
        if endpoint_is_type(endpoint, SU_ENDPOINT_TYPE)
    }
    for name, endpoint in updating_patch.items():
        if endpoint is None:
            effective_su_names.discard(name)
            continue
        patched_type = _patched_endpoint_type(
            name, endpoint, existing_updating
        )
        if patched_type.casefold() == SU_ENDPOINT_TYPE.casefold():
            effective_su_names.add(name)
        else:
            effective_su_names.discard(name)

    if len(effective_su_names) > 1:
        raise ArgumentUsageError(SU_CAP_EXCEEDED_MSG)
