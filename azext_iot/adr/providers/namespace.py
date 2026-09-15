# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Any, Dict, List, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError
from msrestazure.tools import is_valid_resource_id, parse_resource_id

from azext_iot.adr.common import IdentityType
from azext_iot.adr.providers.base import ADRProvider, parse_json_object


def _messaging_properties(value: Any) -> dict:
    if value is None:
        return {}
    endpoints = parse_json_object(value, "--messaging-endpoints")
    for name, endpoint in endpoints.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(endpoint, dict):
            raise InvalidArgumentValueError(
                "--messaging-endpoints must map nonempty endpoint names to JSON objects."
            )
        unsupported = set(endpoint) - {"address", "endpointType", "resourceId"}
        if unsupported:
            raise InvalidArgumentValueError(
                f"Messaging endpoint '{name}' contains unsupported properties: "
                f"{', '.join(sorted(unsupported))}."
            )
        if not isinstance(endpoint.get("address"), str) or not endpoint["address"].strip():
            raise InvalidArgumentValueError(f"Messaging endpoint '{name}' requires a nonempty address.")
        for key in ("endpointType", "resourceId"):
            if key in endpoint and not isinstance(endpoint[key], str):
                raise InvalidArgumentValueError(f"Messaging endpoint '{name}' property '{key}' must be a string.")
    return {"messaging": {"endpoints": endpoints}}


def _clean_migrate_resource_ids(resource_ids: Optional[List[str]]) -> List[str]:
    if not resource_ids:
        raise RequiredArgumentMissingError("Specify at least one legacy asset resource ID with --resource-ids.")
    unique_ids = {}
    for resource_id in resource_ids:
        cleaned = resource_id.strip().rstrip("/") if isinstance(resource_id, str) else ""
        if not cleaned or not is_valid_resource_id(cleaned):
            raise InvalidArgumentValueError(f"'{resource_id}' is not a valid Azure resource ID.")
        parsed = parse_resource_id(cleaned)
        if (
            (parsed.get("namespace") or "").casefold() != "microsoft.deviceregistry"
            or (parsed.get("type") or "").casefold() != "assets"
            or "child_name_1" in parsed
        ):
            raise InvalidArgumentValueError(f"'{resource_id}' is not a Microsoft.DeviceRegistry/assets resource ID.")
        unique_ids.setdefault(cleaned.casefold(), cleaned)
    return list(unique_ids.values())


class NamespaceProvider(ADRProvider):
    def create(
        self,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        system_assigned: bool = True,
        messaging_endpoints: Any = None,
        **kwargs,
    ):
        properties = _messaging_properties(messaging_endpoints)
        resource = {
            "location": self._ensure_location(self.cmd.cli_ctx, resource_group_name, location),
            "identity": {"type": IdentityType.system_assigned.value if system_assigned else IdentityType.none.value},
        }
        if tags is not None:
            resource["tags"] = tags
        if properties:
            resource["properties"] = properties
        poller = self.client.namespaces.begin_create_or_replace(
            resource_group_name=resource_group_name, namespace_name=namespace_name, resource=resource
        )
        result = self._wait(poller, f"Creating namespace {namespace_name}...", **kwargs)
        if not kwargs.get("no_wait") and result and not result.get("resourceGroup"):
            result["resourceGroup"] = resource_group_name
        return result

    def show(self, namespace_name: str, resource_group_name: str):
        return self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

    def list(self, resource_group_name: Optional[str] = None):
        if resource_group_name:
            result = self.client.namespaces.list_by_resource_group(resource_group_name=resource_group_name)
        else:
            result = self.client.namespaces.list_by_subscription()
        return list(result)

    def delete(self, namespace_name: str, resource_group_name: str, **kwargs):
        try:
            poller = self.client.namespaces.begin_delete(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            return self._wait(poller, f"Deleting namespace {namespace_name}...", **kwargs)
        except HttpResponseError as error:
            if "NamespaceNotEmpty" in str(error):
                raise AzureResponseError(
                    f"Namespace '{namespace_name}' is not empty. Delete its child resources before deleting "
                    "the namespace; namespace deletion does not cascade."
                ) from error
            raise

    def update(
        self,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        system_assigned: Optional[bool] = None,
        messaging_endpoints: Any = None,
        **kwargs,
    ):
        properties = _messaging_properties(messaging_endpoints)
        resource = {}
        if tags is not None:
            resource["tags"] = tags
        if system_assigned is not None:
            resource["identity"] = {
                "type": IdentityType.system_assigned.value if system_assigned else IdentityType.none.value
            }
        if properties:
            resource["properties"] = properties
        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name, namespace_name=namespace_name, properties=resource
        )
        return self._wait(poller, f"Updating namespace {namespace_name}...", **kwargs)

    def migrate(self, namespace_name: str, resource_group_name: str, resource_ids: List[str], **kwargs):
        body = {"scope": "Resources", "resourceIds": _clean_migrate_resource_ids(resource_ids)}
        poller = self.client.namespaces.begin_migrate(
            resource_group_name=resource_group_name, namespace_name=namespace_name, body=body
        )
        return self._wait(poller, f"Migrating assets into namespace {namespace_name}...", **kwargs)

    def identity_show(self, namespace_name: str, resource_group_name: str):
        return self.show(namespace_name, resource_group_name).get("identity") or {}

    def identity_assign(self, namespace_name: str, resource_group_name: str, **kwargs):
        result = self.update(namespace_name, resource_group_name, system_assigned=True, **kwargs)
        return result if kwargs.get("no_wait") or result is None else result.get("identity") or {}

    def identity_remove(self, namespace_name: str, resource_group_name: str, **kwargs):
        result = self.update(namespace_name, resource_group_name, system_assigned=False, **kwargs)
        return result if kwargs.get("no_wait") or result is None else result.get("identity") or {}
