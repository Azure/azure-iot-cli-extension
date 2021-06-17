# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError

from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.preview import CentralDeviceProviderPreview
from azext_iot.central.providers.v1 import CentralDeviceProviderV1
from azext_iot.central.models.enum import ApiVersion


def list_devices(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.list_devices(central_dns_suffix=central_dns_suffix)


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.get_device(device_id, central_dns_suffix=central_dns_suffix)


def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    template=None,
    simulated=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if simulated and not template:
        raise CLIError(
            "Error: if you supply --simulated you must also specify --template"
        )

    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.create_device(
        device_id=device_id,
        device_name=device_name,
        template=template,
        simulated=simulated,
        central_dns_suffix=central_dns_suffix,
    )


def delete_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.delete_device(device_id, central_dns_suffix=central_dns_suffix)


def registration_info(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.get_device_registration_info(
        device_id=device_id, central_dns_suffix=central_dns_suffix, device_status=None,
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
):
    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

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
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    if ttl_minutes and ttl_minutes < 1:
        raise CLIError("TTL value should be a positive integer: {}".format(ttl_minutes))

    provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    return provider.run_manual_failover(
        device_id=device_id,
        ttl_minutes=ttl_minutes,
        central_dns_suffix=central_dns_suffix,
    )


def run_manual_failback(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    return provider.run_manual_failback(
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
):
    if api_version == ApiVersion.preview.value:
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    else:
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)

    return provider.get_command_history(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        central_dns_suffix=central_dns_suffix,
    )


def registration_summary(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token,)
    return provider.get_device_registration_summary(
        central_dns_suffix=central_dns_suffix,
    )


def get_credentials(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token,)
    return provider.get_device_credentials(
        device_id=device_id, central_dns_suffix=central_dns_suffix,
    )


def compute_device_key(cmd, primary_key, device_id):
    return utility.compute_device_key(
        primary_key=primary_key, registration_id=device_id
    )
