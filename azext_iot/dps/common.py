# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.

"""


from enum import Enum

MAX_REGISTRATION_ASSIGNMENT_RETRIES = 5


class DeviceRegistrationStatus(Enum):
    """
    DPS Device registration status.
    """

    assigning = "assigning"
    assigned = "assigned"
    failed = "failed"