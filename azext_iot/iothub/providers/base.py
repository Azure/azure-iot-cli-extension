# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.common.arm import (
    adapt_modeless_lro_poller,
    get_resource_group,
    get_subscription_id,
    hub_description_for_write,
    hub_etag_arguments,
)
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
        dataplane: bool = True,
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
            if not self.rg:
                self.rg = self.discovery.last_resource_group
            self.resolver = SdkResolver(self.target)
        else:
            self.hub_resource = self.discovery.find_resource(hub_name, rg)
            self.rg = get_resource_group(
                self.hub_resource,
                fallback=rg,
                resource_label="IoT Hub",
            )
            self.subscription_id = get_subscription_id(
                self.hub_resource,
                fallback=(
                    self.discovery.sub_id
                    if self.discovery.sub_id != "unknown"
                    else None
                ),
                resource_label="IoT Hub",
            )

    def get_sdk(self, sdk_type):
        return self.resolver.get_sdk(sdk_type)

    def _begin_hub_update(self):
        """Submit the current Hub state as a sanitized, conditional full PUT."""
        return adapt_modeless_lro_poller(
            self.discovery.client.begin_create_or_update(
                resource_group_name=self.rg,
                resource_name=self.hub_resource["name"],
                iot_hub_description=hub_description_for_write(
                    self.hub_resource
                ),
                **hub_etag_arguments(self.hub_resource),
            )
        )
