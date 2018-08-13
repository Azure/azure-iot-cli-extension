# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums); hub and dps connection string functions.

"""

from enum import Enum


# pylint: disable=too-few-public-methods
class SdkType(Enum):
    """
    Target SDK for interop.
    """
    device_query_sdk = 0
    modules_sdk = 1
    device_twin_sdk = 2
    device_msg_sdk = 3
    custom_sdk = 4
    dps_sdk = 5
    device_sdk = 6
    service_sdk = 7


# pylint: disable=too-few-public-methods
class EntityStatusType(Enum):
    """
    Resource status.
    """
    disabled = 'disabled'
    enabled = 'enabled'


# pylint: disable=too-few-public-methods
class SettleType(Enum):
    """
    Settlement state of C2D message.
    """
    complete = 'complete'
    abandon = 'abandon'
    reject = 'reject'


# pylint: disable=too-few-public-methods
class DeviceAuthType(Enum):
    """
    Device Authorization type.
    """
    shared_private_key = 'shared_private_key'
    x509_thumbprint = 'x509_thumbprint'
    x509_ca = 'x509_ca'


# pylint: disable=too-few-public-methods
class KeyType(Enum):
    """
    Shared private key.
    """
    primary = 'primary'
    secondary = 'secondary'


# pylint: disable=too-few-public-methods
class AttestationType(Enum):
    """
    Type of atestation (TMP or certificate based).
    """
    tpm = 'tpm'
    x509 = 'x509'
    symmetricKey = 'symmetricKey'


# pylint: disable=too-few-public-methods
class ProtocolType(Enum):
    """
    Device message protocol.
    """
    http = 'http'
    mqtt = 'mqtt'


# pylint: disable=too-few-public-methods
class AckType(Enum):
    """
    Type of request for acknowledgement of c2d message.
    """
    positive = 'positive'
    negative = 'negative'
    full = 'full'


# pylint: disable=too-few-public-methods
class QueryType(Enum):
    """
    Type of request for acknowledgement of c2d message.
    """
    twin = 'twin'
    job = 'job'


# pylint: disable=too-few-public-methods
class MetricType(Enum):
    """
    Type of request for acknowledgement of c2d message.
    """
    system = 'system'
    user = 'user'


# pylint: disable=too-few-public-methods
class ReprovisionType(Enum):
    """
    Type of re-provisioning for device data to different IoT Hub.
    """
    reprovisionandmigratedata = 'reprovisionandmigratedata'
    reprovisionandresetdata = 'reprovisionandresetdata'
    never = 'never'
