# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.device_stream import DeviceStreamProvider
from typing import Optional


def show_device_stream(
    cmd,
    hub_name: str,
    resource_group_name: Optional[str] = None,
) -> Optional[dict]:
    return DeviceStreamProvider(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    ).show()
