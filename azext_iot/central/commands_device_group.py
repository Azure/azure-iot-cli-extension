# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Union
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.preview import DeviceGroupPreview
from azext_iot.central.models.v1_1_preview import DeviceGroupV1_1_preview
from azext_iot.central.providers import CentralDeviceGroupProvider
from azext_iot.central.models.enum import ApiVersion


def list_device_groups(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[Union[DeviceGroupPreview, DeviceGroupV1_1_preview]]:
    provider = CentralDeviceGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.list_device_groups(central_dns_suffix=central_dns_suffix)


def get_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[DeviceGroupPreview, DeviceGroupV1_1_preview]:
    provider = CentralDeviceGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.get_device_group(device_group_id=device_group_id, central_dns_suffix=central_dns_suffix)


def create_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    device_group = provider.create_device_group(
        device_group_id=device_group_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )
    return device_group


def update_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    device_group = provider.update_device_group(
        device_group_id=device_group_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )
    return device_group


def delete_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralDeviceGroupProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_device_group(
        device_group_id=device_group_id,
        central_dns_suffix=central_dns_suffix,
    )
