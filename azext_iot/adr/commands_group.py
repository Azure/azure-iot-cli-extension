# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azext_iot.adr.common import GroupType
from azext_iot.adr.providers.group import GroupProvider


def adr_group_create(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    query_string: str,
    group_type: str = GroupType.registry_device.value,
    location: Optional[str] = None,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
):
    provider = GroupProvider(cmd)
    return provider.create(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        query_string=query_string,
        group_type=group_type,
        location=location,
        display_name=display_name,
        description=description,
        tags=tags,
    )


def adr_group_update(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
):
    provider = GroupProvider(cmd)
    return provider.update(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        display_name=display_name,
        description=description,
        tags=tags,
    )


def adr_group_show(cmd, group_name: str, namespace_name: str, resource_group_name: str):
    provider = GroupProvider(cmd)
    return provider.show(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_group_list(cmd, namespace_name: str, resource_group_name: str):
    provider = GroupProvider(cmd)
    return provider.list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_group_delete(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = GroupProvider(cmd)
    return provider.delete(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_group_refresh(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = GroupProvider(cmd)
    return provider.refresh(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_group_list_members(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
    page_size: Optional[int] = None,
    skip_token: Optional[str] = None,
):
    provider = GroupProvider(cmd)
    return provider.list_members(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        page_size=page_size,
        skip_token=skip_token,
    )


def adr_group_count(
    cmd,
    group_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = GroupProvider(cmd)
    return provider.count(
        group_name=group_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )
