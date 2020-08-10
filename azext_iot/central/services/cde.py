# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import requests

from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility


logger = get_logger(__name__)

BASE_PATH = "api/preview/continuousDataExports"


def add_cde(
    cmd,
    app_id: str,
    token: str,
    sources: str,
    display_name,
    export_id,
    ep_type,
    ep_conn,
    entity_name,
    enable,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Add an API token to a Central app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        sources: Data sources to export to the endpoint.
        display_name: Display name of the continuous data export
        export_id: Unique ID for the continuous data export.
        ep_type: Type of endpoint where exported data should be sent to.
        ep_conn: Connection string for the endpoint.
        entity_name: Name of entity pointing at Eg: container_name, queue_name, etc..
        enable: Boolean indicating whether the continuous data export should be running or not.
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs


    Returns:
    cde: dict
    """
    ep = {
        "type": ep_type,
        "connectionString": ep_conn,
        "name": entity_name,
    }
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, export_id)

    payload = {
        "displayName": display_name,
        "endpoint": ep,
        "enabled": enable,
        "sources": sources,
    }
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload)
    return _utility.try_extract_result(response)


def get_cde_list(
    cmd, app_id: str, token: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get the list continuous data exports in an application

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        cdes: dict
    """
    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)

    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)
    return _utility.try_extract_result(response)


def get_cde(
    cmd, app_id: str, token: str, export_id: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get information about a specified continuous data export

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        export_id: Unique ID for the continous data export
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        cde: dict
    """
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, export_id)

    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)
    return _utility.try_extract_result(response)


def delete_cde(
    cmd, app_id: str, token: str, export_id: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    delete API token from the app.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        export_id: Unique ID for the continous data export
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
       result (currently a 204)
    """
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, export_id)

    headers = _utility.get_headers(token, cmd)

    response = requests.delete(url, headers=headers)
    return _utility.try_extract_result(response)
