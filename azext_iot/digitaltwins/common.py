# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums)

"""

from enum import Enum


class ADTEndpointType(Enum):
    """
    ADT Endpoint Type.
    """

    eventgridtopic = "eventgridtopic"
    servicebus = "servicebus"
    eventhub = "eventhub"


class ADTEndpointAuthType(Enum):
    """
    ADT Endpoint Auth Type.
    """

    identitybased = "IdentityBased"
    keybased = "KeyBased"
