# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
common: Define shared data types(enums) and constant strings.
"""

from enum import Enum
from typing import NamedTuple, Optional, List, Dict
from azext_iot.sdk.iothub.service.models import ConfigurationContent


class EdgeContainerAuth(NamedTuple):
    """
    Edge container authentication datatype
    """
    serveraddress: str
    username: str
    password: str


class EdgeDeviceConfig(NamedTuple):
    """
    Individual Edge device configuration data format.
    """
    device_id: str
    deployment: Optional[ConfigurationContent] = None
    parent_id: Optional[str] = None
    hostname: Optional[str] = None
    parent_hostname: Optional[str] = None
    edge_agent: Optional[str] = None
    container_auth: Optional[EdgeContainerAuth] = None


class EdgeDevicesConfig(NamedTuple):
    """
    Edge device configuration file data format.
    """
    version: str
    auth_method: str
    root_cert: Dict[str, str]
    devices: List[EdgeDeviceConfig]
    template_config_path: Optional[str] = None
    default_edge_agent: Optional[str] = None


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

SYSTEM_ASSIGNED_IDENTITY = "[system]"
BYTES_PER_MEGABYTE = 1048576
NON_DECODABLE_PAYLOAD = "{{non-decodable payload}}"

# Message Endpoint Messages
INVALID_CLI_CORE_FOR_COSMOS = "This version of the azure cli core does not support Cosmos Db Endpoints for IoT Hub."
FORCE_DELETE_WARNING = "This delete command may fail because {0} depend on the selected endpoint(s). Use --force to force delete"\
    " the endpoint(s) and the dependent {0}."

CA_TRANSITION_API_VERSION = "2022-04-30-preview"
HUB_PROVIDER = "Microsoft.Devices/IotHubs"
DEFAULT_ROOT_AUTHORITY = {"enableRootCertificateV2": False}

# Certificate Migration Messages
CA_TRANSITION_WARNING = "Please ensure the following: \n\
    You must update all devices to trust the DigiCert Global G2 root. \n\
    Any devices not updated will not be able to connect. \n\
    The IP address for this IoT Hub resource may change as part of this migration, \
and that it can take up to an hour for devices to reconnect. \n\
    The devices will be disconnected and reconnect with the DigiCert Global G2 root."
CA_REVERT_WARNING = "This will revert the resource Root Certificate to Baltimore. \n\
    Any devices without the Baltimore root will not be able to connect. \n\
    The IP address for this IoT Hub resource may change as part of this migration, \
and that it can take up to an hour for devices to reconnect. \n\
    The devices will be disconnected and reconnect with the Baltimore root."
CONT_INPUT_MSG = "Continue?"
ABORT_MSG = "Command was aborted."
NO_CHANGE_MSG = "Current Certificate Root Authority is already {0}. No updates are needed."


class EndpointType(Enum):
    """
    Type of the message endpoint.
    """
    EventHub = "eventhub"
    ServiceBusQueue = "servicebus-queue"
    ServiceBusTopic = "servicebus-topic"
    AzureStorageContainer = "storage-container"
    CosmosDBContainer = "cosmosdb-container"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


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


class AuthenticationType(Enum):
    """
    Type of the Authentication for the routing endpoint.
    """
    KeyBased = "keyBased"
    IdentityBased = "identityBased"


class EncodingFormat(Enum):
    """
    Type of the encoding format for the container.
    """
    JSON = "json"
    AVRO = "avro"


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
    Invalid = "invalid"
    DeviceMessages = "devicemessages"
    TwinChangeEvents = "twinchangeevents"
    DeviceLifecycleEvents = "devicelifecycleevents"
    DeviceJobLifecycleEvents = "devicejoblifecycleevents"
    DigitalTwinChangeEvents = "digitaltwinchangeevents"
    DeviceConnectionStateEvents = "deviceconnectionstateevents"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))

    @classmethod
    def list_valid_types(cls):
        return list(filter(lambda d: d != RouteSourceType.Invalid.value, map(lambda c: c.value, cls)))


class CertificateAuthorityVersions(Enum):
    """
    Certificate Authority Versions
    """
    v2 = "v2"
    v1 = "v1"
