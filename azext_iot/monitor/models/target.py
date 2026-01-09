# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


class Target:
    def __init__(
        self,
        hostname: str,
        path: str,
        partitions: list,
        policy: str = None,
        key: str = None,
        sas_credential=None,  # AzureSasCredential for IoT Central
    ):
        self.hostname = hostname
        self.path = path
        self.sas_credential = sas_credential  # IoT Central: Pre-generated SAS token credential
        self.partitions = partitions
        self.consumer_group = None
        self.policy = policy  # IoT Hub: Shared access policy name
        self.key = key  # IoT Hub: Shared access key

    def add_consumer_group(self, consumer_group: str):
        self.consumer_group = consumer_group
