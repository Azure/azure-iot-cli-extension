# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class Relationship:
    def __init__(self, relationship: dict):
        self.id = relationship.get("id")
        self.name = relationship.get("name")
        self.source = relationship.get("source")
        self.target = relationship.get("target")
