# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Any, Dict, List, Optional

from azext_iot.adr.providers.namespace import NamespaceProvider


def adr_namespace_create(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    system_assigned: bool = True,
    messaging_endpoints: Any = None,
    no_wait: bool = False,
):
    return NamespaceProvider(cmd).create(
        namespace_name=namespace_name, resource_group_name=resource_group_name,
        location=location, tags=tags, system_assigned=system_assigned,
        messaging_endpoints=messaging_endpoints, no_wait=no_wait,
    )


def adr_namespace_show(cmd, namespace_name: str, resource_group_name: str):
    return NamespaceProvider(cmd).show(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_namespace_list(cmd, resource_group_name: Optional[str] = None):
    return NamespaceProvider(cmd).list(resource_group_name=resource_group_name)


def adr_namespace_delete(cmd, namespace_name: str, resource_group_name: str, no_wait: bool = False):
    return NamespaceProvider(cmd).delete(
        namespace_name=namespace_name, resource_group_name=resource_group_name, no_wait=no_wait,
    )


def adr_namespace_update(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    system_assigned: Optional[bool] = None,
    messaging_endpoints: Any = None,
    no_wait: bool = False,
):
    return NamespaceProvider(cmd).update(
        namespace_name=namespace_name, resource_group_name=resource_group_name,
        tags=tags, system_assigned=system_assigned, messaging_endpoints=messaging_endpoints, no_wait=no_wait,
    )


def adr_namespace_migrate(
    cmd, namespace_name: str, resource_group_name: str, resource_ids: List[str], no_wait: bool = False,
):
    return NamespaceProvider(cmd).migrate(
        namespace_name=namespace_name, resource_group_name=resource_group_name,
        resource_ids=resource_ids, no_wait=no_wait,
    )


def adr_namespace_identity_show(cmd, namespace_name: str, resource_group_name: str):
    return NamespaceProvider(cmd).identity_show(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_namespace_identity_assign(cmd, namespace_name: str, resource_group_name: str, no_wait: bool = False):
    return NamespaceProvider(cmd).identity_assign(
        namespace_name=namespace_name, resource_group_name=resource_group_name, no_wait=no_wait,
    )


def adr_namespace_identity_remove(cmd, namespace_name: str, resource_group_name: str, no_wait: bool = False):
    return NamespaceProvider(cmd).identity_remove(
        namespace_name=namespace_name, resource_group_name=resource_group_name, no_wait=no_wait,
    )
