# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List
from azext_iot.central.providers import CentralApiTokenProvider
from azext_iot.central.models.enum import Role
from azext_iot.sdk.central.ga_2022_05_31.models import ApiToken


def create_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: str,
    org_id=None,
) -> ApiToken:
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id
    )

    # Convert 3 role's name to id
    try:
        role = Role[role].value
    except Exception:
        pass

    return provider.create(
        token_id=token_id,
        org_id=org_id,
        role=role
    )


def list_api_tokens(
    cmd,
    app_id: str,
) -> List[ApiToken]:
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id
    )

    return provider.list()


def get_api_token(
    cmd,
    app_id: str,
    token_id: str,
) -> ApiToken:
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id
    )

    return provider.get(token_id=token_id)


def delete_api_token(
    cmd,
    app_id: str,
    token_id: str,
):
    provider = CentralApiTokenProvider(
        cmd=cmd, app_id=app_id
    )

    return provider.delete(token_id=token_id)
