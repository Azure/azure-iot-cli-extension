# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

from typing import List
import requests
from knack.log import get_logger

from azure.cli.core.azclierror import (
    ResourceNotFoundError,
    BadRequestError,
)

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azure.cli.core.util import should_disable_connection_verify
from azext_iot.common.utility import dict_clean

logger = get_logger(__name__)


def get_device_twin(
    cmd,
    app_id: str,
    device_id: str,
) -> DeviceTwin:
    """
    Get device twin given a device id

    Args:
        cmd: command passed into az
        device_id: unique case-sensitive device id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        twin: dict
    """
    url = "https://{}.{}/{}/{}/get-twin?extendedInfo=true".format(
        app_id, CENTRAL_ENDPOINT, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token=None, cmd=cmd)

    # Construct parameters
    response = requests.get(
        url,
        headers=headers,
        verify=not should_disable_connection_verify(),
    )
    response_data = _utility.try_extract_result(response)
    message = response_data.get("message")

    if (
        message == f"Twin for device {device_id} was not found"
        or response_data.get("code") is not None
    ):  # there is an error
        raise ResourceNotFoundError(f"Twin for device '{device_id}' was not found")
    else:
        return DeviceTwin(response_data)


def run_manual_failover(
    cmd,
    app_id: str,
    device_id: str,
    ttl_minutes: int = None,
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
        app_id, CENTRAL_ENDPOINT, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token=None, cmd=cmd)
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
    cmd,
    app_id: str,
    device_id: str,
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
        app_id, CENTRAL_ENDPOINT, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token=None, cmd=cmd)
    response = requests.post(
        url, headers=headers, verify=not should_disable_connection_verify()
    )
    _utility.log_response_debug(response=response, logger=logger)

    return _utility.try_extract_result(response)


def purge_c2d_messages(
    cmd,
    app_id: str,
    device_id: str,
):
    """
    Purges cloud to device (C2D) message queue for the specified device.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        {
            message: 'Cloud to device (C2D) message queue purged for device {device_id}.\\n
            Total messages purged: {totalMessagesPurged}.'
        } on success
        Raises error on failure
    """
    url = "https://{}.{}/{}/{}/c2d".format(
        app_id, CENTRAL_ENDPOINT, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token=None, cmd=cmd)
    response = requests.delete(url, headers=headers)
    return _utility.try_extract_result(response)


def list_device_modules(
    cmd,
    app_id: str,
    device_id: str,
) -> List[EdgeModule]:
    """
    Get edge device modules

    Args:
        cmd: command passed into az
        device_id: unique case-sensitive device id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        modules: list
    """
    url = f"https://{app_id}.{CENTRAL_ENDPOINT}/system/iotedge/devices/{device_id}/modules"
    headers = _utility.get_headers(token=None, cmd)

    # Construct parameters
    response = requests.get(
        url,
        headers=headers,
        verify=not should_disable_connection_verify(),
    )

    response_data = _utility.try_extract_result(response).get("modules")

    if not response_data:
        raise BadRequestError(f"Device '{device_id}' is not an IoT Edge device.")

    return [EdgeModule(dict_clean(module)) for module in response_data]


def restart_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
) -> EdgeModule:
    """
    Restart a device module

    Args:
        cmd: command passed into az
        device_id: unique case-sensitive device id,
        module_id: unique case-sensitive module id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        module: dict
    """
    url = f"https://{app_id}.{CENTRAL_ENDPOINT}/system/iotedge/devices/{device_id}/modules/$edgeAgent/directmethods"
    json = {
        "methodName": "RestartModule",
        "payload": {"schemaVersion": "1.0", "id": module_id},
    }
    headers = _utility.get_headers(token=None, cmd)

    # Construct parameters
    response = requests.post(
        url,
        json=json,
        headers=headers,
        verify=not should_disable_connection_verify(),
    )

    return response.json()
