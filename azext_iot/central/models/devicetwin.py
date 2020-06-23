# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import re
from datetime import datetime, timezone, timezone


class DeviceTwin:
    def __init__(
        self, devicetwin: dict,
    ):
        self.devicetwin = devicetwin
        self.deviceid = devicetwin.get("deviceId")
        self.desiredProperty = Property(
            "desired property",
            devicetwin.get("properties").get("desired"),
            self.deviceid,
        )
        self.reportedProperty = Property(
            "reported property",
            devicetwin.get("properties").get("reported"),
            self.deviceid,
        )


class Property:
    def __init__(
        self, name: str, property_collection: dict, deviceid,
    ):
        self.name = name
        self.property_collection = property_collection
        self.property_collection_metadata = property_collection.get("$metadata")
        self.capabilities_properties = self._get_capabilities(property_collection)
        self.version = property_collection.get("$version")
        self.deviceid = deviceid
        pass

    def _get_capabilities(self, d):
        keys_to_remove = {"$metadata", "$version"}
        return {x: d[x] for x in d if x not in keys_to_remove}

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
        if time_delta <= time_limit_seconds:
            return True

        return False

    def _get_utc_time_stamp_from_metadata(self, metadata: dict):
        lastUpdated = metadata.get("$lastUpdated")
        lastUpdated = lastUpdated.split(".")
        timestamp = datetime.strptime(lastUpdated[0], "%Y-%m-%dT%H:%M:%S")
        timestamp = timestamp.timestamp()
        return timestamp

    def process_property_updates(self, timestamp: float):
        for value in self.capabilities_properties:
            updated_data = self._get_updated_data(
                self.property_collection_metadata.get(value),
                self.capabilities_properties.get(value),
                value,
                timestamp,
            )
            if updated_data:
                print(self.name, "version:", self.version)
                print(updated_data)
        return

