# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.

"""
from enum import Enum
from typing import List


class ADUPublicNetworkAccessType(Enum):
    """
    ADU public network access type.
    """

    ENABLED = "Enabled"
    DISABLED = "Disabled"


class ADUPrivateLinkServiceConnectionStatus(Enum):
    """
    ADU private link service connection status.
    """

    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class ADUAccountSKUType(Enum):
    """
    ADU account sku types.
    """

    STANDARD = "Standard"
    FREE = "Free"


class ADUInstanceDiagnosticStorageAuthType(Enum):
    """
    ADU instance diagnostic storage auth type.
    """

    KEYBASED = "KeyBased"


class ADUManageDeviceImportType(Enum):
    """
    ADU management device import type.
    """

    #: Import only devices but not modules.
    DEVICES = "Devices"
    #: Import only modules but not devices.
    MODULES = "Modules"
    #: Import both devices and modules.
    ALL = "All"


class ADUValidHashAlgorithmType(Enum):
    """
    ADU valid cryptographic hash algorithms.
    """

    SHA256 = "sha256"


class ADUContentHandlerType(Enum):
    """
    ADU first-party content handler types.
    """

    APT_V1 = "microsoft/apt:1"
    SCRIPT_V1 = "microsoft/script:1"
    SIMULATOR_V1 = "microsoft/simulator:1"
    SWUPDATE_V1 = "microsoft/swupdate:1"
    SWUPDATE_V2 = "microsoft/swupdate:2"
    WIM_V1 = "microsoft/wim:1"


FP_HANDLERS: List[str] = [
    ADUContentHandlerType.APT_V1.value,
    ADUContentHandlerType.SCRIPT_V1.value,
    ADUContentHandlerType.SIMULATOR_V1.value,
    ADUContentHandlerType.SWUPDATE_V1.value,
    ADUContentHandlerType.SWUPDATE_V2.value,
    ADUContentHandlerType.WIM_V1.value,
]


FP_HANDLERS_REQUIRE_CRITERIA: List[str] = [
    ADUContentHandlerType.APT_V1.value,
    ADUContentHandlerType.SWUPDATE_V1.value,
    ADUContentHandlerType.SWUPDATE_V2.value,
]


SYSTEM_IDENTITY_ARG = "[system]"
AUTH_RESOURCE_ID = "https://api.adu.microsoft.com/"
CACHE_RESOURCE_TYPE = "DeviceUpdate"


def get_cache_entry_name(account_name: str, instance_name: str):
    return f"{account_name}_{instance_name}_importUpdate"
