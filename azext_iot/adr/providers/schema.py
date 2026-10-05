# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
from typing import Dict, List, Optional

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)

from azext_iot.adr.common import (
    IdentityType,
    build_managed_service_identity,
    build_mi_body,
    validate_uami_resource_id,
)
from azext_iot.adr.providers.base import ADRProvider

_VERSION_PATTERN = re.compile(r"^[0-9]{1,10}$")


def _validate_version_name(version_name: str) -> str:
    if not _VERSION_PATTERN.fullmatch(version_name):
        raise InvalidArgumentValueError(
            "--version must contain 1 to 10 numeric characters."
        )
    return version_name


def _resolve_outbound_identity(
    outbound_mi_system_assigned: Optional[bool],
    outbound_mi_user_assigned: Optional[str],
) -> Optional[dict]:
    if outbound_mi_user_assigned is not None and not outbound_mi_user_assigned.strip():
        outbound_mi_user_assigned = None
    if outbound_mi_system_assigned and outbound_mi_user_assigned:
        raise MutuallyExclusiveArgumentError(
            "Specify only one of --outbound-system-assigned-mi and "
            "--outbound-user-assigned-mi."
        )
    if outbound_mi_user_assigned:
        validate_uami_resource_id(outbound_mi_user_assigned)
    return build_mi_body(
        outbound_mi_system_assigned,
        outbound_mi_user_assigned,
        sami_type=IdentityType.system_assigned.value,
        uami_type=IdentityType.user_assigned.value,
    )


class SchemaRegistryProvider(ADRProvider):
    def create(
        self,
        schema_registry_name: str,
        resource_group_name: str,
        registry_namespace: str,
        storage_account_container_url: str,
        location: Optional[str] = None,
        description: Optional[str] = None,
        display_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        mi_system_assigned: Optional[bool] = None,
        mi_user_assigned: Optional[List[str]] = None,
        outbound_mi_system_assigned: Optional[bool] = None,
        outbound_mi_user_assigned: Optional[str] = None,
        no_wait: bool = False,
    ):
        registry_location = self._ensure_location(
            self.cmd.cli_ctx, resource_group_name, location
        )

        properties = {
            "namespace": registry_namespace,
            "storageAccountContainerUrl": storage_account_container_url,
        }
        if description is not None:
            properties["description"] = description
        if display_name is not None:
            properties["displayName"] = display_name
        outbound_identity = _resolve_outbound_identity(
            outbound_mi_system_assigned, outbound_mi_user_assigned
        )
        if outbound_identity is not None:
            properties["outboundIdentity"] = outbound_identity
        elif outbound_mi_system_assigned is False:
            properties["outboundIdentity"] = None

        resource = {
            "location": registry_location,
            "properties": properties,
        }
        if tags is not None:
            resource["tags"] = tags
        identity = build_managed_service_identity(
            mi_system_assigned, mi_user_assigned
        )
        if identity is not None:
            resource["identity"] = identity

        poller = self.client.schema_registries.begin_create_or_replace(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            resource=resource,
        )
        return self._wait(
            poller,
            f"Creating schema registry '{schema_registry_name}'...",
            no_wait=no_wait,
        )

    def update(
        self,
        schema_registry_name: str,
        resource_group_name: str,
        description: Optional[str] = None,
        display_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        mi_system_assigned: Optional[bool] = None,
        mi_user_assigned: Optional[List[str]] = None,
        outbound_mi_system_assigned: Optional[bool] = None,
        outbound_mi_user_assigned: Optional[str] = None,
        no_wait: bool = False,
    ):
        patch = {}
        properties = {}
        if description is not None:
            properties["description"] = description
        if display_name is not None:
            properties["displayName"] = display_name
        outbound_identity = _resolve_outbound_identity(
            outbound_mi_system_assigned, outbound_mi_user_assigned
        )
        if outbound_identity is not None:
            properties["outboundIdentity"] = outbound_identity
        elif outbound_mi_system_assigned is False:
            properties["outboundIdentity"] = None
        if properties:
            patch["properties"] = properties
        if tags is not None:
            patch["tags"] = tags
        identity = build_managed_service_identity(
            mi_system_assigned, mi_user_assigned
        )
        if identity is not None:
            patch["identity"] = identity
        if not patch:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --description, --display-name, --tags, "
                "--system-assigned-mi, --user-assigned-mi, "
                "--outbound-system-assigned-mi, or --outbound-user-assigned-mi."
            )

        poller = self.client.schema_registries.begin_update(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            properties=patch,
        )
        return self._wait(
            poller,
            f"Updating schema registry '{schema_registry_name}'...",
            no_wait=no_wait,
        )

    def show(self, schema_registry_name: str, resource_group_name: str):
        return self.client.schema_registries.get(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
        )

    def list(self, resource_group_name: Optional[str] = None):
        if resource_group_name:
            return list(
                self.client.schema_registries.list_by_resource_group(
                    resource_group_name=resource_group_name
                )
            )
        return list(self.client.schema_registries.list_by_subscription())

    def delete(
        self,
        schema_registry_name: str,
        resource_group_name: str,
        no_wait: bool = False,
    ):
        poller = self.client.schema_registries.begin_delete(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
        )
        return self._wait(
            poller,
            f"Deleting schema registry '{schema_registry_name}'...",
            no_wait=no_wait,
        )


class SchemaProvider(ADRProvider):
    def create(
        self,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
        schema_type: str,
        schema_format: str,
        description: Optional[str] = None,
        display_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        properties = {
            "schemaType": schema_type,
            "format": schema_format,
        }
        if description is not None:
            properties["description"] = description
        if display_name is not None:
            properties["displayName"] = display_name
        if tags is not None:
            properties["tags"] = tags

        return self.client.schemas.create_or_replace(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
            resource={"properties": properties},
        )

    def show(
        self,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
    ):
        return self.client.schemas.get(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
        )

    def list(self, schema_registry_name: str, resource_group_name: str):
        return list(
            self.client.schemas.list_by_schema_registry(
                resource_group_name=resource_group_name,
                schema_registry_name=schema_registry_name,
            )
        )

    def delete(
        self,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
        no_wait: bool = False,
    ):
        poller = self.client.schemas.begin_delete(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
        )
        return self._wait(
            poller,
            f"Deleting schema '{schema_name}'...",
            no_wait=no_wait,
        )

    def create_version(
        self,
        version_name: str,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
        schema_content: str,
        description: Optional[str] = None,
    ):
        properties = {"schemaContent": schema_content}
        if description is not None:
            properties["description"] = description
        return self.client.schema_versions.create_or_replace(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
            schema_version_name=_validate_version_name(version_name),
            resource={"properties": properties},
        )

    def show_version(
        self,
        version_name: str,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
    ):
        return self.client.schema_versions.get(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
            schema_version_name=_validate_version_name(version_name),
        )

    def list_versions(
        self,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
    ):
        return list(
            self.client.schema_versions.list_by_schema(
                resource_group_name=resource_group_name,
                schema_registry_name=schema_registry_name,
                schema_name=schema_name,
            )
        )

    def delete_version(
        self,
        version_name: str,
        schema_name: str,
        schema_registry_name: str,
        resource_group_name: str,
        no_wait: bool = False,
    ):
        version_name = _validate_version_name(version_name)
        poller = self.client.schema_versions.begin_delete(
            resource_group_name=resource_group_name,
            schema_registry_name=schema_registry_name,
            schema_name=schema_name,
            schema_version_name=version_name,
        )
        return self._wait(
            poller,
            f"Deleting schema version '{version_name}'...",
            no_wait=no_wait,
        )
