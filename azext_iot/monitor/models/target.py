# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class Target:
    def __init__(
        self,
        hostname: str,
        path: str,
        partitions: list,
        auth,  # : uamqp.authentication.SASTokenAsync,
    ):
        self.hostname = hostname
        self.path = path
        self.auth = auth
        self.partitions = partitions
        self.consumer_group = None

    def add_consumer_group(self, consumer_group: str):
        self.consumer_group = consumer_group
