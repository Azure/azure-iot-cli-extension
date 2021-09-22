# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class FileUpload:
    def __init__(self, fileupload: dict):
        self.account = fileupload.get("account")
        self.connection_string = fileupload.get("connectionString")
        self.container = fileupload.get("container")
        self.sasttl = fileupload.get("sasTtl")
        self.state = fileupload.get("state")
