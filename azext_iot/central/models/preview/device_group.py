# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class DeviceGroup:
    def __init__(self, group: dict):
        self.display_name = group.get("displayName")
        self.id = group.get("id")
        self.organizations = group.get("organizations")
