# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from knack.log import get_logger
from azext_iot.common.utility import trim_from_start
from azext_iot.iothub.models.iothub_target import IotHubTarget
from azext_iot._factory import iot_hub_service_factory
from typing import Dict, List

PRIVILEDGED_ACCESS_RIGHTS_SET = set(
    ["RegistryWrite", "ServiceConnect", "DeviceConnect"]
)
CONN_STR_TEMPLATE = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"

logger = get_logger(__name__)


# TODO: Consider abstract base class
class IotHubDiscovery(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.client = None
        self.sub_id = "unknown"
        self._initialize_client()

    def _initialize_client(self):
        if not self.client:
            if getattr(self.cmd, "cli_ctx", None):
                self.client = iot_hub_service_factory(self.cmd.cli_ctx)
            else:
                self.client = self.cmd
            self.sub_id = self.client.config.subscription_id

    def get_iothubs(self, rg: str = None) -> List:
        hubs_list = []

        if not rg:
            hubs_pager = self.client.list_by_subscription()
        else:
            hubs_pager = self.client.list_by_resource_group(resource_group_name=rg)

        try:
            while True:
                hubs_list.extend(hubs_pager.advance_page())
        except StopIteration:
            pass

        return hubs_list

    def get_policies(self, hub_name: str, rg: str) -> List:
        policy_pager = self.client.list_keys(
            resource_group_name=rg, resource_name=hub_name
        )
        policy_list = []

        try:
            while True:
                policy_list.extend(policy_pager.advance_page())
        except StopIteration:
            pass

        return policy_list

    def find_iothub(self, hub_name: str, rg: str = None):
        from azure.mgmt.iothub.models import ErrorDetailsException

        if rg:
            try:
                return self.client.get(resource_group_name=rg, resource_name=hub_name)
            except ErrorDetailsException:
                raise CLIError(
                    "Unable to find IoT Hub: {} in resource group: {}".format(
                        hub_name, rg
                    )
                )

        hubs_list = self.get_iothubs()

        if hubs_list:
            target_hub = next(
                (hub for hub in hubs_list if hub_name.lower() == hub.name.lower()), None
            )
            if target_hub:
                return target_hub

        raise CLIError(
            "Unable to find IoT Hub: {} in current subscription {}.".format(
                hub_name, self.sub_id
            )
        )

    def find_policy(self, hub_name: str, rg: str, policy_name: str = "auto"):
        if policy_name.lower() != "auto":
            return self.client.get_keys_for_key_name(
                resource_group_name=rg, resource_name=hub_name, key_name=policy_name
            )

        policy_list = self.get_policies(hub_name=hub_name, rg=rg)

        for policy in policy_list:
            rights_set = set(policy.rights.split(", "))
            if PRIVILEDGED_ACCESS_RIGHTS_SET == rights_set:
                logger.info(
                    "Using policy '%s' for IoT Hub interaction.", policy.key_name
                )
                return policy

        raise CLIError(
            "Unable to discover a priviledged policy for IoT Hub: {}, in subscription {}. "
            "When interfacing with an IoT Hub, the IoT extension requires any single policy with "
            "'RegistryWrite', 'ServiceConnect' and 'DeviceConnect' rights.".format(
                hub_name, self.sub_id
            )
        )

    @classmethod
    def get_target_by_cstring(cls, connection_string: str) -> IotHubTarget:
        return IotHubTarget.from_connection_string(cstring=connection_string).as_dict()

    def get_target(self, hub_name: str, rg: str = None, **kwargs) -> Dict[str, str]:
        cstring = kwargs.get("login")
        if cstring:
            return self.get_target_by_cstring(connection_string=cstring)

        target_iothub = self.find_iothub(hub_name=hub_name, rg=rg)

        policy_name = kwargs.get("policy_name", "auto")
        rg = target_iothub.additional_properties.get("resourcegroup")

        target_policy = self.find_policy(
            hub_name=target_iothub.name, rg=rg, policy_name=policy_name,
        )

        key_type = kwargs.get("key_type", "primary")
        include_events = kwargs.get("include_events", False)
        return self._build_target(
            iothub=target_iothub,
            policy=target_policy,
            key_type=key_type,
            include_events=include_events,
        )

    def get_targets(self, rg: str = None, **kwargs) -> List[Dict[str, str]]:
        targets = []
        hubs = self.get_iothubs(rg=rg)
        if hubs:
            for hub in hubs:
                targets.append(
                    self.get_target(hub_name=hub.name, rg=self._get_rg(hub), **kwargs)
                )

        return targets

    def _get_rg(self, hub):
        return hub.additional_properties.get("resourcegroup")

    def _build_target(
        self, iothub, policy, key_type: str = None, include_events=False
    ) -> Dict[str, str]:
        # This is more or less a compatibility function which produces the
        # same result as _azure.get_iot_hub_connection_string()
        # In future iteration we will return a 'Target' object rather than dict
        # but that will be better served aligning with vNext pattern for Iot Hub

        target = {}
        target["cs"] = CONN_STR_TEMPLATE.format(
            iothub.properties.host_name,
            policy.key_name,
            policy.primary_key if key_type == "primary" else policy.secondary_key,
        )
        target["entity"] = iothub.properties.host_name
        target["policy"] = policy.key_name
        target["primarykey"] = policy.primary_key
        target["secondarykey"] = policy.secondary_key
        target["subscription"] = self.sub_id
        target["resourcegroup"] = iothub.additional_properties.get("resourcegroup")
        target["location"] = iothub.location
        target["sku_tier"] = iothub.sku.tier.value

        if include_events:
            events = {}
            events["endpoint"] = trim_from_start(
                iothub.properties.event_hub_endpoints["events"].endpoint, "sb://"
            ).strip("/")
            events["partition_count"] = iothub.properties.event_hub_endpoints[
                "events"
            ].partition_count
            events["path"] = iothub.properties.event_hub_endpoints["events"].path
            events["partition_ids"] = iothub.properties.event_hub_endpoints[
                "events"
            ].partition_ids
            target["events"] = events

        return target
