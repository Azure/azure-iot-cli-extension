# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types

"""

from enum import Enum

EDGE_ONLY = "type eq 'GatewayDevice' or type eq 'EdgeDevice'"


class DestinationType(Enum):
    """
    Data Export destination type.
    """

    Webhook = "webhook@v1"
    BlobStorage = "blobstorage@v1"
    AzureDataExplorer = "dataexplorer@v1"
    ServiceBusQueue = "servicebusqueue@v1"
    ServiceBusTopic = "servicebustopic@v1"
    EventHub = "eventhubs@v1"


class ExportSource(Enum):
    """
    Data Export Source.
    """

    Telemetry = "telemetry"
    Properties = "properties"
    DeviceLifecycle = "deviceLifecycle"
    DeviceTemplateLifecycle = "deviceTemplateLifecycle"
    DeviceConnectivity = "deviceConnectivity"
