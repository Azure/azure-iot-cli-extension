# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class EnrollmentGroup():
    def __init__(self, group: dict):
        self.id = group.get("id")
        self.display_name = group.get("displayName")
        self.enabled = group.get("enabled")
        self.type = group.get("type")
        self.attestation = group.get("attestation")
        self.etag = group.get("etag")

    def __setitem__(self, key, newvalue):
        if key == 'x509':
            self.x509 = newvalue
