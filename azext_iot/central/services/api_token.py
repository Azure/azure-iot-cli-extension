# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import requests
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import Role
from azure.cli.core.util import should_disable_connection_verify

logger = get_logger(__name__)

BASE_PATH = "api/preview/apiTokens"


def add_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: Role,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Add an API token to a Central app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token_id: Unique ID for the API token.
        role : permission level to access the application
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
    token: dict
    """
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id)

    payload = {
        "roles": [{"role": role.value}],
    }

    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload, verify=not should_disable_connection_verify())
    return _utility.try_extract_result(response)


def get_api_token_list(
    cmd, app_id: str, token: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
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
    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)

    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers, verify=not should_disable_connection_verify())
    return _utility.try_extract_result(response)


def get_api_token(
    cmd, app_id: str, token: str, token_id: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
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
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id)

    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers, verify=not should_disable_connection_verify())
    return _utility.try_extract_result(response)


def delete_api_token(
    cmd, app_id: str, token: str, token_id: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
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
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, token_id)

    headers = _utility.get_headers(token, cmd)

    response = requests.delete(url, headers=headers, verify=not should_disable_connection_verify())
    return _utility.try_extract_result(response)
