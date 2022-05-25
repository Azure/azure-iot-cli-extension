# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.

"""

from enum import Enum


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


SYSTEM_IDENTITY_ARG = "[system]"
