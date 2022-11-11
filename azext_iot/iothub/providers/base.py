# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot._factory import SdkResolver
from msrest.exceptions import SerializationError
from msrestazure.azure_exceptions import CloudError


__all__ = ["IoTHubProvider", "CloudError", "SerializationError"]


class IoTHubProvider(object):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: str,
        login: Optional[str] = None,
        auth_type_dataplane: Optional[str] = None,
        dataplane: bool = True
    ):
        self.cmd = cmd
        self.hub_name = hub_name
        self.rg = rg
        self.discovery = IotHubDiscovery(cmd)
        if dataplane:
            self.target = self.discovery.get_target(
                resource_name=self.hub_name,
                resource_group_name=self.rg,
                login=login,
                auth_type=auth_type_dataplane,
            )
            self.resolver = SdkResolver(self.target)
        else:
            self.hub_resource = self.discovery.find_resource(hub_name, rg)

    def get_sdk(self, sdk_type):
        return self.resolver.get_sdk(sdk_type)
