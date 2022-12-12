# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import NamedTuple, Optional, List, Dict
from azext_iot.sdk.iothub.service.models import ConfigurationContent


class EdgeContainerAuth(NamedTuple):
    """
    Edge container authentication datatype
    """
    serveraddress: str
    username: str
    password: str


class EdgeDeviceConfig(NamedTuple):
    """
    Individual Edge device configuration data format.
    """
    device_id: str
    deployment: Optional[ConfigurationContent] = None
    parent_id: Optional[str] = None
    hostname: Optional[str] = None
    parent_hostname: Optional[str] = None
    edge_agent: Optional[str] = None
    container_auth: Optional[EdgeContainerAuth] = None


class EdgeDevicesConfig(NamedTuple):
    """
    Edge device configuration file data format.
    """
    version: str
    auth_method: str
    root_cert: Dict[str, str]
    devices: List[EdgeDeviceConfig]
    template_config_path: Optional[str] = None
    default_edge_agent: Optional[str] = None
