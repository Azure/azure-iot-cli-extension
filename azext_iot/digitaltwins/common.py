# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums)

"""

from enum import Enum

MAX_ADT_CREATE_RETRIES = 5
ADT_CREATE_RETRY_AFTER = 10


class ADTEndpointType(Enum):
    """
    ADT endpoint type.
    """

    eventgridtopic = "eventgridtopic"
    servicebus = "servicebus"
    eventhub = "eventhub"


class ADTEndpointAuthType(Enum):
    """
    ADT endpoint auth type.
    """

    identitybased = "IdentityBased"
    keybased = "KeyBased"


class ADTPrivateConnectionStatusType(Enum):
    """
    ADT private endpoint connection status type.
    """

    pending = "Pending"
    approved = "Approved"
    rejected = "Rejected"
    disconnected = "Disconnected"


class ADTPublicNetworkAccessType(Enum):
    """
    ADT private endpoint connection status type.
    """

    enabled = "Enabled"
    disabled = "Disabled"


class ProvisioningStateType(Enum):
    """
    ARM poller provisioning states
    """
    FINISHED = frozenset(['succeeded', 'canceled', 'failed'])
    FAILED = frozenset(['canceled', 'failed'])
    SUCCEEDED = frozenset(['succeeded'])
