# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azext_iot.adr.providers.device import DeviceProvider


def adr_device_show(cmd, device_name: str, namespace_name: str, resource_group_name: str):
    provider = DeviceProvider(cmd)
    return provider.show(
        device_name=device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_device_list(cmd, namespace_name: str, resource_group_name: str):
    provider = DeviceProvider(cmd)
    return provider.list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_device_update(
    cmd,
    device_name: str,
    namespace_name: str,
    resource_group_name: str,
    enabled: Optional[bool] = None,
    tags: Optional[Dict[str, str]] = None,
    operating_system_version: Optional[str] = None,
    attributes: Optional[str] = None,
    policy_resource_id: Optional[str] = None,
):
    provider = DeviceProvider(cmd)
    return provider.update(
        device_name=device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        enabled=enabled,
        tags=tags,
        operating_system_version=operating_system_version,
        attributes=attributes,
        policy_resource_id=policy_resource_id,
    )


def adr_device_revoke(
    cmd,
    device_name: str,
    namespace_name: str,
    resource_group_name: str,
    disable: bool = False,
):
    provider = DeviceProvider(cmd)
    return provider.revoke(
        device_name=device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        disable=disable,
    )
