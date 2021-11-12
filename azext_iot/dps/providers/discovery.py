# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.common._azure import IOT_SERVICE_CS_TEMPLATE
from azext_iot.common.base_discovery import BaseDiscovery
from azext_iot.common.shared import DiscoveryResourceType
from azext_iot._factory import iot_service_provisioning_factory
from typing import Any, Dict

logger = get_logger(__name__)
PRIVILEDGED_ACCESS_RIGHTS_SET = set(
    ["ServiceConfig", "EnrollmentWrite"]
)


class DPSDiscovery(BaseDiscovery):
    def __init__(self, cmd):
        super().__init__(
            cmd=cmd,
            necessary_rights_set=PRIVILEDGED_ACCESS_RIGHTS_SET,
            resource_type=DiscoveryResourceType.DPS.value
        )

    def _initialize_client(self):
        if not self.client:
            if getattr(self.cmd, "cli_ctx", None):
                # The client we want to use is an attribute of the client returned
                # from the factory. This will have to be revisted if the DPS sdk changes.
                self.client = iot_service_provisioning_factory(self.cmd.cli_ctx).iot_dps_resource
                self.sub_id = get_subscription_id(self.cmd.cli_ctx)
            else:
                self.client = self.cmd

            # Method get_keys_for_key_name needed for policy discovery (see
            # BaseDiscovery.find_policy for usage) and is defined as
            # list)keys_for_key_name in the DPS Sdk.
            self.client.get_keys_for_key_name = self.client.list_keys_for_key_name

    def _make_kwargs(self, **kwargs) -> Dict[str, Any]:
        # The DPS client needs the provisioning_service_name argument
        kwargs["provisioning_service_name"] = kwargs.get("resource_name")
        return kwargs

    @classmethod
    def get_target_by_cstring(cls, connection_string: str):
        # TODO: future iteration
        pass

    def _build_target(
        self, resource, policy, key_type: str = None, **kwargs
    ) -> Dict[str, str]:
        # This is more or less a compatibility function which produces the
        # same result as _azure.get_iot_dps_connection_string()
        # In future iteration we will return a 'Target' object rather than dict
        # but that will be better served aligning with vNext pattern for DPS
        result = {}
        result["cs"] = IOT_SERVICE_CS_TEMPLATE.format(
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