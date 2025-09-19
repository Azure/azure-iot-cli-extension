# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class Export:
    def __init__(self, export: dict):
        self.id = export.get("id")
        self.display_name = export.get("displayName")
        self.enabled = export.get("enabled")
        self.source = export.get("source")
        self.filter = export.get("filter")
        self.destinations = export.get("destinations")
        self.errors = export.get("errors")
        self.status = export.get("status")
        self.enrichment = export.get("enrichments")
