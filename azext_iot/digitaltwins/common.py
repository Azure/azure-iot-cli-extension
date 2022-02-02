# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.

"""

from enum import Enum

# Retry constants
MAX_ADT_CREATE_RETRIES = 5
ADT_CREATE_RETRY_AFTER = 60
MAX_ADT_DH_CREATE_RETRIES = 20


# Data History strings
DT_IDENTITY_ERROR = "Digital Twins instance does not have System-Assigned Identity enabled. Please enable and try again."
ERROR_PREFIX = "Could not create ADT instance connection. Unable to"
FINISHED_CHECK_RESOURCE_LOG_MSG = "Finished checking the {0} resource."
ADX_ROLE_MSG = "'Database Admin' permission on the Digital Twins instance for the Azure Data Explorer database '{0}'"
RBAC_ROLE_MSG = "'{0}' role on the Digital Twins instance for the scope '{1}'"
TRY_ADD_ROLE_LOG_MSG = "Trying to add the {0}."
PRESENT_ADD_ROLE_LOG_MSG = "The {0} is already present."
FINISHED_ADD_ROLE_LOG_MSG = "Finished adding the {0}."
SKIP_MSG = "Skipping addition of the {0}. This may prevent creation of the data history connection."
FAIL_GENERIC_MSG = ERROR_PREFIX + " assign {0}. Please assign this role manually."
FAIL_RBAC_MSG = ERROR_PREFIX + " assign {0}. Please assign this role manually with the command `az {1}`."
ABORT_MSG = "Command was aborted."
ADD_INPUT_MSG = "Add the {0}?"
CONT_INPUT_MSG = "Continue with Data History connection creation anyway?"


# Enums
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
