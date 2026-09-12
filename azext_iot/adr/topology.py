# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared helpers and diagnostics for atomic namespace link operations."""

from copy import deepcopy

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
    "existing link."
)

HUB_CAP_EXCEEDED_MSG = (
    "Namespace already has the maximum of 10 linked IoT Hubs."
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


def hub_endpoint_count(namespace: dict) -> int:
    return sum(
        endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE)
        for endpoint in get_endpoints(namespace, "messaging").values()
    )


def is_failed_hub_endpoint(endpoint) -> bool:
    """Return whether an endpoint is a Hub whose linking state is Failed."""
    return endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE) and (
        endpoint.get("linkingState") or ""
    ).casefold() == "failed"


def writable_namespace_properties(properties: dict) -> dict:
    """Copy replaceable namespace state without dropping established links."""
    result = deepcopy(properties or {})
    result.pop("provisioningState", None)
    result.pop("uuid", None)
    for section in ("provisioning", "messaging", "updating"):
        if section not in result:
            continue
        section_body = result.get(section) or {}
        endpoints = section_body.get("endpoints") or {}
        section_body["endpoints"] = {
            name: deepcopy(endpoint)
            for name, endpoint in endpoints.items()
            if isinstance(endpoint, dict)
        }
        result[section] = section_body
    return result
