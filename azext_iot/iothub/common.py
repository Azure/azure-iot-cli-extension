# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum

IMMUTABLE_DEVICE_IDENTITY_FIELDS = [
    "cloudToDeviceMessageCount",
    "configurations",
    "deviceEtag",
    "deviceScope",
    "lastActivityTime",
    "parentScopes",
    "statusUpdateTime",
    "etag",
    "version",
    "deviceId"
]
IMMUTABLE_MODULE_IDENTITY_FIELDS = [
    "generationId",
    "connectionStateUpdatedTime",
    "lastActivityTime",
    "cloudToDeviceMessageCount",
    "etag",
    "deviceId",
    "moduleId",
]
IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS = [
    "deviceEtag",
    "lastActivityTime",
    "etag",
    "version",
    "cloudToDeviceMessageCount",
    "statusUpdateTime",
    "authenticationType",
    "connectionState",
    "deviceId",
    "moduleId",
    "x509Thumbprint"
]


# Enums
class EndpointType(Enum):
    """
    Type of the message endpoint.
    """
    EventHub = 'eventhub'
    ServiceBusQueue = 'servicebusqueue'
    ServiceBusTopic = 'servicebustopic'
    AzureStorageContainer = 'azurestoragecontainer'


class HubAspects(Enum):
    """
    Hub aspects to import or export.
    """
    Configurations = "configurations"
    Devices = "devices"
    Arm = "arm"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))
