# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.
"""

from enum import Enum


CA_TRANSITION_API_VERSION = "2022-04-30-preview"
HUB_PROVIDER = "Microsoft.Devices/IotHubs"
DEFAULT_ROOT_AUTHORITY = {"enableRootCertificateV2": False}

# Certificate Migration Messages
CA_TRANSITION_WARNING = "Please ensure the following: \n\
    You must update all devices to trust the DigiCert Global G2 root. \n\
    Any devices not updated will not be able to connect. \n\
    The IP address for this IoT Hub resource may change as part of this migration, \
and that it can take up to an hour for DNS servers to refresh. \n\
    The devices will be disconnected and reconnect with the DigiCert Global G2 root."
CA_REVERT_WARNING = "This will revert the resource Root Certificate to Baltimore. \n\
    Any devices without the Baltimore root will not be able to connect. \n\
    The IP address for this IoT Hub resource may change as part of this migration, \
and that it can take up to an hour for DNS servers to refresh. \n\
    The devices will be disconnected and reconnect with the Baltimore root."
CONT_INPUT_MSG = "Continue?"
ABORT_MSG = "Command was aborted."
NO_CHANGE_MSG = "Current Certificate Root Authority is already {0}. No updates are needed."


# Enums
class CertificateAuthorityVersions(Enum):
    """
    Certificate Authority Versions
    """
    v2 = "v2"
    v1 = "v1"
