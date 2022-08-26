# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class EnrollmentGroup:
    def __init__(self, group: dict):
        self.id = group.get("id")
        self.display_name = group.get("displayName")
        self.enabled = group.get("enabled")
        self.type = group.get("type")
        self.attestation = group.get("attestation")
        self.etag = group.get("etag")
