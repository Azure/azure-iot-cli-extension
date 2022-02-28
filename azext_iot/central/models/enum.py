# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Enum definitions for central

"""

from enum import Enum
from typing import List, Any


class DeviceStatus(Enum):
    """
    Type of Device status.
    """

    provisioned = "provisioned"
    registered = "registered"
    blocked = "blocked"
    unassociated = "unassociated"


class Role(Enum):
    """
    Types of roles a user can have in Central (admin, builder, etc)
    """

    admin = "ca310b8d-2f4a-44e0-a36e-957c202cd8d4"
    builder = "344138e9-8de4-4497-8c54-5237e96d6aaf"
    operator = "ae2c9854-393b-4f97-8c42-479d70ce626e"


class UserTypePreview(Enum):
    """
    Types of users , supported under the preview route, that can be added to use/manage a Central app
    (service principal, email, etc)
    """

    service_principal = "ServicePrincipalUser"
    email = "EmailUser"


class UserTypeV1(Enum):
    """
    Types of users, supported under V1/1.0 route, that can be added to use/manage a Central app
    (service principal, email, etc)
    """

    service_principal = "servicePrincipal"
    email = "email"


class ApiVersion(Enum):
    """
    API version's supported
    """

    preview = "preview"
    v1 = "1.0"
    v1_1_preview = "1.1-preview"


def get_enum_keys(enum: Enum) -> List[str]:
    return [f'{key}' for key, _ in enum.__members__.items()]


def get_enum_values(enum: Enum) -> List[Any]:
    return [item.value for _, item in enum.__members__.items()]
