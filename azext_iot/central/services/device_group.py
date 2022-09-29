# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/deviceGroups

from typing import List
import requests

from knack.log import get_logger

from azure.cli.core.azclierror import AzureResponseError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.ga_2022_07_31 import DeviceGroupGa
from azext_iot.central.common import API_VERSION

logger = get_logger(__name__)

BASE_PATH = "api/deviceGroups"
MODEL = "DeviceGroup"


def list_device_groups(
    cmd,
    app_id: str,
    token: str,
    api_version=API_VERSION,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[DeviceGroupGa]:
    """
    Get a list of all device groups.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of device groups
    """
    api_version = API_VERSION

    device_groups = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        for device_group in result["value"]:
            device_groups.append(DeviceGroupGa(device_group))

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return device_groups


def get_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> DeviceGroupGa:
    """
    Get a specific device group.

    Args:
        cmd: command passed into az
        device_group_id: case sensitive device group id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_group: dict
    """
    api_version = API_VERSION

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_group_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def create_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    display_name: str,
    filter: str,
    description: str,
    etag: str,
    organizations: List[str],
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> DeviceGroupGa:
    """
    Create a device group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_group_id: case sensitive device group id
        display_name: Display name of the device group
        filter: Query defining which devices should be in this group,
            or check here for more information
            https://docs.microsoft.com/en-us/azure/iot-central/core/howto-query-with-rest-api
        description: Short summary of device group
        organizations: List of organization IDs of the device group
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_group: dict
    """
    api_version = API_VERSION

    payload = {"displayName": display_name, "filter": filter}

    if description is not None:
        payload['description'] = description

    if organizations is not None:
        payload['organizations'] = organizations

    if etag is not None:
        payload['etag'] = etag

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_group_id),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def update_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    display_name: str,
    filter: str,
    description: str,
    organizations: List[str],
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> DeviceGroupGa:
    """
    Updates a device group.

    Args:
       cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_group_id: case sensitive device group id
        display_name: Display name of the device group
        filter: Query defining which devices should be in this group,
            or check here for more information
            https://docs.microsoft.com/en-us/azure/iot-central/core/howto-query-with-rest-api
        description: Short summary of device group
        organizations: List of organization IDs of the device group
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_group: dict
    """
    api_version = API_VERSION

    payload = {}
    if display_name is not None:
        payload["displayName"] = display_name

    if filter is not None:
        payload["filter"] = filter

    if description is not None:
        payload["description"] = description

    if organizations is not None:
        payload["organizations"] = organizations

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PATCH",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_group_id),
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, MODEL, api_version)


def delete_device_group(
    cmd,
    app_id: str,
    device_group_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete a device group.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_group_id: case sensitive device group id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_group: dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_group_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
