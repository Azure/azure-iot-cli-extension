# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.preview import CentralUserProviderPreview
from azext_iot.central.providers.v1 import CentralUserProviderV1
from azext_iot.central.models.enum import Role, ApiVersion


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
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralUserProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralUserProviderV1(cmd=cmd, app_id=app_id, token=token)

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


def list_users(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralUserProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralUserProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.get_user_list(central_dns_suffix=central_dns_suffix,)


def get_user(
    cmd,
    app_id: str,
    assignee: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralUserProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralUserProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.get_user(assignee=assignee, central_dns_suffix=central_dns_suffix,)


def delete_user(
    cmd,
    app_id: str,
    assignee: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralUserProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralUserProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.delete_user(
        assignee=assignee, central_dns_suffix=central_dns_suffix,
    )
