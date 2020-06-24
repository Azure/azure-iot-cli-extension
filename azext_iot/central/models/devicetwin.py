# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import re
from datetime import datetime, timezone, timezone
from azext_iot.central.models.template import Template


class DeviceTwin:
    def __init__(
        self, device_twin: dict,
    ):
        self.device_twin = device_twin
        self.device_id = device_twin.get("deviceId")
        self.desired_property = Property(
            "desired property",
            device_twin.get("properties").get("desired"),
            self.device_id,
        )
        self.reported_property = Property(
            "reported property",
            device_twin.get("properties").get("reported"),
            self.device_id,
        )


class Property:
    def __init__(
        self, name: str, property_collection: dict, device_id,
    ):
        self.name = name
        self.property_collection = property_collection
        self.property_collection_metadata = property_collection.get("$metadata")
        self.capabilities_properties = self._get_capabilities(property_collection)
        self.version = property_collection.get("$version")
        self.device_id = device_id
        pass

    def _get_capabilities(self, d):
        keys_to_remove = {"$metadata", "$version"}
        return {key: value for key, value in d.items() if key not in keys_to_remove}

    def _get_updated_data(
        self, metadata: dict, data: dict, instance_name: str, timestamp: float
    ):
        updated_data = {}
        if self._data_changed_in_time_limit(
            metadata=metadata, timestamp=timestamp, time_limit_seconds=15
        ):
            updated_data.update({instance_name: data})
        return updated_data

    def _data_changed_in_time_limit(
        self, metadata: dict, timestamp: float, time_limit_seconds: int
    ):

        time_delta = timestamp - self._get_utc_time_stamp_from_metadata(metadata)
        return time_delta <= time_limit_seconds

    def _get_utc_time_stamp_from_metadata(self, metadata: dict):
        lastUpdated = metadata.get("$lastUpdated")
        lastUpdated = lastUpdated.split(".")
        timestamp = datetime.strptime(lastUpdated[0], "%Y-%m-%dT%H:%M:%S")
        timestamp = timestamp.timestamp()
        return timestamp

    def _is_value_interface(self, value, template: Template):
        name = value.replace("$iotin:", "")
        return name in template.interfaces

    def print_property_updates(self, data):
        print(self.name, "version:", self.version)
        print(data)

    def process_property_updates(self, timestamp: float, template: Template):
        updated_properties_collection = {}
        for value in self.capabilities_properties:
            if self._is_value_interface(value, template):
                # iterate thru all the properties in the interface
                updated_properties_interface_level = {}
                for props in self.capabilities_properties[value]:
                    updated_properties_interface_level.update(
                        self._get_updated_data(
                            self.property_collection_metadata.get(value).get(props),
                            self.capabilities_properties.get(value).get(props),
                            props,
                            timestamp,
                        )
                    )

                if updated_properties_interface_level:
                    updated_properties_collection.update(
                        {value: updated_properties_interface_level}
                    )
            else:
                updated_property = self._get_updated_data(
                    self.property_collection_metadata.get(value),
                    self.capabilities_properties.get(value),
                    value,
                    timestamp,
                )
                if updated_property:
                    updated_properties_collection.update({value: updated_property})
        return updated_properties_collection
