# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class DeviceTwin:
    def __init__(
        self,
        device_twin: dict,
    ):
        self.device_twin = device_twin
        if "_links" in device_twin:
            device_twin.pop("_links")

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
        self.metadata = props.get("$metadata") if props else None
        self.version = props.get("$version") if props else None
        self.device_id = device_id
