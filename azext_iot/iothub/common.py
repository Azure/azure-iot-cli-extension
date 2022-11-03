# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.
"""

from enum import Enum


SYSTEM_ASSIGNED_IDENTITY = '[system]'


class AuthenticationType(Enum):
    """
    Type of the Authentication for the routing endpoint.
    """
    KeyBased = 'keyBased'
    IdentityBased = 'identityBased'


class EncodingFormat(Enum):
    """
    Type of the encoding format for the container.
    """
    JSON = 'json'
    AVRO = 'avro'


class EndpointType(Enum):
    """
    Type of the routing endpoint.
    """
    EventHub = 'eventhub'
    ServiceBusQueue = 'servicebus-queue'
    ServiceBusTopic = 'servicebus-topic'
    AzureStorageContainer = 'storage-container'
    CosmosDBCollection = 'cosmosdb-collection'


class IdentityType(Enum):
    """
    Type of managed identity for the IoT Hub.
    """
    system_assigned = "SystemAssigned"
    user_assigned = "UserAssigned"
    system_assigned_user_assigned = "SystemAssigned, UserAssigned"
    none = "None"


class RouteSourceType(Enum):
    """
    Type of the route source.
    """
    # Invalid = 'invalid'
    DeviceMessages = 'devicemessages'
    TwinChangeEvents = 'twinchangeevents'
    DeviceLifecycleEvents = 'devicelifecycleevents'
    DeviceJobLifecycleEvents = 'devicejoblifecycleevents'
    DigitalTwinChangeEvents = 'digitaltwinchangeevents'
    DeviceConnectionStateEvents = 'deviceconnectionstateevents'

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))
