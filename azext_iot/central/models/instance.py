# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import re
from datetime import datetime, timezone, timezone


class Property:
    def __init__(
        self, name: str, property_collection: dict, request_utc_timestamp: datetime
    ):
        self.name = name
        self.property_collection = property_collection
        self.property_collection_metadata = property_collection.get("$metadata")
        self.property_capabilities = self._get_capabilities(property_collection)
        self.version = property_collection.get("$version")
        self.request_utc_timestamp = request_utc_timestamp
        pass

    def _get_capabilities(self, d):
        keys_to_remove = {"$metadata", "$version"}
        return {x: d[x] for x in d if x not in keys_to_remove}

    def process_property_updates(self,):

        for value in self.property_capabilities:
            updated_data = self._get_updated_data(
                self.property_collection_metadata.get(value),
                self.property_capabilities.get(value),
                value,
            )
            if updated_data:
                print(self.name, "version:", self.version)
                print(updated_data)
        return

    def _get_updated_data(
        self, metadata: dict, data: dict, instance_name: str,
    ):

        updated_data = {}
        if self._data_changed_in_time_limit(metadata=metadata):
            for value in data:
                if type(data) is dict:
                    updated_data.update({"instance_name": instance_name})
                    if self._data_changed_in_time_limit(metadata=metadata[value]):
                        updated_data.update({value: data[value]})
                else:
                    updated_data.update({instance_name: data})
        return updated_data

    def _data_changed_in_time_limit(
        self, metadata: dict,
    ):
        time_limit_seconds = 15
        time_delta = (
            self.request_utc_timestamp
            - self._get_utc_time_stamp_from_metadata(metadata)
        )
        if time_delta <= time_limit_seconds:
            return True

        return False

    def _get_utc_time_stamp_from_metadata(self, metadata: dict):
        lastUpdated = metadata.get("$lastUpdated")
        lastUpdated = lastUpdated.split(".")
        timestamp = datetime.strptime(lastUpdated[0], "%Y-%m-%dT%H:%M:%S")
        timestamp = timestamp.timestamp()
        return timestamp
