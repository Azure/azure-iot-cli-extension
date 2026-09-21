# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    ManualInterrupt,
    ResourceNotFoundError,
)
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError
from knack.prompting import prompt_y_n

from azext_iot.common.utility import handle_service_exception
from azext_iot.core.shared import IotHubConnectionProfile
from azext_iot.iothub.providers.base import IoTHubProvider


class TopicGroup(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(TopicGroup, self).__init__(cmd, hub_name, rg, dataplane=False)
        self._validate_connection_profile()

    def create(self, topic_group_id: str, topic_templates: List[str]):
        topic_groups = self._get_topic_groups(create=True)
        if any(group.get("topicGroupId") == topic_group_id for group in topic_groups):
            raise InvalidArgumentValueError(f"Topic group '{topic_group_id}' already exists.")

        topic_groups.append(
            {
                "topicGroupId": topic_group_id,
                "topicTemplates": list(topic_templates),
            }
        )
        return self._update_hub()

    def show(self, topic_group_id: str):
        for topic_group in self._get_topic_groups():
            if topic_group.get("topicGroupId") == topic_group_id:
                return topic_group
        raise ResourceNotFoundError(f"Topic group '{topic_group_id}' was not found.")

    def list(self):
        return self._get_topic_groups()

    def update(self, topic_group_id: str, topic_templates: List[str]):
        topic_group = self.show(topic_group_id)
        topic_group["topicTemplates"] = list(topic_templates)
        return self._update_hub()

    def delete(
        self,
        topic_group_id: Optional[str] = None,
        delete_all: bool = False,
        yes: bool = False,
    ):
        topic_groups = self._get_topic_groups()
        if delete_all:
            if not yes and not prompt_y_n(
                msg=f"Confirm you want to delete all topic groups from IoT Hub '{self.hub_name}'",
                default="n",
            ):
                raise ManualInterrupt(
                    "Operation was aborted because topic group deletion was not confirmed."
                )
            topic_groups.clear()
        else:
            topic_groups.remove(self.show(topic_group_id))

        return self._update_hub()

    def _validate_connection_profile(self):
        connection_profile = self.hub_resource["properties"].get("connectionProfile")
        if (
            not isinstance(connection_profile, str)
            or connection_profile.casefold()
            != IotHubConnectionProfile.MQTT_V5.value.casefold()
        ):
            raise InvalidArgumentValueError(
                "Topic groups are only supported for IoT Hubs using the MqttV5 connection profile."
            )

    def _get_topic_groups(self, create: bool = False):
        properties = self.hub_resource["properties"]
        mqtt_v5_settings = properties.get("mqttV5Settings")
        if mqtt_v5_settings is None:
            if not create:
                return []
            mqtt_v5_settings = {}
            properties["mqttV5Settings"] = mqtt_v5_settings

        topic_groups = mqtt_v5_settings.get("topicGroups")
        if topic_groups is None:
            if not create:
                return []
            topic_groups = []
            mqtt_v5_settings["topicGroups"] = topic_groups
        return topic_groups

    def _update_hub(self):
        try:
            return self.discovery.client.begin_create_or_update(
                resource_group_name=self.hub_resource["resourcegroup"],
                resource_name=self.hub_resource["name"],
                iot_hub_description=self.hub_resource,
                etag=self.hub_resource["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except HttpResponseError as e:
            handle_service_exception(e)
