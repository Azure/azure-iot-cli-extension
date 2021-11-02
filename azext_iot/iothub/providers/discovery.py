# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.common.base_discovery import BaseDiscovery
from azext_iot.common.utility import trim_from_start, ensure_iothub_sdk_min_version
from azext_iot.iothub.models.iothub_target import IotHubTarget
from azext_iot._factory import iot_hub_service_factory
from azext_iot.constants import IOTHUB_TRACK_2_SDK_MIN_VERSION
from typing import Dict
from enum import Enum, EnumMeta

PRIVILEDGED_ACCESS_RIGHTS_SET = set(
    ["RegistryWrite", "ServiceConnect", "DeviceConnect"]
)
CONN_STR_TEMPLATE = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"
POLICY_ERROR_TEMPLATE = (
    "Unable to discover a priviledged policy for IoT Hub: {}, in subscription {}. "
    "When interfacing with an IoT Hub, the IoT extension requires any single policy with "
    "'RegistryWrite', 'ServiceConnect' and 'DeviceConnect' rights."
)

logger = get_logger(__name__)


# TODO: Consider abstract base class
class IotHubDiscovery(BaseDiscovery):
    def __init__(self, cmd):
        super().__init__(
            cmd,
            ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
            "IoT Hub"
        )

    def _initialize_client(self):
        if not self.client:
            if getattr(self.cmd, "cli_ctx", None):
                self.client = iot_hub_service_factory(self.cmd.cli_ctx)
                self.sub_id = get_subscription_id(self.cmd.cli_ctx)
            else:
                self.client = self.cmd

    def _make_kwargs(self, **kwargs):
        return kwargs

    def _policy_error(self, policy_name, resource_name):
        return (
            "Unable to discover a priviledged policy for IoT Hub: {}, in subscription {}. "
            "When interfacing with an IoT Hub, the IoT extension requires any single policy with "
            "'RegistryWrite', 'ServiceConnect' and 'DeviceConnect' rights.".format(
                resource_name, self.sub_id
            )
        )

    @classmethod
    def _usable_policy(cls, policy):
        rights_set = set(policy.rights.split(", "))
        return PRIVILEDGED_ACCESS_RIGHTS_SET == rights_set

    @classmethod
    def get_target_by_cstring(cls, connection_string: str) -> IotHubTarget:
        return IotHubTarget.from_connection_string(cstring=connection_string).as_dict()

    def _build_target(
        self, resource, policy, key_type: str = None, **kwargs
    ) -> Dict[str, str]:
        # This is more or less a compatibility function which produces the
        # same result as _azure.get_iot_hub_connection_string()
        # In future iteration we will return a 'Target' object rather than dict
        # but that will be better served aligning with vNext pattern for Iot Hub
        include_events = kwargs.get("include_events", False)

        target = {}
        target["cs"] = CONN_STR_TEMPLATE.format(
            resource.properties.host_name,
            policy.key_name,
            policy.primary_key if key_type == "primary" else policy.secondary_key,
        )
        target["entity"] = resource.properties.host_name
        target["policy"] = policy.key_name
        target["primarykey"] = policy.primary_key
        target["secondarykey"] = policy.secondary_key
        target["subscription"] = self.sub_id
        target["resourcegroup"] = resource.additional_properties.get("resourcegroup")
        target["location"] = resource.location
        target["sku_tier"] = resource.sku.tier.value if isinstance(resource.sku.tier, (Enum, EnumMeta)) else resource.sku.tier

        if include_events:
            events = {}
            events["endpoint"] = trim_from_start(
                resource.properties.event_hub_endpoints["events"].endpoint, "sb://"
            ).strip("/")
            events["partition_count"] = resource.properties.event_hub_endpoints[
                "events"
            ].partition_count
            events["path"] = resource.properties.event_hub_endpoints["events"].path
            events["partition_ids"] = resource.properties.event_hub_endpoints[
                "events"
            ].partition_ids
            target["events"] = events

        target["cmd"] = self.cmd

        return target
