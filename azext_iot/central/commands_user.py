# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Union
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralUserProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.v1 import UserV1
from azext_iot.central.models.preview import UserPreview
from azext_iot.central.models.v1_1_preview import UserV1_1_preview

UserType = Union[UserV1, UserPreview, UserV1_1_preview]


def add_user(
    cmd,
    app_id: str,
    assignee: str,
    role: str,
    email=None,
    tenant_id=None,
    object_id=None,
    org_id=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> UserType:
    provider = CentralUserProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    if email:
        return provider.add_email(
            assignee=assignee,
            email=email,
            org_id=org_id,
            role=role,
            central_dns_suffix=central_dns_suffix,
        )

    return provider.add_service_principal(
        assignee=assignee,
        org_id=org_id,
        tenant_id=tenant_id,
        object_id=object_id,
        role=role,
        central_dns_suffix=central_dns_suffix,
    )


def update_user(
    cmd,
    app_id: str,
    assignee: str,
    roles=None,
    email=None,
    tenant_id=None,
    object_id=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> UserType:
    provider = CentralUserProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    if email:
        return provider.update_email_user(
            assignee=assignee,
            email=email,
            roles=roles,
            central_dns_suffix=central_dns_suffix,
        )

    return provider.update_service_principal(
        assignee=assignee,
        tenant_id=tenant_id,
        object_id=object_id,
        roles=roles,
        central_dns_suffix=central_dns_suffix,
    )


def list_users(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> List[UserType]:
    provider = CentralUserProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_user_list(
        central_dns_suffix=central_dns_suffix,
    )


def get_user(
    cmd,
    app_id: str,
    assignee: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> UserType:
    provider = CentralUserProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_user(
        assignee=assignee,
        central_dns_suffix=central_dns_suffix,
    )


def delete_user(
    cmd,
    app_id: str,
    assignee: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralUserProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.delete_user(
        assignee=assignee,
        central_dns_suffix=central_dns_suffix,
    )
