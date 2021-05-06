# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central import models as central_models
from azext_iot.central.models.enum import DeviceStatus, ApiVersion

logger = get_logger(__name__)

BASE_PATH = "api/devices"


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
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
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(url, headers=headers, params=query_parameters)
    result = _utility.try_extract_result(response)

    if api_version == ApiVersion.preview.value:
        return central_models.DevicePreview(result)
    else:
        return central_models.DeviceV1(result)


def list_devices(
    cmd,
    app_id: str,
    token: str,
    max_pages=1,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Get a list of all devices in IoTC app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of devices
    """

    devices = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (pages_processed <= max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        if api_version == ApiVersion.preview.value:
            devices = devices + [
                central_models.DevicePreview(device) for device in result["value"]
            ]
        else:
            devices = devices + [
                central_models.DeviceV1(device) for device in result["value"]
            ]

        url = result.get("nextLink", params=query_parameters)
        pages_processed = pages_processed + 1

    return devices


def get_device_registration_summary(
    cmd, app_id: str, token: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get device registration summary for a given app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        registration summary
    """

    registration_summary = {status.value: 0 for status in DeviceStatus}

    url = "https://{}.{}/{}?api-version={}".format(
        app_id, central_dns_suffix, BASE_PATH, ApiVersion.v1.value
    )
    headers = _utility.get_headers(token, cmd)

    logger.warning(
        "This command may take a long time to complete if your app contains a lot of devices"
    )

    while url:
        response = requests.get(url, headers=headers)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        for device in result["value"]:
            registration_summary[
                central_models.DeviceV1(device).device_status.value
            ] += 1

        print("Processed {} devices...".format(sum(registration_summary.values())))
        url = result.get("nextLink")

    return registration_summary


def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name: str,
    template: str,
    simulated: bool,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Create a device in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        device_name: (non-unique) human readable name for the device
        template: (optional) string that maps to the device_template_id
            of the device template that this device is to be an instance of
        simulated: if IoTC is to simulate data for this device
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    if not device_name:
        device_name = device_id

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    if api_version == ApiVersion.preview.value:
        payload = {
            "displayName": device_name,
            "simulated": simulated,
            "approved": True,
        }
        if template:
            payload["instanceOf"] = template
    else:
        payload = {
            "displayName": device_name,
            "simulated": simulated,
            "enabled": True,
        }
        if template:
            payload["template"] = template

    response = requests.put(url, headers=headers, json=payload, params=query_parameters)
    result = _utility.try_extract_result(response)

    if api_version == ApiVersion.preview.value:
        return central_models.DevicePreview(result)
    else:
        return central_models.DeviceV1(result)


def delete_device(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> dict:
    """
    Delete a device from IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        {"result": "success"} on success
        Raises error on failure
    """
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.delete(url, headers=headers, params=query_parameters)
    return _utility.try_extract_result(response)


def get_device_credentials(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Get device credentials from IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_credentials: dict
    """
    url = "https://{}.{}/{}/{}/credentials".format(
        app_id, central_dns_suffix, BASE_PATH, device_id
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(url, headers=headers, params=query_parameters)
    return _utility.try_extract_result(response)


def run_component_command(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    payload: dict,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Execute a direct method on a device

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        interface_id: interface id where command exists
        command_name: name of command to execute
        payload: params for command
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        result (currently a 201)
    """
    url = "https://{}.{}/{}/{}/components/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, interface_id, command_name
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.post(
        url, headers=headers, json=payload, params=query_parameters
    )

    # execute command response has caveats in it due to Async/Sync device methods
    # return the response if we get 201, otherwise try to apply generic logic
    if response.status_code == 201:
        return response.json()

    return _utility.try_extract_result(response)


def get_component_command_history(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Get component command history

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        interface_id: interface id where command exists
        command_name: name of command to view execution history
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Command history (List) - currently limited to 1 item
    """
    url = "https://{}.{}/{}/{}/components/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, interface_id, command_name
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(url, headers=headers, params=query_parameters)
    return _utility.try_extract_result(response)
