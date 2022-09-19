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
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.constants import USER_AGENT


__all__ = ["IoTHubProvider", "CloudError", "SerializationError"]


class IoTHubProvider(object):
    """Class to use for data plane operations."""
    def __init__(self, cmd, hub_name, rg, login=None, auth_type_dataplane=None):
        self.cmd = cmd
        self.hub_name = hub_name
        self.rg = rg
        self.discovery = IotHubDiscovery(cmd)
        self.target = self.discovery.get_target(
            resource_name=self.hub_name,
            resource_group_name=self.rg,
            login=login,
            auth_type=auth_type_dataplane,
        )
        self.resolver = SdkResolver(self.target)

    def get_sdk(self, sdk_type):
        return self.resolver.get_sdk(sdk_type)


class IoTHubResourceProvider(object):
    """Class to use for control plane operations."""
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        self.cmd = cmd
        self.api_version = "2022-04-30-preview"
        self.client = self.get_client()
        self.discovery = IotHubDiscovery(cmd)
        # Set discovery variables since we set client
        self.discovery.track2 = True
        self.discovery.client = self.client.iot_hub_resource
        self.discovery.sub_id = get_subscription_id(self.cmd.cli_ctx)
        # Need to get the direct resource
        self.hub_resource = self.get_iot_hub_resource(hub_name, rg)

    def get_client(self):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.cli.core.profiles import ResourceType
        client = get_mgmt_service_client(
            self.cmd.cli_ctx,
            ResourceType.MGMT_IOTHUB,
            api_version=self.api_version
        )

        # Adding IoT Ext User-Agent is done with best attempt.
        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client

    def get_iot_hub_resource(self, hub_name, rg):
        return self.discovery.find_resource(hub_name, rg)
