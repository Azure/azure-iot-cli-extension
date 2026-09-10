# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Helpers shared by modeless ARM command implementations."""

from copy import deepcopy
from typing import Optional

from azure.core import MatchConditions
from azure.core.polling import AsyncLROPoller, LROPoller


def _deserialize_modeless_lro_response(pipeline_response):
    response = pipeline_response.http_response
    if not response.content:
        return None
    return response.json()


def adapt_modeless_lro_poller(poller):
    """Repair generated modeless ARM LRO result deserialization in place.

    Some generated Update Instance operations close over an undefined
    ``response`` variable in their final-response callback. Keep the original
    azure-core poller (and therefore its complete public interface), replacing
    only that callback with JSON deserialization from the pipeline response.
    Legacy msrest pollers are returned unchanged.
    """
    if not isinstance(poller, (LROPoller, AsyncLROPoller)):
        return poller

    polling_method = poller.polling_method()
    polling_method._deserialization_callback = (  # pylint: disable=protected-access
        _deserialize_modeless_lro_response
    )
    return poller


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
