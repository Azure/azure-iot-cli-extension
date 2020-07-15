# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import requests

from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.enum import Role, UserType

logger = get_logger(__name__)

BASE_PATH = "api/preview/users"


def add_service_principal(
    cmd,
    app_id: str,
    assignee: str,
    tenant_id: str,
    object_id: str,
    role: Role,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
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
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, assignee)

    payload = {
        "tenantId": tenant_id,
        "objectId": object_id,
        "type": UserType.service_principal.value,
        "roles": [{"role": role.value}],
    }

    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload)
    return _utility.try_extract_result(response)


def add_email(
    cmd,
    app_id: str,
    assignee: str,
    email: str,
    role: Role,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
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
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, assignee)

    payload = {
        "email": email,
        "type": UserType.email.value,
        "roles": [{"role": role.value}],
    }

    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload)
    return _utility.try_extract_result(response)
