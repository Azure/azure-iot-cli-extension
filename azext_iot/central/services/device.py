# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/devices

from typing import List, Union
import requests
from azext_iot.central.common import EDGE_ONLY_FILTER
from azext_iot.central.models.edge import EdgeModule
from azext_iot.common.auth import get_aad_token

from knack.log import get_logger

from azure.cli.core.azclierror import (
    AzureResponseError,
    ResourceNotFoundError,
    BadRequestError,
)
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.preview import DevicePreview
from azext_iot.central.models.v1 import DeviceV1
from azext_iot.central.models.v1_1_preview import (
    DeviceV1_1_preview,
    RelationshipV1_1_preview,
)
from azext_iot.central.models.enum import ApiVersion, DeviceStatus
from azure.cli.core.util import should_disable_connection_verify
from azext_iot.common.utility import dict_clean, parse_entity

logger = get_logger(__name__)

BASE_PATH = "api/devices"
MODEL = "Device"
REL_MODEL = "Relationship"


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[DeviceV1_1_preview, DeviceV1, DevicePreview]:
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
    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )

    return _utility.get_object(result, MODEL, api_version)


def list_devices(
    cmd,
    app_id: str,
    filter: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[DeviceV1, DeviceV1_1_preview, DevicePreview]]:
    """
    Get a list of all devices in IoTC app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        filter: only show filtered devices
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
    query_parameters = (
        {"$filter": filter} if api_version == ApiVersion.v1_1_preview.value else {}
    )
    query_parameters["api-version"] = api_version

    warning = "This command may take a long time to complete if your app contains a lot of devices."
    if (
        filter
        and filter == EDGE_ONLY_FILTER
        and api_version != ApiVersion.v1_1_preview.value
    ):
        warning += (
            "\nAlso consider using Api Version 1.1-preview when listing edge devices "
            "as it supports server filtering speeding up the process."
        )
    logger.warning(warning)

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(
            url,
            headers=headers,
            params=query_parameters if pages_processed == 0 else None,
        )
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        devices.extend(
            [
                _utility.get_object(device, MODEL, api_version)
                for device in result["value"]
            ]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return devices


def get_device_registration_summary(
    cmd,
    app_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
        app_id, central_dns_suffix, BASE_PATH, api_version
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
            raise AzureResponseError("Value is not present in body: {}".format(result))

        for device in result["value"]:
            registration_summary[
                (_utility.get_object(device, MODEL, api_version))._device_status.value
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
    organizations: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[DeviceV1, DeviceV1_1_preview, DevicePreview]:
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

    payload = {"displayName": device_name, "simulated": simulated, "enabled": True}

    if template:
        payload["template"] = template

    if organizations:
        payload["organizations"] = organizations.split(",")

    data = _utility.get_object(payload, MODEL, api_version)
    json = _utility.to_camel_dict(dict_clean(parse_entity(data)))
    response = requests.put(url, headers=headers, json=json, params=query_parameters)
    result = _utility.try_extract_result(response)

    return _utility.get_object(result, MODEL, api_version)


def update_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name: str,
    template: str,
    simulated: bool,
    enabled: bool,
    organizations: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[DeviceV1, DeviceV1_1_preview, DevicePreview]:
    """
    Update a device in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        device_name: (non-unique) human readable name for the device
        template: (optional) string that maps to the device_template_id
            of the device template that this device is to be an instance of
        simulated: if IoTC is to simulate data for this device
        enabled: if device is enabled
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    current_device = get_device(
        cmd=cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        api_version=api_version,
        central_dns_suffix=central_dns_suffix,
    )

    payload = dict_clean(parse_entity(current_device))

    if device_name is not None:
        payload["displayName"] = device_name

    if template is not None:
        payload["template"] = template

    if enabled is not None:
        payload["enabled"] = enabled

    if simulated is not None:
        payload["simulated"] = simulated

    if organizations is not None:
        payload["organizations"] = organizations.split(",")

    # sanitize device payload based on apiversion

    data = _utility.get_object(payload, MODEL, api_version)
    json = _utility.to_camel_dict(dict_clean(parse_entity(data)))

    response = requests.patch(
        url,
        headers=headers,
        json=json,
        params=query_parameters,
    )
    result = _utility.try_extract_result(response)

    return _utility.get_object(result, MODEL, api_version)


