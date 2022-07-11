# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class ApiToken:
    def __init__(self, apitoken: dict):
        self.id = apitoken.get("id")
        self.token = apitoken.get("token")
        self.expiry = apitoken.get("expiry")
