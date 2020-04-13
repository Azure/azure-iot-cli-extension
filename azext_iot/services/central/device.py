# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

import requests

from ._utility import get_token


def get_device(
    cmd,
    device_id: str,
    app_id: str,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> str:
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

    if not token:
        token = get_token(token, cmd)

    url = "https://{}.{}/api/preview/devices/{}".format(
        app_id, central_dns_suffix, device_id
    )
    headers = {"Authorization": token}

    response = requests.get(url, headers=headers)

    body = response.json()

    if "error" in body:
        raise Exception(body["error"])

    return body
