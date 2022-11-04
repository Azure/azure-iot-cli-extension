# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# Utility classes for edge device configs
from typing import NamedTuple, Optional, List, Dict
from azext_iot.common.shared import DeviceAuthType
from azext_iot.sdk.iothub.service.models import ConfigurationContent


class EdgeContainerAuth(NamedTuple):
    serveraddress: str
    username: str
    password: str


class EdgeDeviceConfig(NamedTuple):
    device_id: str
    deployment: Optional[ConfigurationContent] = None
    parent_id: Optional[str] = None
    hostname: Optional[str] = None
    parent_hostname: Optional[str] = None
    edge_agent: Optional[str] = None
    container_auth: Optional[EdgeContainerAuth] = None


class EdgeDevicesConfig(NamedTuple):
    version: str
    auth_method: DeviceAuthType
    root_cert: Dict[str, str]
    devices: List[EdgeDeviceConfig]
    template_config_path: Optional[str] = None
    default_edge_agent: Optional[str] = None
