# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.util import should_disable_connection_verify
from knack.util import CLIError
import requests

from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import Role, ApiVersion, UserTypePreview, UserTypeV1

logger = get_logger(__name__)

BASE_PATH = "api/users"
MODEL = "User"


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
):
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


def add_service_principal(
    cmd,
    app_id: str,
    assignee: str,
    tenant_id: str,
    object_id: str,
    role: Role,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Add a user to a Central app

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
        "tenantId": tenant_id,
        "objectId": object_id,
        "type": user_type,
        "roles": [{"role": role.value}],
    }

    result = _make_call(
        cmd,
        app_id=app_id,
        method="put",
        path=assignee,
        payload=payload,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def add_email(
    cmd,
    app_id: str,
    assignee: str,
    email: str,
    role: Role,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Add a user to a Central app

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

    payload = {
        "email": email,
        "type": user_type,
        "roles": [{"role": role.value}],
    }

    result = _make_call(
        cmd,
        app_id=app_id,
        method="put",
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
) -> dict:
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
) -> dict:
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
