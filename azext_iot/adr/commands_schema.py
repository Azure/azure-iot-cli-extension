# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, List, Optional

from azext_iot.adr.providers.schema import SchemaProvider, SchemaRegistryProvider


def adr_schema_registry_create(
    cmd,
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
    return SchemaRegistryProvider(cmd).create(
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        registry_namespace=registry_namespace,
        storage_account_container_url=storage_account_container_url,
        location=location,
        description=description,
        display_name=display_name,
        tags=tags,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        outbound_mi_system_assigned=outbound_mi_system_assigned,
        outbound_mi_user_assigned=outbound_mi_user_assigned,
        no_wait=no_wait,
    )


def adr_schema_registry_update(
    cmd,
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
    return SchemaRegistryProvider(cmd).update(
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        description=description,
        display_name=display_name,
        tags=tags,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        outbound_mi_system_assigned=outbound_mi_system_assigned,
        outbound_mi_user_assigned=outbound_mi_user_assigned,
        no_wait=no_wait,
    )


def adr_schema_registry_show(
    cmd, schema_registry_name: str, resource_group_name: str
):
    return SchemaRegistryProvider(cmd).show(
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
    )


def adr_schema_registry_list(cmd, resource_group_name: Optional[str] = None):
    return SchemaRegistryProvider(cmd).list(
        resource_group_name=resource_group_name
    )


def adr_schema_registry_delete(
    cmd,
    schema_registry_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return SchemaRegistryProvider(cmd).delete(
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_schema_create(
    cmd,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
    schema_type: str,
    schema_format: str,
    description: Optional[str] = None,
    display_name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
):
    return SchemaProvider(cmd).create(
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        schema_type=schema_type,
        schema_format=schema_format,
        description=description,
        display_name=display_name,
        tags=tags,
    )


def adr_schema_show(
    cmd,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
):
    return SchemaProvider(cmd).show(
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
    )


def adr_schema_list(
    cmd, schema_registry_name: str, resource_group_name: str
):
    return SchemaProvider(cmd).list(
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
    )


def adr_schema_delete(
    cmd,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return SchemaProvider(cmd).delete(
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_schema_version_create(
    cmd,
    version_name: str,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
    schema_content: str,
    description: Optional[str] = None,
):
    return SchemaProvider(cmd).create_version(
        version_name=version_name,
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        schema_content=schema_content,
        description=description,
    )


def adr_schema_version_show(
    cmd,
    version_name: str,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
):
    return SchemaProvider(cmd).show_version(
        version_name=version_name,
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
    )


def adr_schema_version_list(
    cmd,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
):
    return SchemaProvider(cmd).list_versions(
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
    )


def adr_schema_version_delete(
    cmd,
    version_name: str,
    schema_name: str,
    schema_registry_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return SchemaProvider(cmd).delete_version(
        version_name=version_name,
        schema_name=schema_name,
        schema_registry_name=schema_registry_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )
