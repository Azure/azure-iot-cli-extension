# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums).

"""

from enum import Enum


# pylint: disable=too-few-public-methods
class EndpointType(Enum):
    """
    Type of the routing endpoint.
    """

    EventHub = "eventhub"
    ServiceBusQueue = "servicebusqueue"
    ServiceBusTopic = "servicebustopic"
    AzureStorageContainer = "azurestoragecontainer"


# pylint: disable=too-few-public-methods
class RouteSourceType(Enum):
    """
    Type of the route source.
    """

    Invalid = "invalid"
    DeviceMessages = "devicemessages"
    TwinChangeEvents = "twinchangeevents"
    DeviceLifecycleEvents = "devicelifecycleevents"
    DeviceJobLifecycleEvents = "devicejoblifecycleevents"
    DigitalTwinChangeEvents = "digitaltwinchangeevents"
    DeviceConnectionStateEvents = "deviceconnectionstateevents"


# pylint: disable=too-few-public-methods
class EncodingFormat(Enum):
    """
    Type of the encoding format for the container.
    """

    JSON = "json"
    AVRO = "avro"


# pylint: disable=too-few-public-methods
class RenewKeyType(Enum):
    """
    Type of the RegenerateKey for the authorization policy.
    """

    Primary = "primary"
    Secondary = "secondary"
    Swap = "swap"


# pylint: disable=too-few-public-methods
class AuthenticationType(str, Enum):
    """
    Type of the Authentication for the routing endpoint.
    """

    KeyBased = "keyBased"
    IdentityBased = "identityBased"


# pylint: disable=too-few-public-methods
class IdentityType(Enum):
    """
    Type of managed identity for the IoT Hub.
    """

    system_assigned = "SystemAssigned"
    user_assigned = "UserAssigned"
    system_assigned_user_assigned = "SystemAssigned, UserAssigned"
    none = "None"


class ManagedServiceIdentityType(str, Enum):
    """Type of managed service identity (DPS)."""

    NONE = "None"
    SYSTEM_ASSIGNED = "SystemAssigned"
    USER_ASSIGNED = "UserAssigned"
    SYSTEM_ASSIGNED_USER_ASSIGNED = "SystemAssigned,UserAssigned"


class IotHubSku(Enum):
    """The name of the IoT Hub SKU."""

    F1 = "F1"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"


class IotDpsSku(Enum):
    """DPS SKU name."""

    S1 = "S1"


class IotHubAuthenticationType(Enum):
    """Authentication type for DPS linked IoT Hub."""

    KEY_BASED = "KeyBased"
    SYSTEM_ASSIGNED = "SystemAssigned"
    USER_ASSIGNED = "UserAssigned"


class AccessRightsDescription(str, Enum):
    """DPS access rights."""

    SERVICE_CONFIG = "ServiceConfig"
    ENROLLMENT_READ = "EnrollmentRead"
    ENROLLMENT_WRITE = "EnrollmentWrite"
    DEVICE_CONNECT = "DeviceConnect"
    REGISTRATION_STATUS_READ = "RegistrationStatusRead"
    REGISTRATION_STATUS_WRITE = "RegistrationStatusWrite"


class AccessRights(str, Enum):
    """IoT Hub shared access policy rights."""

    REGISTRY_READ = "RegistryRead"
    REGISTRY_WRITE = "RegistryWrite"
    SERVICE_CONNECT = "ServiceConnect"
    DEVICE_CONNECT = "DeviceConnect"
    REGISTRY_READ_REGISTRY_WRITE = "RegistryRead, RegistryWrite"
    REGISTRY_READ_SERVICE_CONNECT = "RegistryRead, ServiceConnect"
    REGISTRY_READ_DEVICE_CONNECT = "RegistryRead, DeviceConnect"
    REGISTRY_WRITE_SERVICE_CONNECT = "RegistryWrite, ServiceConnect"
    REGISTRY_WRITE_DEVICE_CONNECT = "RegistryWrite, DeviceConnect"
    SERVICE_CONNECT_DEVICE_CONNECT = "ServiceConnect, DeviceConnect"
    REGISTRY_READ_REGISTRY_WRITE_SERVICE_CONNECT = "RegistryRead, RegistryWrite, ServiceConnect"
    REGISTRY_READ_REGISTRY_WRITE_DEVICE_CONNECT = "RegistryRead, RegistryWrite, DeviceConnect"
    REGISTRY_READ_SERVICE_CONNECT_DEVICE_CONNECT = "RegistryRead, ServiceConnect, DeviceConnect"
    REGISTRY_WRITE_SERVICE_CONNECT_DEVICE_CONNECT = "RegistryWrite, ServiceConnect, DeviceConnect"
    REGISTRY_READ_REGISTRY_WRITE_SERVICE_CONNECT_DEVICE_CONNECT = "RegistryRead, RegistryWrite, ServiceConnect, DeviceConnect"
