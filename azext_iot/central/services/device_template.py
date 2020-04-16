# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates

import requests

from knack.util import CLIError
from knack.log import get_logger
from . import _utility as utility

logger = get_logger(__name__)

BASE_PATH = "api/preview/deviceTemplates"


def get_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> dict:
    """
    Get device template given a device id

    Args:
        cmd: command passed into az
        device_template_id: case sensitive device template urn,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """
    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)

    body = response.json()

    if "error" in body:
        raise CLIError(body["error"])

    return body


def list_device_templates(
    cmd, app_id: str, token: str, central_dns_suffix="azureiotcentral.com",
) -> list:
    """
    Get device info given a device id

    Args:
        cmd: command passed into az
        device_id: unique case-sensitive device id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)

    body = response.json()

    if "error" in body:
        raise CLIError(body["error"])

    if "value" not in body:
        raise CLIError("Value is not present in body: {}".format(body))

    return body["value"]


def add_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    payload: dict,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> list:
    """
    Get device info given a device id

    Args:
        cmd: command passed into az
        device_id: unique case-sensitive device id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload)

    body = response.json()

    if "error" in body:
        raise CLIError(body["error"])

    return body
