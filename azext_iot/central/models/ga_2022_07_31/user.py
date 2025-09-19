# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

class User:
    def __init__(self, user: dict):
        self.id = user.get("id")
        self.type = user.get("type")
        self.roles = user.get("roles")
        self.email = user.get("email")
