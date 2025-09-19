# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class ApiToken:
    def __init__(self, apitoken: dict):
        self.id = apitoken.get("id")
        self.token = apitoken.get("token")
        self.expiry = apitoken.get("expiry")
