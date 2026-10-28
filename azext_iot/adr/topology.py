# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared helpers and diagnostics for atomic namespace link operations."""

from copy import deepcopy
from typing import Optional

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
    "Namespace already has a linked DPS; only one is allowed. "
    "Use 'az iot adr ns link dps update' to change its identity or retry a Failed link. "
    "To change the target, remove the existing link with 'az iot adr ns link dps remove'. "
    "Delete the target first for Succeeded links, not Failed links."
)

SU_CAP_EXCEEDED_MSG = (
    "Namespace already has a linked Software Updates instance; only one is allowed. "
    "Use 'az iot adr ns link su update' to change its identity or retry a Failed link. "
    "To change the target, remove the existing link with 'az iot adr ns link su remove'. "
    "Delete the target first for Succeeded links, not Failed links."
)

HUB_CAP_EXCEEDED_MSG = (
    "Namespace already has the maximum of 10 linked IoT Hubs. "
    "Use 'az iot adr ns link hub update' to retry a Failed link, or "
    "'az iot adr ns link hub remove' to free an endpoint. "
    "Delete the target first for Succeeded links, not Failed links. "
    "Clear Registry Device IoT Hub capability references before removing any Hub endpoint."
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
    return endpoint_is_type(endpoint, IOT_HUB_ENDPOINT_TYPE) and is_failed_link_endpoint(endpoint)


def is_failed_link_endpoint(endpoint: dict) -> bool:
    status = endpoint.get("provisioningStatus") or endpoint.get("status") or {}
    state = endpoint.get("linkingState") or (status.get("status") if isinstance(status, dict) else None)
    return str(state or "").casefold() == "failed"


def endpoint_update_body(
    existing: Optional[dict],
    inbound_identity: Optional[dict] = None,
) -> dict:
    """Project an endpoint onto its writable fields, dropping server-computed
    status/output (linkingState, linkingError, serviceAddress, address,
    deviceAddress)."""
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


def endpoint_settings_match(actual: dict, expected: dict) -> bool:
    """Match writable fields, allowing only omitted Hub provisioning settings to appear."""
    actual = endpoint_update_body(actual)
    expected = endpoint_update_body(expected)
    if not endpoint_is_type(expected, IOT_HUB_ENDPOINT_TYPE):
        return actual == expected
    actual_settings = actual.pop("provisioning", {})
    expected_settings = expected.pop("provisioning", {})
    return (
        actual == expected
        and isinstance(actual_settings, dict)
        and isinstance(expected_settings, dict)
        and not (actual_settings.keys() - expected_settings.keys() - {"availability", "allocationWeight"})
        and all(key in actual_settings and actual_settings[key] == value for key, value in expected_settings.items())
    )


def writable_namespace_properties(properties: dict) -> dict:
    """Copy replaceable namespace state, projecting endpoints to their writable
    fields so a CreateOrReplace PUT does not echo server-computed status."""
    result = deepcopy(properties or {})
    result.pop("provisioningState", None)
    result.pop("uuid", None)
    for section in ("provisioning", "messaging", "updating"):
        if section not in result:
            continue
        section_body = result.get(section) or {}
        endpoints = section_body.get("endpoints") or {}
        section_body["endpoints"] = {
            name: endpoint_update_body(endpoint)
            for name, endpoint in endpoints.items()
            if isinstance(endpoint, dict)
        }
        result[section] = section_body
    return result
