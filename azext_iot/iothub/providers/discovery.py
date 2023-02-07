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
from azext_iot.common.utility import trim_from_start, ensure_iothub_sdk_min_version
from azext_iot.iothub.models.iothub_target import IotHubTarget
from azext_iot._factory import iot_hub_service_factory
from azext_iot.constants import IOTHUB_TRACK_2_SDK_MIN_VERSION
from typing import Any, Dict
from enum import Enum, EnumMeta

logger = get_logger(__name__)
PRIVILEDGED_ACCESS_RIGHTS_SET = set(
    ["RegistryWrite", "ServiceConnect", "DeviceConnect"]
)


class IotHubDiscovery(BaseDiscovery):
    def __init__(self, cmd):
        super().__init__(
            cmd=cmd,
            necessary_rights_set=PRIVILEDGED_ACCESS_RIGHTS_SET,
            resource_type=DiscoveryResourceType.IoTHub.value
        )

    def _initialize_client(self):
        """Initialize the client and set the track2 value if not done already."""
        if not self.client:
            # Track 2 could be supported
            self.track2 = ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION)

            if getattr(self.cmd, "cli_ctx", None):
                self.client = iot_hub_service_factory(self.cmd.cli_ctx).iot_hub_resource
                self.sub_id = get_subscription_id(self.cmd.cli_ctx)
            else:
                self.client = self.cmd

    def _make_kwargs(self, **kwargs) -> Dict[str, Any]:
        return kwargs

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
        target["cs"] = IOT_SERVICE_CS_TEMPLATE.format(
            resource.properties.host_name,
            policy.key_name,
            policy.primary_key if key_type == "primary" else policy.secondary_key,
        )
        target["entity"] = resource.properties.host_name
        target["name"] = resource.name
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
