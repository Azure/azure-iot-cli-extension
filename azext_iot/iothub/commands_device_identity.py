# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional
from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider
from knack.log import get_logger

logger = get_logger(__name__)


def iot_edge_hierarchy_create(
    cmd,
    devices: Optional[List[List[str]]] = None,
    config_file: Optional[str] = None,
    visualize: Optional[bool] = False,
    clean: Optional[bool] = False,
    default_agent: Optional[str] = None,
    hub_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    login: Optional[str] = None,
    auth_type_dataplane: Optional[str] = None,
):
    device_identity_provider = DeviceIdentityProvider(
        cmd=cmd,
        hub_name=hub_name,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    return device_identity_provider.create_edge_hierarchy(
        devices=devices,
        config_file=config_file,
        clean=clean,
        visualize=visualize,
        default_agent=default_agent,
    )
