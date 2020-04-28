# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Enum definitions for central

"""

from enum import Enum


class DeviceStatus(Enum):
    """
    Type of Device status.
    """

    provisioned = "provisioned"
    registered = "registered"
    blocked = "blocked"
    unassociated = "unassociated"
