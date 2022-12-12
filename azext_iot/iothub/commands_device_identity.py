# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional
from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider
from knack.log import get_logger

logger = get_logger(__name__)


def iot_edge_devices_create(
    cmd,
    devices: Optional[List[List[str]]] = None,
    config_file: Optional[str] = None,
    visualize: bool = False,
    clean: bool = False,
    yes: bool = False,
    device_auth_type: Optional[str] = None,
    default_edge_agent: Optional[str] = None,
    device_config_template: Optional[str] = None,
    root_cert_path: Optional[str] = None,
    root_key_path: Optional[str] = None,
    root_cert_password: Optional[str] = None,
    bundle_output_path: Optional[str] = None,
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
    return device_identity_provider.create_edge_devices(
        devices=devices,
        config_file=config_file,
        clean=clean,
        yes=yes,
        visualize=visualize,
        auth_type=device_auth_type,
        default_edge_agent=default_edge_agent,
        device_config_template=device_config_template,
        root_cert_path=root_cert_path,
        root_key_path=root_key_path,
        root_cert_password=root_cert_password,
        output_path=bundle_output_path,
    )


def iot_delete_devices(
    cmd,
    device_ids: List[str],
    confirm: bool = True,
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
    return device_identity_provider.delete_device_identities(
        device_ids=device_ids,
        confirm=confirm
    )
