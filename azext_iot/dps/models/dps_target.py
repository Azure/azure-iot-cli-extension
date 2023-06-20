# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common._azure import parse_iot_dps_connection_string


# TODO: Align with vNext for DPS
class DPSTarget:
    def __init__(self, decomposed: dict):
        # Revisit
        decomposed_lower = dict((k.lower(), v) for k, v in decomposed.items())

        self.cs = decomposed_lower.get("cs")
        self.policy = decomposed_lower.get("sharedaccesskeyname")
        self.shared_access_key = decomposed_lower.get("sharedaccesskey")
        self.entity = decomposed_lower.get("hostname")

    @classmethod
    def from_connection_string(cls, cstring):
        decomposed = parse_iot_dps_connection_string(cs=cstring)
        decomposed["cs"] = cstring
        return cls(decomposed)

    def as_dict(self):
        return {
            "cs": self.cs,
            "policy": self.policy,
            "primarykey": self.shared_access_key,
            "entity": self.entity,
        }
