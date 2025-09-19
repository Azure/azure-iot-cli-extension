# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.resource import ResourceProvider
from knack.log import get_logger

logger = get_logger(__name__)


def assign_role(cmd, name, role_type, assignee, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.assign_role(
        name=name,
        role_type=role_type,
        assignee=assignee,
        resource_group_name=resource_group_name,
    )


def remove_role(cmd, name, assignee=None, role_type=None, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.remove_role(
        name=name,
        assignee=assignee,
        role_type=role_type,
        resource_group_name=resource_group_name,
    )


def list_assignments(
    cmd, name, include_inherited=False, role_type=None, resource_group_name=None
):
    rp = ResourceProvider(cmd)
    return rp.get_role_assignments(
        name=name,
        include_inherited=include_inherited,
        resource_group_name=resource_group_name,
        role_type=role_type,
    )
