# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


class Destination:
    def __init__(self, destination: dict):
        self.id = destination.get("id")
        self.display_name = destination.get("displayName")
        self.type = destination.get("type")
        self.authorization = destination.get("authorization")
        self.status = destination.get("status")
        self.error = destination.get("errors")


class WebhookDestination(Destination):
    def __init__(self, destination: dict):
        super().__init__(destination)
        self.url = destination.get("url")
        self.header_customizations = destination.get("headerCustomizations")


class AdxDestination(Destination):
    def __init__(self, destination: dict):
        super().__init__(destination)
        self.cluster_url = destination.get("clusterUrl")
        self.database = destination.get("database")
        self.table = destination.get("table")
