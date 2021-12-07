# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/roles

from typing import List, Union
import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.v1_1_preview import OrganizationV1_1_preview
from azure.cli.core.util import should_disable_connection_verify


logger = get_logger(__name__)

BASE_PATH = "api/organizations"
MODEL = "Organization"


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
) -> Union[dict, OrganizationV1_1_preview]:
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


def get_org(
    cmd,
    app_id: str,
    org_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> OrganizationV1_1_preview:
    """
    Get organization info given an organization id

    Args:
        cmd: command passed into az
        org_id: unique case-sensitive organization id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch role details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        role: dict
    """

    result = _make_call(
        cmd,
        app_id=app_id,
        method="get",
        path=org_id,
        payload=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def list_orgs(
    cmd,
    app_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[OrganizationV1_1_preview]:
    """
    Get a list of all organizations in IoTC app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch role details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of organizations
    """

    orgs = []

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

        orgs.extend(
            [_utility.get_object(org, MODEL, api_version) for org in result["value"]]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return orgs


def create_org(
    cmd,
    app_id: str,
    org_id: str,
    org_name: str,
    parent_org: str,
    token: str,
    update: bool,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> OrganizationV1_1_preview:

    """
    Create an organization in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        org_id: unique case-sensitive organization id
        org_name: (non-unique) human readable name for the organization
        parent_org: (optional) parent organization.
        token: (OPTIONAL) authorization token to fetch organization details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        organization: dict
    """

    if not org_name:
        org_name = org_id

    payload = {
        "displayName": org_name,
    }
    if parent_org:
        payload["parent"] = parent_org

    result = _make_call(
        cmd,
        app_id=app_id,
        method="patch" if update else "put",
        path=org_id,
        payload=payload,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return _utility.get_object(result, MODEL, api_version)


def delete_org(
    cmd,
    app_id: str,
    org_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> OrganizationV1_1_preview:
    """
    Delete an organization

    Args:
        cmd: command passed into az
        org_id: unique case-sensitive organization id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch role details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        role: dict
    """

    result = _make_call(
        cmd,
        app_id=app_id,
        method="delete",
        path=org_id,
        payload=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return result
