# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.util import should_disable_connection_verify
from knack.util import CLIError
import requests
from typing import Union, List
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import (
    Role,
    ApiVersion,
    UserTypePreview,
    UserTypeV1,
    get_enum_keys,
)
from azext_iot.central.models.v1 import UserV1
from azext_iot.central.models.v1_1_preview import UserV1_1_preview
from azext_iot.central.models.preview import UserPreview
from re import search

User = Union[UserV1, UserV1_1_preview, UserPreview]

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
    api_version: str,
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


def create_roles(roles: str, api_version: str):
    result_roles = []
    parsed_roles = roles.split(",")
    for role in parsed_roles:
        match = search(ROLE_PATTERN, role)
        if match and len(match.groups()) == 2:
            # role is an org role
            if api_version != ApiVersion.v1_1_preview.value:
                raise CLIError(
                    f"Api Version {ApiVersion[api_version].value} does not support organizations."
                    " Please use version >= 1.1-preview."
                )
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


def addorupdate_service_principal_user(
    cmd,
    app_id: str,
    assignee: str,
    tenant_id: str,
    object_id: str,
    roles: str,
    token: str,
    api_version: str,
    update=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> User:
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

    if api_version == ApiVersion.preview.value:
        user_type = UserTypePreview.service_principal.value
    else:
        user_type = UserTypeV1.service_principal.value

    payload = {
        "type": user_type,
    }

    if roles:
        payload["roles"] = create_roles(roles, api_version=api_version)

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


def addorupdate_email_user(
    cmd,
    app_id: str,
    assignee: str,
    email: str,
    roles: str,
    token: str,
    api_version: str,
    update=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> User:
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

    if api_version == ApiVersion.preview.value:
        user_type = UserTypePreview.email.value
    else:
        user_type = UserTypeV1.email.value

    payload = {"type": user_type, "roles": []}

    if roles:
        payload["roles"] = create_roles(roles, api_version=api_version)

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
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[User]:
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
            raise CLIError("Value is not present in body: {}".format(result))

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
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> User:
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
    api_version: str,
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
