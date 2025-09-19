# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

class Organization:
    def __init__(self, org: dict):
        self.display_name = org.get("displayName")
        self.id = org.get("id")
        self.parent = org.get("parent")
