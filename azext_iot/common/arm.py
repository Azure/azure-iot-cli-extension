# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Helpers shared by modeless ARM command implementations."""

from copy import deepcopy
from typing import Optional

from azure.cli.core.azclierror import CLIInternalError
from azure.core import MatchConditions
from msrestazure.tools import parse_resource_id


def _resource_id_parts(resource: Optional[dict]) -> dict:
    resource_id = (resource or {}).get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return {}
    return parse_resource_id(resource_id)


def get_resource_group(
    resource: Optional[dict],
    fallback: Optional[str] = None,
    resource_label: str = "resource",
) -> str:
    """Resolve a resource group from caller context or an ARM resource ID.

    Modelless management clients return the service JSON verbatim and therefore
    do not add the legacy ``resourcegroup`` convenience field.
    """
    if fallback:
        return fallback
    resource_group = _resource_id_parts(resource).get("resource_group")
    if not resource_group:
        raise CLIInternalError(
            f"The {resource_label} response did not include a usable resource "
            "ID and no resource group was supplied."
        )
    return resource_group


def get_subscription_id(
    resource: Optional[dict],
    fallback: Optional[str] = None,
    resource_label: str = "resource",
) -> str:
    """Resolve a subscription from an ARM resource ID or caller context."""
    subscription_id = _resource_id_parts(resource).get("subscription")
    if subscription_id:
        return subscription_id
    if fallback:
        return fallback
    raise CLIInternalError(
        f"The {resource_label} response did not include a usable resource ID "
        "and no subscription was supplied."
    )


def sanitize_arm_identity(identity: Optional[dict]) -> Optional[dict]:
    """Copy only writable ARM managed-identity fields."""
    if not identity:
        return identity
    result = {"type": identity.get("type")}
    user_identities = identity.get("userAssignedIdentities")
    if user_identities:
        result["userAssignedIdentities"] = {
            resource_id: {} for resource_id in user_identities
        }
    return result


def hub_description_for_write(hub: dict) -> dict:
    """Build a Hub PUT body without service-owned response projections."""
    body = {
        key: deepcopy(hub[key])
        for key in ("location", "tags", "sku")
        if key in hub
    }
    if "identity" in hub:
        body["identity"] = sanitize_arm_identity(hub.get("identity"))

    sku = body.get("sku")
    if isinstance(sku, dict):
        sku.pop("tier", None)

    properties = deepcopy(hub.get("properties") or {})
    for key in (
        "deviceRegistry",
        "provisioningState",
        "state",
        "hostName",
        "deviceHostName",
        "serviceHostName",
        "locations",
        "iotHubDetails",
        "privateEndpointConnections",
    ):
        properties.pop(key, None)

    # These values identify the service-owned Event Hub endpoint. The writable
    # retention and partition-count settings remain in the request.
    for endpoint in (properties.get("eventHubEndpoints") or {}).values():
        if isinstance(endpoint, dict):
            for key in ("endpoint", "path", "partitionIds"):
                endpoint.pop(key, None)

    body["properties"] = properties
    return body


def hub_etag_arguments(hub: Optional[dict]) -> dict:
    """Return conditional request arguments only when an ETag is available."""
    etag = (hub or {}).get("etag")
    if etag is None:
        return {}
    return {
        "etag": etag,
        "match_condition": MatchConditions.IfNotModified,
    }
