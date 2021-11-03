# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.common._azure import CONN_STR_TEMPLATE
from azext_iot.common.base_discovery import BaseDiscovery
from azext_iot.common.shared import DiscoveryResourceType
from azext_iot._factory import iot_service_provisioning_factory
from typing import Dict

logger = get_logger(__name__)


class DPSDiscovery(BaseDiscovery):
    def __init__(self, cmd):
        super().__init__(
            cmd,
            DiscoveryResourceType.DPS.value
        )

    def _initialize_client(self):
        if not self.client:
            if getattr(self.cmd, "cli_ctx", None):
                self.client = iot_service_provisioning_factory(self.cmd.cli_ctx).iot_dps_resource
                self.sub_id = get_subscription_id(self.cmd.cli_ctx)
            else:
                self.client = self.cmd

            # Weirdness thanks to client discrepencies
            self.client.get_keys_for_key_name = self.client.list_keys_for_key_name

    def _make_kwargs(self, **kwargs):
        """Adds kwarg for the DPS client."""
        kwargs["provisioning_service_name"] = kwargs.get("resource_name")
        return kwargs

    def _policy_error(self, policy_name: str, resource_name: str) -> str:
        return (
            "No keys found for policy {} of "
            "IoT Provisioning Service {}.".format(policy_name, resource_name)
        )

    @classmethod
    def _usable_policy(cls, policy):
        return bool(policy)

    @classmethod
    def get_target_by_cstring(cls, connection_string: str):
        # TODO: future iteration
        # """Parse from dps connection string and return the parts needed. See IotHubTarget."""
        # decomposed = parse_dps_connection_string(connection_string)
        # return {
        #     "cs": connection_string,
        #     "policy": decomposed.get("SharedAccessKeyName"),
        #     "primarykey": decomposed.get("SharedAccessKey"),
        #     "entity": decomposed.get("HostName"),
        # }
        pass

    def _build_target(self, resource, policy, key_type: str = None, **kwargs) -> Dict[str, str]:
        result = {}
        result["cs"] = CONN_STR_TEMPLATE.format(
            resource.properties.service_operations_host_name,
            policy.key_name,
            policy.primary_key if key_type == "primary" else policy.secondary_key,
        )
        result["entity"] = resource.properties.service_operations_host_name
        result["policy"] = policy.key_name
        result["primarykey"] = policy.primary_key
        result["secondarykey"] = policy.secondary_key
        result["subscription"] = self.sub_id

        return result
