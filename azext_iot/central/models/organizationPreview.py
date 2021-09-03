# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

class OrganizationPreview:
    def __init__(self, org: dict):
        self.display_name = org.get("displayName")
        self.id = org.get("id")
