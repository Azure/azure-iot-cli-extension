# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import requests
from typing import List
from knack.log import get_logger

from azure.cli.core.azclierror import AzureResponseError
from azure.cli.core.util import should_disable_connection_verify
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.common import API_VERSION
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import (
    Role,
    UserTypeV1,
    get_enum_keys,
)
from azext_iot.central.models.ga_2022_07_31 import UserGa
from re import search

logger = get_logger(__name__)

BASE_PATH = "api/users"
MODEL = "User"
ROLE_PATTERN = r"([\S]+)\\\\([\S]+)"


def _make_call(
    cmd,
    app_id: str,
    method: str,
    path: str,
    payload: str,
    token: str,
    central_dns_suffix: str,
    api_version=API_VERSION,
    url=None,
) -> dict:
    if url is None:
        url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)

    if path is not None:
        url = "{}/{}".format(url, path)
    headers = _utility.get_headers(
        token, cmd, has_json_payload=True if payload is not None else False
    )

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.request(
        url=url,
        method=method.upper(),
        headers=headers,
        params=query_parameters,
        json=payload,
        verify=not should_disable_connection_verify(),
    )
    return _utility.try_extract_result(response)


def _create_roles(roles: str):
    result_roles = []
    parsed_roles = roles.split(",")
    for role in parsed_roles:
        org_id = None
        match = search(ROLE_PATTERN, role)
        if match and len(match.groups()) == 2:
            # role is an org role
            org_id = match[1]
            role_id = (
                Role[match[2]].value if match[2] in get_enum_keys(Role) else match[2]
            )
        else:
            role_id = Role[role].value if role in get_enum_keys(Role) else role

        if org_id:
            result_roles.append({"role": role_id, "organization": org_id})
        else:
            result_roles.append({"role": role_id})

    return result_roles


def add_or_update_service_principal_user(
    cmd,
    app_id: str,
    assignee: str,
    tenant_id: str,
    object_id: str,
    roles: str,
    token: str,
    api_version=API_VERSION,
    update=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> UserGa:
    """
    Add or update a user to a Central app

    Args:
        cmd: command passed into az
        tenant_id: tenant id of service principal to be added
        object_id: object id of service principal to be added
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        user: dict
    """
    api_version = API_VERSION

    user_type = UserTypeV1.service_principal.value

    payload = {
        "type": user_type,
    }

    if roles:
        payload["roles"] = _create_roles(roles)

    if tenant_id:
        payload["tenantId"] = tenant_id

    if object_id:
        payload["objectId"] = object_id

    result = _make_call(
        cmd,
        app_id=app_id,
        method="patch" if update else "put",
        path=assignee,
        payload=payload,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def add_or_update_email_user(
    cmd,
    app_id: str,
    assignee: str,
    email: str,
    roles: str,
    token: str,
    api_version=API_VERSION,
    update=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> UserGa:
    """
    Add or update a user to a Central app

    Args:
        cmd: command passed into az
        email: email of user to be added
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        user: dict
    """
    api_version = API_VERSION

    user_type = UserTypeV1.email.value

    payload = {"type": user_type, "roles": []}

    if roles:
        payload["roles"] = _create_roles(roles)

    if email and not update:
        payload["email"] = email

    result = _make_call(
        cmd,
        app_id=app_id,
        method="patch" if update else "put",
        path=assignee,
        payload=payload,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def get_user_list(
    cmd,
    app_id: str,
    token: str,
    api_version=API_VERSION,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[UserGa]:
    """
    Get the list of users for central app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        users: dict
    """
    api_version = API_VERSION

    users = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        result = _make_call(
            cmd,
            app_id=app_id,
            url=url,
            method="get",
            path=None,
            payload=None,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        users.extend(
            [_utility.get_object(user, MODEL, api_version) for user in result["value"]]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return users


def get_user(
    cmd,
    app_id: str,
    token: str,
    assignee: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> UserGa:
    """
    Get information for the specified user.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        assignee: unique ID of the user
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        users: dict
    """
    api_version = API_VERSION

    result = _make_call(
        cmd,
        app_id=app_id,
        method="get",
        path=assignee,
        payload=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def delete_user(
    cmd,
    app_id: str,
    token: str,
    assignee: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    delete user from theapp.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        assignee: unique ID of the user
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        users: dict
    """
    api_version = API_VERSION

    result = _make_call(
        cmd,
        app_id=app_id,
        method="delete",
        path=assignee,
        payload=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return result
