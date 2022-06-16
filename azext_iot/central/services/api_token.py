# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import requests

from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import ApiVersion

logger = get_logger(__name__)

BASE_PATH = "api/apiTokens"


def add_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: str,
    org_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Add an API token to a Central app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token_id: Unique ID for the API token
        role : permission level to access the application
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
    token: dict
    """
    payload = {
        "roles": [{"role": role}],
    }

    if org_id and api_version == ApiVersion.v1_1_preview.value:
        payload["roles"][0]["organization"] = org_id

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_api_token_list(
    cmd,
    app_id: str,
    token: str,
    api_version: ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Get the list of API tokens for a central app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        tokens: dict
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_api_token(
    cmd,
    app_id: str,
    token: str,
    token_id: str,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Get information about a specified API token.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        token_id: Unique ID for the API token.
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        token: dict
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def delete_api_token(
    cmd,
    app_id: str,
    token: str,
    token_id: str,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    delete API token from the app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        token_id:Unique ID for the API token.
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
       result (currently a 201)
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
