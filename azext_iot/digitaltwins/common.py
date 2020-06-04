# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums)

"""

from enum import Enum


class ADTSkuType(Enum):
    """
    ADT SKU Type.
    """

    S1 = "S1"


class ADTLocationType(Enum):
    """
    ADT Location Type.
    """

    WestCentralUS = "westcentralus"
    WestUS2 = "westus2"
    EastUS2EUAP = "eastus2euap"


class ADTEndpointType(Enum):
    """
    ADT Location Type.
    """

    eventgridtopic = "eventgridtopic"
    servicebus = "servicebus"
    eventhub = "eventhub"
