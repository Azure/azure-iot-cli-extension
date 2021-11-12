# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/1.1-previewdataplane/destinations
from typing import List, Union

from knack.log import get_logger
from knack.util import CLIError
from azext_iot.central.models.enum import ApiVersion

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.v1_1_preview import DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview
from azext_iot.central.services import _utility

logger = get_logger(__name__)

BASE_PATH = "api/dataExport/destinations"

def add_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    payload: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT
) -> Union[DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview]:
    """
    Add an data export destinations to IoT Central app

    Args:
        cmd: command passed into az
    """

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, destination_id)

    return _utility.make_api_call(
        cmd,
        app_id,
        method="PUT",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix
    )

def update_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    payload: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT
) -> Union[DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview]:
    """
    Update an data export destination in IoT Central app

    Args:
        cmd: command passed into az
    """

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, destination_id)

    return _utility.make_api_call(
        cmd,
        app_id,
        method="PATCH",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix
    )

def list_dataExport_destinations(
    cmd,
    app_id: str,
    token: str,
    max_pages=0,
    api_version=ApiVersion.v1_1_preview.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview]]:
    """
    Get the list of destinations for a central app.

    Args:
        cmd: command passed into az

    """
    destinations = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        result =  _utility.make_api_call(
            cmd,
            app_id,
            method="GET",
            url=url,
            payload=None,
            token=token,
            api_version=api_version,
            central_dnx_suffix=central_dns_suffix
        )

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        destinations.extend(
            result.get("value", [])
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1
    
    return destinations

def get_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token: str,
    api_version=ApiVersion.v1_1_preview.value,
    central_dns_suffix=CENTRAL_ENDPOINT
) -> Union[DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview]:
    """
    Get information about a specified destination.

    Args:
        cmd: command passed into az
    """

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, destination_id)

    return _utility.make_api_call(
        cmd,
        app_id,
        method="GET",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix
    )

def delete_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token: str,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete data export destination from Central app.

    Args:
        cmd: command passed into az
    """

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, destination_id)

    return _utility.make_api_call(
        cmd,
        app_id,
        method="DELETE",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix
    )