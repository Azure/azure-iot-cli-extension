# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralApiTokenProvider
from azext_iot.central.models.enum import Role


def add_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralApiTokenProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.add_api_token(
        token_id=token_id, role=Role[role], central_dns_suffix=central_dns_suffix,
    )


def list_api_tokens(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralApiTokenProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.get_api_token_list(central_dns_suffix=central_dns_suffix,)


def get_api_token(
    cmd, app_id: str, token_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralApiTokenProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.get_api_token(
        token_id=token_id, central_dns_suffix=central_dns_suffix
    )


def delete_api_token(
    cmd, app_id: str, token_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralApiTokenProvider(cmd=cmd, app_id=app_id, token=token)

    return provider.delete_api_token(
        token_id=token_id, central_dns_suffix=central_dns_suffix
    )
