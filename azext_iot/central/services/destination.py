# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/1.1-previewdataplane/destinations
from typing import List, Union
from knack.log import get_logger

from azure.cli.core.azclierror import AzureResponseError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.v2022_06_30_preview import (
    DestinationPreview,
    WebhookDestinationPreview,
    AdxDestinationPreview,
)
from azext_iot.central.services import _utility
from azext_iot.central.common import API_VERSION_PREVIEW


logger = get_logger(__name__)

BASE_PATH = "api/dataExport/destinations"


def add_destination(
    cmd,
    app_id: str,
    destination_id: str,
    payload,
    token: str,
    api_version=API_VERSION_PREVIEW,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    """
    Add an data export destinations to IoT Central app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        destination_id: unique identifier of destination
        payload: destination JSON definition
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Destination
    """
    api_version = API_VERSION_PREVIEW

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, destination_id
    )

    return _utility.make_api_call(
        cmd,
        app_id,
        method="PUT",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def update_destination(
    cmd,
    app_id: str,
    destination_id: str,
    payload: str,
    token: str,
    api_version=API_VERSION_PREVIEW,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    """
    Update an data export destination in IoT Central app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        destination_id: unique identifier for destination
        payload: destination JSON definition
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Destination
    """
    api_version = API_VERSION_PREVIEW

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, destination_id
    )

    return _utility.make_api_call(
        cmd,
        app_id,
        method="PATCH",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def list_destinations(
    cmd,
    app_id: str,
    token: str,
    max_pages=0,
    api_version=API_VERSION_PREVIEW,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[
    Union[
        DestinationPreview,
        WebhookDestinationPreview,
        AdxDestinationPreview,
    ]
]:
    """
    Get the list of destinations for a central app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        max_pages: max return result pages
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        List of destinations
    """
    api_version = API_VERSION_PREVIEW

    destinations = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        result = _utility.make_api_call(
            cmd,
            app_id,
            method="GET",
            url=url,
            payload=None,
            token=token,
            api_version=api_version,
            central_dnx_suffix=central_dns_suffix,
        )

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        destinations.extend(result.get("value", []))

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return destinations


def get_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token: str,
    api_version=API_VERSION_PREVIEW,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    """
    Get information about a specified destination.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        destination_id: unique identifier of destination
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Destination
    """
    api_version = API_VERSION_PREVIEW

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, destination_id
    )

    return _utility.make_api_call(
        cmd,
        app_id,
        method="GET",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def delete_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token: str,
    api_version=API_VERSION_PREVIEW,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete data export destination from Central app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        destination_id: unique identifier of destination
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        response dict
    """
    api_version = API_VERSION_PREVIEW

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, destination_id
    )

    return _utility.make_api_call(
        cmd,
        app_id,
        method="DELETE",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
