# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class DeviceTwin:
    def __init__(
        self,
        device_twin: dict,
    ):
        self.device_twin = device_twin
        if "_links" in device_twin:
            device_twin.pop("_links")
        if "tags" in device_twin:
            device_twin.pop("tags")

        self.device_id = device_twin.get("deviceId")
        self.desired_property = Property(
            "desired property",
            device_twin.get("properties", {}).get("desired"),
            self.device_id,
        )
        self.reported_property = Property(
            "reported property",
            device_twin.get("properties", {}).get("reported"),
            self.device_id,
        )


class Property:
    def __init__(
        self,
        name: str,
        props: dict,
        device_id,
    ):
        self.name = name
        self.props = props
        self.metadata = props.get("$metadata")
        self.version = props.get("$version")
        self.device_id = device_id
