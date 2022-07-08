# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralApiTokenProvider
from azext_iot.central.models.enum import Role, ApiVersion


def add_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: str,
    org_id=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    try:
        role = Role[role].value
    except Exception:
        pass

    return provider.add_api_token(
        token_id=token_id,
        org_id=org_id,
        role=role,
        central_dns_suffix=central_dns_suffix,
    )


def list_api_tokens(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> List[dict]:

    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_api_token_list(central_dns_suffix=central_dns_suffix)


def get_api_token(
    cmd,
    app_id: str,
    token_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
):

    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_api_token(
        token_id=token_id,
        central_dns_suffix=central_dns_suffix,
    )


def delete_api_token(
    cmd,
    app_id: str,
    token_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_api_token(
        token_id=token_id,
        central_dns_suffix=central_dns_suffix,
    )
