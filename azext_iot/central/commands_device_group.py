# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from typing import List, Optional

from azext_iot.central.providers import CentralDeviceGroupProvider
from azext_iot.sdk.central.ga_2022_05_31.models import DeviceGroup


def create_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    display_name: str,
    filter: str,
    description: Optional[str] = None,
    organizations: Optional[List[str]] = None,
) -> DeviceGroup:
    provider = CentralDeviceGroupProvider(cmd=cmd, app_id=app_id)
    device_group = provider.create(
        device_group_id=device_group_id,
        display_name=display_name,
        filter=filter,
        description=description,
        organizations=organizations,
    )
    return device_group


def list_device_groups(
    cmd,
    app_id: str,
) -> List[DeviceGroup]:
    provider = CentralDeviceGroupProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def get_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
) -> DeviceGroup:
    provider = CentralDeviceGroupProvider(cmd=cmd, app_id=app_id)
    return provider.get(device_group_id=device_group_id)


def update_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    display_name: Optional[str] = None,
    filter: Optional[str] = None,
    description: Optional[str] = None,
    organizations: Optional[List[str]] = None,
) -> DeviceGroup:
    provider = CentralDeviceGroupProvider(cmd=cmd, app_id=app_id)
    device_group = provider.update(
        device_group_id=device_group_id,
        display_name=display_name,
        filter=filter,
        description=description,
        organizations=organizations,
    )
    return device_group


def delete_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
):
    provider = CentralDeviceGroupProvider(cmd=cmd, app_id=app_id)
    return provider.delete(device_group_id=device_group_id)
