# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class DeviceGroup:
    def __init__(self, group: dict):
        self.display_name = group.get("displayName")
        self.id = group.get("id")
        self.organizations = group.get("organizations")
        self.filter = group.get("filter")
        self.description = group.get("description")
