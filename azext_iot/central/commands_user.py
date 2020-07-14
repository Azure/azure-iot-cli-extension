# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralUserProvider
from azext_iot.central.models.enum import Role


def add_service_principal(
    cmd,
    app_id: str,
    user_id: str,
    tenant_id: str,
    object_id: str,
    role: Role.admin.name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralUserProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.add_service_principal(
        user_id=user_id,
        tenant_id=tenant_id,
        object_id=object_id,
        role=Role[role],
        central_dns_suffix=central_dns_suffix,
    )
