# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from typing import Dict, List, Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError
from msrestazure.tools import parse_resource_id

from azext_iot._factory import (
    adr_service_factory,
    adr_update_instance_service_factory,
)
from azext_iot.adr.common import (
    SU_ENDPOINT_TYPE,
    build_managed_service_identity,
)
from azext_iot.adr.providers import base as provider_base
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.common.arm import sanitize_arm_identity


class UpdateInstanceProvider(ADRProvider):
    def __init__(self, cmd):
        self.cmd = cmd
        self.client = adr_update_instance_service_factory(cmd.cli_ctx)

    def _await_terminal(self, poller, **kwargs):
        return provider_base.wait_for_terminal_state(poller, **kwargs)

    def check_name(self, update_instance_name: str):
        return self.client.update_instances.check_name_availability(
            {"name": update_instance_name, "type": SU_ENDPOINT_TYPE}
        )

    def list(self, resource_group_name: Optional[str] = None):
        if resource_group_name:
            result = self.client.update_instances.list_by_resource_group(
                resource_group_name=resource_group_name
            )
        else:
            result = self.client.update_instances.list_by_subscription()
        return list(result)

    def show(self, update_instance_name: str, resource_group_name: str):
        return self.client.update_instances.get(
            resource_group_name=resource_group_name,
            update_instance_name=update_instance_name,
        )

    def create(
        self,
        update_instance_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        mi_system_assigned: Optional[bool] = None,
        mi_user_assigned: Optional[List[str]] = None,
        **kwargs,
    ):
        availability = self.client.update_instances.check_name_availability(
            {"name": update_instance_name, "type": SU_ENDPOINT_TYPE}
        )
        current = None
        if (
            isinstance(availability, dict)
            and availability.get("nameAvailable") is False
        ):
            try:
                current = self.show(
                    update_instance_name, resource_group_name
                )
            except HttpResponseError as error:
                if error.status_code != 404:
                    raise

        if location is None:
            location = (current or {}).get("location")
        if location is None:
            location = self._ensure_location(
                self.cmd.cli_ctx, resource_group_name, location
            )

        resource = {
            "location": location,
            "properties": {},
        }
        if tags is not None:
            resource["tags"] = tags
        elif current is not None and "tags" in current:
            resource["tags"] = deepcopy(current["tags"])

        identity = build_managed_service_identity(mi_system_assigned, mi_user_assigned)
        if identity is not None:
            if current is not None:
                self._protect_link_identity(current, identity)
            resource["identity"] = identity
        elif current is not None and "identity" in current:
            resource["identity"] = sanitize_arm_identity(
                current.get("identity")
            )

        poller = self.client.update_instances.begin_create(
            resource_group_name=resource_group_name,
            update_instance_name=update_instance_name,
            resource=resource,
        )
        return self._wait(
            poller,
            f"Creating Update Instance '{update_instance_name}'...",
            **kwargs,
        )

    def update(
        self,
        update_instance_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        mi_system_assigned: Optional[bool] = None,
        mi_user_assigned: Optional[List[str]] = None,
        **kwargs,
    ):
        properties = {}
        if tags is not None:
            properties["tags"] = tags
        identity = build_managed_service_identity(mi_system_assigned, mi_user_assigned)
        if identity is not None:
            current = self.show(update_instance_name, resource_group_name)
            self._protect_link_identity(current, identity)
            properties["identity"] = identity
        if not properties:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --tags, --system-assigned-mi, "
                "or --user-assigned-mi."
            )

        poller = self.client.update_instances.begin_update(
            resource_group_name=resource_group_name,
            update_instance_name=update_instance_name,
            properties=properties,
        )
        return self._wait(
            poller,
            f"Updating Update Instance '{update_instance_name}'...",
            **kwargs,
        )

    def _protect_link_identity(self, instance: dict, desired_identity: dict):
        linking = ((instance or {}).get("properties") or {}).get("linking") or {}
        namespace_id = linking.get("namespaceResourceId")
        if not namespace_id:
            return

        raw_instance_id = (
            instance.get("id") if isinstance(instance, dict) else None
        )
        if not raw_instance_id:
            raise AzureResponseError(
                "The Update Instance response omitted its resource ID, so the "
                "identity selected by an ADR link cannot be verified. No "
                "identity update was submitted. Retry the command or rotate "
                "the link with 'az iot adr ns link su update'."
            )
        instance_id = str(raw_instance_id).rstrip("/").casefold()
        parsed = parse_resource_id(namespace_id)
        if not all(
            parsed.get(key)
            for key in ("subscription", "resource_group", "name")
        ):
            raise ArgumentUsageError(
                "The Update Instance has an active ADR link that could not be "
                "validated. Rotate or delete the link before changing identities."
            )
        try:
            namespace = adr_service_factory(
                self.cmd.cli_ctx, subscription_id=parsed["subscription"]
            ).namespaces.get(
                resource_group_name=parsed["resource_group"],
                namespace_name=parsed["name"],
            )
        except Exception as error:
            raise ArgumentUsageError(
                "The Update Instance is namespace-linked, but its selected "
                "identity could not be read. Run 'az iot adr ns link su show' "
                "and rotate the link before changing identities."
            ) from error

        endpoints = (
            (((namespace or {}).get("properties") or {}).get("updating") or {})
            .get("endpoints")
            or {}
        )
        for endpoint in endpoints.values():
            if (
                str((endpoint or {}).get("resourceId") or "")
                .rstrip("/")
                .casefold()
                != instance_id
            ):
                continue
            selected = (endpoint or {}).get("inboundCallerIdentity") or {}
            desired_type = str(desired_identity.get("type") or "")
            selected_type = str(selected.get("type") or "").casefold()
            if (
                selected_type == "systemassigned"
                and "SystemAssigned" not in desired_type
            ):
                raise ArgumentUsageError(
                    "The Update Instance system-assigned identity is used by an "
                    "active ADR link. Rotate it first with "
                    "'az iot adr ns link su update'."
                )
            selected_uami = selected.get("userAssignedIdentity")
            desired_uamis = {
                resource_id.rstrip("/").casefold()
                for resource_id in (
                    desired_identity.get("userAssignedIdentities") or {}
                )
            }
            if (
                selected_type == "userassigned"
                and selected_uami
                and selected_uami.rstrip("/").casefold() not in desired_uamis
            ):
                raise ArgumentUsageError(
                    "The selected Update Instance user-assigned identity is used "
                    "by an active ADR link. Rotate it first with "
                    "'az iot adr ns link su update'."
                )

    def delete(
        self,
        update_instance_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        poller = self.client.update_instances.begin_delete(
            resource_group_name=resource_group_name,
            update_instance_name=update_instance_name,
        )
        return self._wait(
            poller,
            f"Deleting Update Instance '{update_instance_name}'...",
            **kwargs,
        )
