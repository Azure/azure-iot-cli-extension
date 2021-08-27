# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/roles

from typing import List
import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central import models as central_models
from azext_iot.central.models.enum import ApiVersion
from azure.cli.core.util import should_disable_connection_verify


logger = get_logger(__name__)

BASE_PATH = "api/organizations"


def get_org(
    cmd,
    app_id: str,
    org_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
) -> central_models.OrganizationPreview:
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

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, org_id)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(
        url,
        headers=headers,
        params=query_parameters,
        verify=not should_disable_connection_verify(),
    )
    result = _utility.try_extract_result(response)

    return central_models.OrganizationPreview(result)


def list_orgs(
    cmd,
    app_id: str,
    token: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
) -> List[central_models.OrganizationPreview]:
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
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(
            url,
            headers=headers,
            params=query_parameters,
            verify=not should_disable_connection_verify(),
        )
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        orgs.extend(
            [central_models.OrganizationPreview(org) for org in result["value"]]
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
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
) -> central_models.OrganizationPreview:

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

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, org_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    payload = {
        "displayName": org_name,
    }
    if parent_org:
        payload["parent"] = parent_org

    response = requests.put(url, headers=headers, json=payload, params=query_parameters)
    result = _utility.try_extract_result(response)

    return central_models.OrganizationPreview(result)
