# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common._azure import parse_iot_hub_connection_string
from azext_iot.common.shared import AuthenticationTypeDataplane


# TODO: Align with vNext for IoT Hub
class IotHubTarget:
    def __init__(self, decomposed: dict):
        # Revisit
        decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())
        login = AuthenticationTypeDataplane.login.value

        self.cs = decomposed_lower.get("cs", login)
        self.policy = decomposed_lower.get("sharedaccesskeyname", login)
        self.shared_access_key = decomposed_lower.get("sharedaccesskey", login)
        self.entity = decomposed_lower.get("hostname")
        self.name = self.entity.split(".")[0]

    @classmethod
    def from_connection_string(cls, cstring):
        decomposed = parse_iot_hub_connection_string(cs=cstring)
        decomposed["cs"] = cstring
        return cls(decomposed)

    @classmethod
    def from_host_name(cls, hostname):
        return cls({"hostname": hostname})

    def as_dict(self):
        return {
            "cs": self.cs,
            "policy": self.policy,
            "primarykey": self.shared_access_key,
            "entity": self.entity,
            "name": self.name
        }
