# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.pnp.providers.resource import RepoResourceProvider
from azext_iot.sdk.pnp.modelrepository.models import Subject


def iot_pnp_tenant_create(cmd, pnp_dns_suffix=None):
    rp = RepoResourceProvider(cmd, pnp_dns_suffix)
    return rp.create()


def iot_pnp_tenant_show(cmd, pnp_dns_suffix=None):
    rp = RepoResourceProvider(cmd, pnp_dns_suffix)
    return rp.list()


def iot_pnp_role_create(
    cmd, resource_id, resource_type, subject_id, subject_type, role, pnp_dns_suffix=None
):
    rp = RepoResourceProvider(cmd, pnp_dns_suffix)
    subject = Subject(subject_type=subject_type, role=role, resource_type=resource_type)
    return rp.add_role_assignment(
        resource_id=resource_id,
        subject=subject,
        subject_id=subject_id,
        resource_type=resource_type,
    )


def iot_pnp_role_list(
    cmd, resource_id, resource_type, subject_id=None, pnp_dns_suffix=None
):
    rp = RepoResourceProvider(cmd, pnp_dns_suffix)
    return (
        rp.get_role_assignments_for_resource(
            resource_id=resource_id, resource_type=resource_type,
        )
        if not subject_id
        else rp.get_role_assignments_for_subject(
            resource_id=resource_id, subject_id=subject_id, resource_type=resource_type,
        )
    )


def iot_pnp_role_delete(
    cmd, resource_id, resource_type, role, subject_id, pnp_dns_suffix=None
):
    rp = RepoResourceProvider(cmd, pnp_dns_suffix)
    return rp.remove_role_assignment(
        resource_id=resource_id,
        subject_id=subject_id,
        resource_type=resource_type,
        role_id=role,
    )
