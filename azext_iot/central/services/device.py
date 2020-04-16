# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

import requests

from knack.util import CLIError
from . import _utility as utility

BASE_PATH = "api/preview/devices"


def get_device(
    cmd,
    device_id: str,
    app_id: str,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> dict:
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

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id)
    headers = utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)

    body = response.json()

    if "error" in body:
        raise CLIError(body["error"])

    return body


def list_devices(
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


def add_device(
    cmd,
    token: str,
    app_id: str,
    device_id: str,
    device_name: str,
    instance_of: str,
    simulated: bool,
    central_dns_suffix="azureiotcentral.com",
) -> dict:
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

    if not device_name:
        device_name = device_id

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id)
    headers = utility.get_headers(token, cmd, has_json_payload=True)
    body = {
        "displayName": device_name,
        "simualted": simulated,
        "approved": True,
    }
    if instance_of:
        body["instanceOf"] = instance_of

    response = requests.put(url, headers=headers, json=body)

    body = response.json()

    if "error" in body:
        raise CLIError(body["error"])

    return body
