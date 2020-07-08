# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError

from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralDeviceProvider


def list_devices(cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.list_devices()


def get_device(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.get_device(device_id)


def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    instance_of=None,
    simulated=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    if simulated and not instance_of:
        raise CLIError(
            "Error: if you supply --simulated you must also specify --instance-of"
        )
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.create_device(
        device_id=device_id,
        device_name=device_name,
        instance_of=instance_of,
        simulated=simulated,
        central_dns_suffix=central_dns_suffix,
    )


def delete_device(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.delete_device(device_id)


def registration_info(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token,)

    return provider.get_device_registration_info(
        device_id=device_id, central_dns_suffix=central_dns_suffix, device_status=None,
    )


def run_command(
    cmd,
    app_id: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.run_component_command(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        payload=payload,
    )


def get_command_history(
    cmd,
    app_id: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.get_component_command_history(
        device_id=device_id, interface_id=interface_id, command_name=command_name,
    )


def registration_summary(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token,)
    return provider.get_device_registration_summary(
        central_dns_suffix=central_dns_suffix,
    )


def get_credentials(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token,)
    return provider.get_device_credentials(
        device_id=device_id, central_dns_suffix=central_dns_suffix,
    )
