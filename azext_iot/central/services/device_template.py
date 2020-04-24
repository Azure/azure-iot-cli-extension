# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates

import requests

from knack.util import CLIError
from knack.log import get_logger
from azext_iot.central.services import _utility

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
    Get a specific device template from IoTC

    Args:
        cmd: command passed into az
        device_template_id: case sensitive device template id,
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
    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)
    return _utility.try_extract_result(response)


def list_device_templates(
    cmd, app_id: str, token: str, central_dns_suffix="azureiotcentral.com",
) -> list:
    """
    Get a list of all device templates in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    response = requests.get(url, headers=headers)

    result = _utility.try_extract_result(response)

    if "value" not in result:
        raise CLIError("Value is not present in body: {}".format(result))

    return result["value"]


def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    payload: dict,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> list:
    """
    Create a device template in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_template_id: case sensitive device template id,
        payload: see example payload available in
            <repo-root>/azext_iot/tests/central/json/device_template_int_test.json
            or check here for more information
            https://docs.microsoft.com/en-us/rest/api/iotcentral/devicetemplates
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    response = requests.put(url, headers=headers, json=payload)
    return _utility.try_extract_result(response)


def delete_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token: str,
    central_dns_suffix="azureiotcentral.com",
) -> dict:
    """
    Delete a device template from IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_template_id: case sensitive device template id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """
    url = "https://{}.{}/{}/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_template_id
    )
    headers = _utility.get_headers(token, cmd)

    response = requests.delete(url, headers=headers)
    return _utility.try_extract_result(response)
