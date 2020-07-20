# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums)
"""

from enum import Enum


class RoleResourceType(Enum):
    """
    Type of the Resource
    """

    model = "Model"
    tenant = "Tenant"


class RoleIdentifier(Enum):
    """
    Role Identifier
    """

    modelsPublisher = "ModelsPublisher"
    modelsCreator = "ModelsCreator"
    tenantAdmin = "TenantAdministrator"
    modelAdmin = "ModelAdministrator"
    modelReader = "ModelReader"


class SubjectType(Enum):
    """
    Subject type.
    """

    user = "User"
    servicePrincipal = "ServicePrincipal"


class ModelType(Enum):
    """
    Type of Model
    """

    interface = "Interface"
    undetermined = "Undetermined"


class ModelState(Enum):
    """
    State of a model
    """

    created = "Created"
    listed = "Listed"
