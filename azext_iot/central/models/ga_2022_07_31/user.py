# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

class User:
    def __init__(self, user: dict):
        self.id = user.get("id")
        self.type = user.get("type")
        self.roles = user.get("roles")
        self.email = user.get("email")
