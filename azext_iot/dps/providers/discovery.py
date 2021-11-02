# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.common.base_discovery import BaseDiscovery
from azext_iot._factory import iot_service_provisioning_factory
from typing import Dict

CONN_STR_TEMPLATE = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"

logger = get_logger(__name__)


# TODO: Consider abstract base class
class DPSDiscovery(BaseDiscovery):
    def __init__(self, cmd):
        super().__init__(
            cmd,
            False,
            "DPS"
        )

    def _initialize_client(self):
        if not self.client:
            if getattr(self.cmd, "cli_ctx", None):
                self.client = iot_service_provisioning_factory(self.cmd.cli_ctx).iot_dps_resource
                self.sub_id = get_subscription_id(self.cmd.cli_ctx)
                # Weirdness thanks to client discrepencies
                self.client.get_keys_for_key_name = self.client.list_keys_for_key_name
            else:
                self.client = self.cmd

    def _make_kwargs(self, **kwargs):
        kwargs["provisioning_service_name"] = kwargs.get("resource_name")
        return kwargs

    def _policy_error(self, policy_name, resource_name):
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
        pass

    def _build_target(self, resource, policy, key_type: str = None) -> Dict[str, str]:
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
