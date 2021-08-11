# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

from typing import List, Union
import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central import models as central_models
from azext_iot.central.models.enum import DeviceStatus, ApiVersion
from azure.cli.core.util import should_disable_connection_verify

logger = get_logger(__name__)

BASE_PATH = "api/devices"


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> Union[central_models.DevicePreview, central_models.DeviceV1]:
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

    response = requests.get(
        url,
        headers=headers,
        params=query_parameters,
        verify=not should_disable_connection_verify(),
    )
    result = _utility.try_extract_result(response)

    if api_version == ApiVersion.preview.value:
        return central_models.DevicePreview(result)
    else:
        return central_models.DeviceV1(result)


def list_devices(
    cmd,
    app_id: str,
    token: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> List[Union[central_models.DevicePreview, central_models.DeviceV1]]:
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

    logger.warning(
        "This command may take a long time to complete if your app contains a lot of devices"
    )

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters if pages_processed == 0 else None)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        if api_version == ApiVersion.preview.value:
            devices.extend([
                central_models.DevicePreview(device) for device in result["value"]
            ])
        else:
            devices.extend([
                central_models.DeviceV1(device) for device in result["value"]
            ])

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return devices


def get_device_registration_summary(
    cmd, app_id: str, token: str, central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
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
        response = requests.get(
            url, headers=headers, verify=not should_disable_connection_verify()
        )
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
) -> Union[central_models.DevicePreview, central_models.DeviceV1]:
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


def run_command(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
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
        command_name: name of command to execute
        payload: params for command
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        result (currently a 201)
    """
    url = "https://{}.{}/{}/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, command_name
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


def get_command_history(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    command_name: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    """
    Get command history

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        command_name: name of command to view execution history
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Command history (List) - currently limited to 1 item
    """
    url = "https://{}.{}/{}/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, command_name
    )
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.get(url, headers=headers, params=query_parameters)
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


def run_manual_failover(
    cmd,
    app_id: str,
    device_id: str,
    ttl_minutes: int = None,
    token: str = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Execute a manual failover of device across multiple IoT Hubs to validate device firmware's
         ability to reconnect using DPS to a different IoT Hub.
    Args:
        cmd: command passed into az
        app_id: id of an app (used for forming request URL)
        device_id: unique case-sensitive device id
        ttl_minutes: (OPTIONAL) An optional value to specify the expiration time of this manual failover
            test before the device moves back to it's original IoT Hub.
            This has a default value of 30 minutes, but can optionally be any positive integer between 1 and 30.
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix:(OPTIONAL) {centralDnsSuffixInPath} as found in docs
    Returns:
        result (currently a 200)
    """

    url = "https://{}.{}/{}/{}/manual-failover".format(
        app_id, central_dns_suffix, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token, cmd)
    json = {}
    if ttl_minutes:
        json = {"ttl": ttl_minutes}
    else:
        print(
            """Using default time to live -
        see https://github.com/iot-for-all/iot-central-high-availability-clients#readme for more information"""
        )

    response = requests.post(
        url, headers=headers, verify=not should_disable_connection_verify(), json=json
    )
    _utility.log_response_debug(response=response, logger=logger)
    return _utility.try_extract_result(response)


def run_manual_failback(
    cmd, app_id: str, device_id: str, token: str, central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Execute a manual failback for device. Reverts the previously executed failover
         command by moving the device back to it's original IoT Hub.
    Args:
        cmd: command passed into az
        app_id: id of an app (used for forming request URL)
        device_id: unique case-sensitive device id
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs
    Returns:
        result (currently a 200)
    """

    url = "https://{}.{}/{}/{}/manual-failback".format(
        app_id, central_dns_suffix, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token, cmd)
    response = requests.post(
        url, headers=headers, verify=not should_disable_connection_verify()
    )
    _utility.log_response_debug(response=response, logger=logger)

    return _utility.try_extract_result(response)
