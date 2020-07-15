# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralUserProvider
from azext_iot.central.models.enum import Role


def add_user(
    cmd,
    app_id: str,
    assignee: str,
    role: str,
    email=None,
    tenant_id=None,
    object_id=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralUserProvider(cmd=cmd, app_id=app_id, token=token)

    if email:
        return provider.add_email(
            assignee=assignee,
            email=email,
            role=Role[role],
            central_dns_suffix=central_dns_suffix,
        )

    return provider.add_service_principal(
        assignee=assignee,
        tenant_id=tenant_id,
        object_id=object_id,
        role=Role[role],
        central_dns_suffix=central_dns_suffix,
    )
