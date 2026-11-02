# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common._azure import parse_iot_hub_connection_string
from azext_iot.common.shared import HostnameType
from azext_iot.iothub.common import transform_iot_hub_hostname


def derive_iot_hub_hostnames(hostname):
    """Return the service and device hostnames for a split IoT Hub hostname."""
    parts = hostname.split(".")
    if len(parts) > 2 and parts[1].lower() in ("device", "service"):
        return (
            transform_iot_hub_hostname(hostname, HostnameType.SERVICE.value),
            transform_iot_hub_hostname(hostname, HostnameType.DEVICE.value),
        )
    return None, None


# TODO: Align with vNext for IoT Hub
class IotHubTarget:
    def __init__(self, decomposed: dict):
        # Revisit
        decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())

        self.cs = decomposed_lower.get("cs")
        self.policy = decomposed_lower.get("sharedaccesskeyname")
        self.shared_access_key = decomposed_lower.get("sharedaccesskey")
        hostname = decomposed_lower.get("hostname")
        self.service_hostname, self.device_hostname = derive_iot_hub_hostnames(hostname)
        self.entity = hostname
        self.name = self.entity.split(".")[0]

    @classmethod
    def from_connection_string(cls, cstring):
        decomposed = parse_iot_hub_connection_string(cs=cstring)
        decomposed["cs"] = cstring
        return cls(decomposed)

    def as_dict(self):
        target = {
            "cs": self.cs,
            "policy": self.policy,
            "primarykey": self.shared_access_key,
            "entity": self.entity,
            "name": self.name,
        }
        if self.service_hostname:
            target["serviceHostName"] = self.service_hostname
            target["deviceHostName"] = self.device_hostname
        return target
