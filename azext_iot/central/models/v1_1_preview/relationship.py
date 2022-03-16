# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class Relationship:
    def __init__(self, relationship: dict):
        self.id = relationship.get("id")
        self.name = relationship.get("name")
        self.source = relationship.get("source")
        self.target = relationship.get("target")
