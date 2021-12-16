# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.providers import CentralDeviceProvider
from knack.util import CLIError
from typing import Union, List
from azext_iot.central.models.v1 import DeviceV1
from azext_iot.central.models.preview import DevicePreview
from azext_iot.central.models.v1_1_preview import DeviceV1_1_preview
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.enum import ApiVersion

DeviceType = Union[DevicePreview, DeviceV1, DeviceV1_1_preview]


def list_devices(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> List[DeviceType]:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.list_devices(central_dns_suffix=central_dns_suffix)


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> DeviceType:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device(device_id, central_dns_suffix=central_dns_suffix)


def get_device_twin(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> DeviceTwin:

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1.value
    )

    return provider.get_device_twin(
        device_id, central_dns_suffix=central_dns_suffix
    ).device_twin


def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    template=None,
    simulated=False,
    organizations=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> DeviceType:
    if simulated and not template:
        raise CLIError(
            "Error: if you supply --simulated you must also specify --template"
        )

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.create_device(
        device_id=device_id,
        device_name=device_name,
        template=template,
        simulated=simulated,
        organizations=organizations,
        central_dns_suffix=central_dns_suffix,
    )


def delete_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_device(device_id, central_dns_suffix=central_dns_suffix)


def registration_info(
    cmd,
    app_id: str,
    device_id,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_registration_info(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
        device_status=None,
    )


def run_command(
    cmd,
    app_id: str,
    device_id: str,
    command_name: str,
    content: str,
    interface_id=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> dict:
    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.run_command(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def run_manual_failover(
    cmd,
    app_id: str,
    device_id: str,
    ttl_minutes=None,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    if ttl_minutes and ttl_minutes < 1:
        raise CLIError("TTL value should be a positive integer: {}".format(ttl_minutes))

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.run_manual_failover(
        device_id=device_id,
        ttl_minutes=ttl_minutes,
        central_dns_suffix=central_dns_suffix,
    )


def run_manual_failback(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.run_manual_failback(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )


def purge_c2d_messages(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.purge_c2d_messages(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )


def get_command_history(
    cmd,
    app_id: str,
    device_id: str,
    command_name: str,
    token=None,
    interface_id=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_command_history(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        central_dns_suffix=central_dns_suffix,
    )


def registration_summary(
    cmd,
    app_id: str,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.get_device_registration_summary(
        central_dns_suffix=central_dns_suffix,
    )


def get_credentials(
    cmd,
    app_id: str,
    device_id,
    token=None,
    api_version=ApiVersion.v1.value,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.get_device_credentials(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def compute_device_key(
    cmd,
    primary_key,
    device_id
):
    return utility.compute_device_key(
        primary_key=primary_key, registration_id=device_id
    )
