# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, List, Optional

from knack.log import get_logger

from azext_iot.adr.providers.namespace import NamespaceProvider

logger = get_logger(__name__)


def adr_namespace_create(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    outbound_mi_system_assigned: Optional[bool] = None,
    outbound_mi_user_assigned: Optional[str] = None,
    observability_enabled: Optional[bool] = None,
    no_wait: bool = False,
):
    provider = NamespaceProvider(cmd)
    return provider.create(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
        observability_enabled=observability_enabled,
        outbound_mi_system_assigned=outbound_mi_system_assigned,
        outbound_mi_user_assigned=outbound_mi_user_assigned,
        no_wait=no_wait,
    )


def adr_namespace_show(cmd, namespace_name: str, resource_group_name: str):
    provider = NamespaceProvider(cmd)
    return provider.show(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_namespace_list(cmd, resource_group_name: Optional[str] = None):
    provider = NamespaceProvider(cmd)
    return provider.list(resource_group_name=resource_group_name)


def adr_namespace_delete(cmd, namespace_name: str, resource_group_name: str, no_wait: bool = False):
    provider = NamespaceProvider(cmd)
    return provider.delete(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_namespace_migrate(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    resource_ids: List[str],
    no_wait: bool = False,
):
    provider = NamespaceProvider(cmd)
    return provider.migrate(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        resource_ids=resource_ids,
        no_wait=no_wait,
    )


def adr_namespace_update(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    outbound_mi_system_assigned: Optional[bool] = None,
    outbound_mi_user_assigned: Optional[str] = None,
    observability_enabled: Optional[bool] = None,
    no_wait: bool = False,
):
    provider = NamespaceProvider(cmd)
    return provider.update(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        tags=tags,
        observability_enabled=observability_enabled,
        outbound_mi_system_assigned=outbound_mi_system_assigned,
        outbound_mi_user_assigned=outbound_mi_user_assigned,
        no_wait=no_wait,
    )


def adr_namespace_identity_show(
    cmd, namespace_name: str, resource_group_name: str
):
    provider = NamespaceProvider(cmd)
    return provider.identity_show(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_namespace_identity_assign(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    system_assigned: bool = False,
    user_assigned_identities: Optional[List[str]] = None,
    no_wait: bool = False,
):
    provider = NamespaceProvider(cmd)
    return provider.identity_assign(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        system_assigned=system_assigned,
        user_assigned_identities=user_assigned_identities,
        no_wait=no_wait,
    )


def adr_namespace_identity_remove(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    system_assigned: bool = False,
    user_assigned_identities: Optional[List[str]] = None,
    no_wait: bool = False,
):
    provider = NamespaceProvider(cmd)
    return provider.identity_remove(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        system_assigned=system_assigned,
        user_assigned_identities=user_assigned_identities,
        no_wait=no_wait,
    )
