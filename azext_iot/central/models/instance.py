# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import re
from datetime import datetime, timezone, timezone


class Instance:
    def __init__(self, instance: dict, instanceName, metadata: dict):
        self.lastUpdated = instance.get("approved")
        self.value = instance.get("description")
        self.instanceName = instanceName.replace("iotin:", "")
        self.pnp = "iotin:" in instanceName
        self.property_list = self.get_property_info(instance, metadata, instanceName)

        pass

    def get_property_info(self, instance: dict, metadata: dict, instanceName):
        property_list = []
        data = metadata.get(instanceName)
        for item in instance.items():
            property_item = {
                "lastUpdated": data.get("$lastUpdated"),
                item[0]: item[1].get("value"),
            }
            property_list.append(property_item)

        return property_list


class InstanceProperty:
    def __init__(self, name: str):
        self.dataset = ()
        self.data_List = []
        self.name = name
        # self.lastUpdated = property.get("approved")
        # self.value = property.get("description")
        # self.instanceName = instanceName.replace("iotin:", "")
        # self.pnp = "iotin:" in instanceName
        pass

    def extract_print(self, time_limit, metadata: dict, data: dict, time_now: datetime):

        time_delta = time_now - self.utc_time_stamp_from_metadata(metadata)

        if time_delta <= time_limit:
            if type(data) is dict:
                for value in data:
                    if type(metadata[value]) is dict:
                        self.dataset = self.dataset + (value,)
                        result = self.extract_print(
                            time_limit, metadata[value], data[value], time_now
                        )
                        if result:
                            self.data_List.append(self.dataset)
                        self.dataset = ()

            else:
                self.dataset = self.dataset + (data,)
                return data
        return

    def utc_time_stamp_from_metadata(self, metadata: dict):
        lastUpdated = metadata.get("$lastUpdated")
        lastUpdated = lastUpdated.split(".")
        timestamp = datetime.strptime(lastUpdated[0], "%Y-%m-%dT%H:%M:%S")
        timestamp = timestamp.timestamp()
        return timestamp
