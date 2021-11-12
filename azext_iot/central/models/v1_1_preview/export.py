# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

class Export:
    def __init__(self, export: dict):
        self.id = export.get("id")
        self.display_name = export.get("displayName")
        self.enabled = export.get("enabled")
        self.source = export.get("source")
        self.filter = export.get("filter")
        self.destinations = export.get("destinations")
        self.errors = export.get("erros")
        self.status = export.get("status")
        self.enrichment = export.get("enrichment")