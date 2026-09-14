# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Creation requests for onboarding.

Every selection step offers "use an existing one" or "create a new one". A creation
request is a plain description of what to make; it is turned into a plan item like any
other, so nothing is created during selection.

New resources are always created **with a system-assigned identity**: without one the
resource cannot present a caller identity and the link would fail after a long-running
operation.

This module is deliberately free of any UI framework import.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice,
    system_choice,
)

#: Defaults for resources radr creates on the customer's behalf. Deliberately modest:
#: onboarding should not silently provision expensive capacity.
DEFAULT_HUB_SKU = "S1"
DEFAULT_DPS_SKU = "S1"
DEFAULT_CAPACITY = 1


@dataclass
class CreateRequest:
    """A resource the flow will create."""

    kind: str            # namespace | dps | hub | su
    name: str
    resource_group_name: str
    location: str
    sku: Optional[str] = None
    capacity: int = DEFAULT_CAPACITY
    tags: Optional[Dict[str, str]] = None
    identity: IdentityChoice = field(default_factory=system_choice)

    @property
    def label(self) -> str:
        return {
            "namespace": "namespace",
            "dps": "DPS",
            "hub": "IoT Hub",
            "su": "update instance",
        }.get(self.kind, self.kind)

    def arm_id(self, subscription_id: str) -> str:
        provider = {
            "namespace": "Microsoft.DeviceRegistry/namespaces",
            "dps": "Microsoft.Devices/provisioningServices",
            "hub": "Microsoft.Devices/IotHubs",
            "su": "Microsoft.DeviceUpdate/updateInstances",
        }[self.kind]
        return (
            f"/subscriptions/{subscription_id}/resourceGroups/{self.resource_group_name}"
            f"/providers/{provider}/{self.name}"
        )


def hub_body(
    location: str,
    sku: str = DEFAULT_HUB_SKU,
    capacity: int = DEFAULT_CAPACITY,
    identity: Optional[IdentityChoice] = None,
) -> Dict[str, Any]:
    choice = identity or system_choice()
    return {
        "location": location,
        "sku": {"name": sku, "capacity": capacity},
        "identity": _identity_body(choice),
        "properties": {},
    }


def dps_body(
    location: str,
    sku: str = DEFAULT_DPS_SKU,
    capacity: int = DEFAULT_CAPACITY,
    identity: Optional[IdentityChoice] = None,
) -> Dict[str, Any]:
    choice = identity or system_choice()
    return {
        "location": location,
        "sku": {"name": sku, "capacity": capacity},
        "identity": _identity_body(choice),
        "properties": {},
    }


def _identity_body(choice: IdentityChoice) -> Dict[str, Any]:
    if choice.is_user_assigned:
        return {
            "type": "UserAssigned",
            "userAssignedIdentities": {choice.uami_id: {}},
        }
    return {"type": "SystemAssigned"}


def create_hub(catalog, request: CreateRequest):
    """Start hub creation. Returns a poller for the operations tray."""
    from azext_iot._factory import iot_hub_service_factory

    client = iot_hub_service_factory(catalog.cmd.cli_ctx).iot_hub_resource
    return client.begin_create_or_update(
        resource_group_name=request.resource_group_name,
        resource_name=request.name,
        iot_hub_description=hub_body(
            request.location,
            request.sku or DEFAULT_HUB_SKU,
            request.capacity,
            request.identity,
        ),
    )


def create_dps(catalog, request: CreateRequest):
    """Start DPS creation. Returns a poller for the operations tray."""
    from azext_iot._factory import iot_service_provisioning_factory

    client = iot_service_provisioning_factory(catalog.cmd.cli_ctx).iot_dps_resource
    return client.begin_create_or_update(
        resource_group_name=request.resource_group_name,
        provisioning_service_name=request.name,
        iot_dps_description=dps_body(
            request.location,
            request.sku or DEFAULT_DPS_SKU,
            request.capacity,
            request.identity,
        ),
    )


def create_namespace(session, request: CreateRequest):
    """Create the namespace with an outbound identity already assigned."""
    return session.call(
        session.provider("namespace").create,
        namespace_name=request.name,
        resource_group_name=request.resource_group_name,
        location=request.location,
        tags=request.tags,
        outbound_mi_system_assigned=not request.identity.is_user_assigned,
        outbound_mi_user_assigned=(
            request.identity.uami_id if request.identity.is_user_assigned else None
        ),
        no_wait=True,
    )


def create_update_instance(session, request: CreateRequest):
    return session.call(
        session.provider("update_instance").create,
        update_instance_name=request.name,
        resource_group_name=request.resource_group_name,
        location=request.location,
        mi_system_assigned=not request.identity.is_user_assigned,
        mi_user_assigned=(
            [request.identity.uami_id] if request.identity.is_user_assigned else None
        ),
        no_wait=True,
    )
