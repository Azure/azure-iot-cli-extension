# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import re


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
    def __init__(self, instance: dict, instanceName):
        self.lastUpdated = property.get("approved")
        self.value = property.get("description")
        self.instanceName = instanceName.replace("iotin:", "")
        self.pnp = "iotin:" in instanceName
        pass
