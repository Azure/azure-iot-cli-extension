# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralRoleProvider
from azext_iot.central.models.enum import ApiVersion


def get_role(
    cmd,
    app_id: str,
    role_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralRoleProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_role(role_id=role_id, central_dns_suffix=central_dns_suffix)


def list_roles(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralRoleProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_roles(central_dns_suffix=central_dns_suffix)