def delete_device(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def list_relationships(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[RelationshipV1_1_preview]:

    url = "https://{}.{}/{}/{}/relationships".format(
        app_id, central_dns_suffix, BASE_PATH, device_id
    )
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    relationships = []
    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(
            url,
            headers=headers,
            params=query_parameters if pages_processed == 0 else None,
        )
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        relationships.extend(
            [
                _utility.get_object(relationship, REL_MODEL, api_version)
                for relationship in result["value"]
            ]
        )

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return relationships


def create_relationship(
    cmd,
    app_id: str,
    device_id: str,
    target_id: str,
    rel_id: str,
    rel_name: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):

    payload = {"id": rel_id, "name": rel_name, "source": device_id, "target": target_id}
    response = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/relationships/{rel_id}",
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )

    return _utility.get_object(response, REL_MODEL, api_version)


def update_relationship(
    cmd,
    app_id: str,
    device_id: str,
    rel_id: str,
    target_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> RelationshipV1_1_preview:

    """
    Update a relationship in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        rel_id: unique case-sensitive relationship id
        target_id: (optional) unique case-sensitive device id
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device: dict
    """

    payload = {"target": target_id}

    response = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PATCH",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/relationships/{rel_id}",
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )

    return _utility.get_object(response, REL_MODEL, api_version)


def delete_relationship(
    cmd,
    app_id: str,
    device_id: str,
    rel_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete a relationship from IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        rel_id: unique case-sensitive relationship id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        {"result": "success"} on success
        Raises error on failure
    """

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/relationships/{rel_id}",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_device_credentials(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}/credentials".format(app_id, central_dns_suffix, BASE_PATH, device_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def run_command(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    command_name: str,
    payload: dict,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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


def run_module_command(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    module_name: str,
    component_name: str,
    command_name: str,
    payload: dict,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Run a command on a module.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        module_name: name of the device module
        component_name: name of the device component
        command_name: name of command to execute
        payload: params for command
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        result (currently a 201)
    """

    url = "https://{}.{}/{}/{}/modules/{}/components/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, module_name, component_name, command_name
    )

    if component_name is None:
        url = "https://{}.{}/{}/{}/modules/{}/commands/{}".format(
            app_id, central_dns_suffix, BASE_PATH, device_id, module_name, command_name
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
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}/commands/{}".format(app_id, central_dns_suffix, BASE_PATH, device_id, command_name),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_component_command_history(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_module_command_history(
    cmd,
    app_id: str,
    token: str,
    device_id: str,
    module_name: str,
    component_name: str,
    command_name: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get module command history

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        module_name: name of the device module
        component_name: name of the device component
        command_name: name of command to view execution history
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        Module command history (List)
    """
    url = "https://{}.{}/{}/{}/modules/{}/components/{}/commands/{}".format(
        app_id, central_dns_suffix, BASE_PATH, device_id, module_name, component_name, command_name
    )
    if component_name is None:
        url = f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/modules/{module_name}/commands/{command_name}"

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_device_twin(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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

    if not token:
        aad_token = get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
            "accessToken"
        ]
        token = "Bearer {}".format(aad_token)

    url = f"https://{app_id}.{central_dns_suffix}/system/iothub/devices/{device_id}/get-twin?extendedInfo=true"
    headers = _utility.get_headers(token, cmd)

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
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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


def purge_c2d_messages(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
        app_id, central_dns_suffix, "system/iothub/devices", device_id
    )
    headers = _utility.get_headers(token, cmd)
    response = requests.delete(url, headers=headers)
    return _utility.try_extract_result(response)


def list_device_modules(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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
    response_data = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/modules",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    ).get("modules")

    if not response_data:
        raise BadRequestError(f"Device '{device_id}' is not an IoT Edge device.")
    return [EdgeModule(dict_clean(module)) for module in response_data]


def restart_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
    token: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
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

    if not token:
        aad_token = get_aad_token(cmd, resource="https://apps.azureiotcentral.com")[
            "accessToken"
        ]
        token = "Bearer {}".format(aad_token)

    url = f"https://{app_id}.{central_dns_suffix}/system/iotedge/devices/{device_id}/modules/$edgeAgent/directmethods"
    json = {
        "methodName": "RestartModule",
        "payload": {"schemaVersion": "1.0", "id": module_id},
    }
    headers = _utility.get_headers(token, cmd)

    # Construct parameters

    response = requests.post(
        url,
        json=json,
        headers=headers,
        verify=not should_disable_connection_verify(),
    )

    return response.json()


def get_device_attestation(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Gets the attestation for a device.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_attestation: dict
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/attestation",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def delete_device_attestation(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Remove an individual device attestation.

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
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/attestation",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def update_device_attestation(
    cmd,
    app_id: str,
    device_id: str,
    payload: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Update an individual device attestation via patch

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        payload: attestation key definition in JSON
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        {"result": "success"} on success
        Raises error on failure
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PATCH",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/attestation",
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def create_device_attestation(
    cmd,
    app_id: str,
    device_id: str,
    payload: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Create an individual device attestation

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        payload: attestation key definition in JSON
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        {"result": "success"} on success
        Raises error on failure
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/attestation",
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def list_device_components(
    cmd,
    app_id: str,
    device_id: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    List the components present in a device.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        device_components: dict
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/components",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def list_device_module_components(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    List the components present in a module.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        module_name: name of the device module,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        module_components: dict
    """
    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}/modules/{module_name}/components",
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def get_device_properties_or_telemetry_value(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    component_name: str,
    telemetry_name: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get device properties or telemetry value for device / component / module / module component

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id,
        moduleName: name of the device module,
        component_name: name of the device component,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        properties/telemetry value: dict
    """
    url = f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}"

    if module_name is not None:
        url += f"/modules/{module_name}"

    if component_name is not None:
        url += f"/components/{component_name}"

    if telemetry_name is not None:
        url += f"/telemetry/{telemetry_name}"
    else:
        url += "/properties"

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url=url,
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def replace_properties(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    component_name: str,
    payload: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Replace properties for device / component / module / module component

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        module_name: name of the device module
        component_name: name of the device component
        payload: properties in JSON
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        properties: dict
    """
    url = f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}"

    if module_name is not None:
        url += f"/modules/{module_name}"

    if component_name is not None:
        url += f"/components/{component_name}"

    url += "/properties"

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PUT",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def update_properties(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    component_name: str,
    payload: str,
    token: str,
    api_version=ApiVersion.ga_2022_05_31.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Update properties for device / component / module / module component

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        device_id: unique case-sensitive device id
        moduleName: name of the device module
        component_name: name of the device component
        payload: properties in JSON
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        properties: dict
    """
    url = f"https://{app_id}.{central_dns_suffix}/api/devices/{device_id}"

    if module_name is not None:
        url += f"/modules/{module_name}"

    if component_name is not None:
        url += f"/components/{component_name}"

    url += "/properties"

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="PATCH",
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
