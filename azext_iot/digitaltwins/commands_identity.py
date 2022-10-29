# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.resource import ResourceProvider
from knack.log import get_logger

logger = get_logger(__name__)


def assign_identity(
    cmd,
    name,
    system_identity=None,
    user_identities=None,
    identity_role=None,
    identity_scopes=None,
    resource_group_name=None
):
    rp = ResourceProvider(cmd)
    return rp.assign_identity(
        name=name,
        system_identity=system_identity,
        user_identities=user_identities,
        identity_role=identity_role,
        identity_scopes=identity_scopes,
        resource_group_name=resource_group_name,
    )


def remove_identity(
    cmd,
    name,
    system_identity=None,
    user_identities=None,
    resource_group_name=None
):
    rp = ResourceProvider(cmd)
    return rp.remove_identity(
        name=name,
        system_identity=system_identity,
        user_identities=user_identities,
        resource_group_name=resource_group_name,
    )


def show_identity(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.show_identity(
        name=name,
        resource_group_name=resource_group_name,
    )
