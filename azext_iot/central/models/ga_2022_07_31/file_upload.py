# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class FileUpload:
    def __init__(self, fileupload: dict):
        self.account = fileupload.get("account")
        self.connection_string = fileupload.get("connectionString")
        self.container = fileupload.get("container")
        self.sas_ttl = fileupload.get("sasTtl")
        self.state = fileupload.get("state")
