# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError
from azext_iot.central.providers import CentralDeviceProvider


def list_devices(
    cmd, app_id: str, token=None, central_dns_suffix="azureiotcentral.com"
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.list_devices()


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix="azureiotcentral.com",
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
    central_dns_suffix="azureiotcentral.com",
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
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix="azureiotcentral.com",
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.delete_device(device_id)


def registration_info(
    cmd,
    app_id: str,
    device_id=None,
    token=None,
    central_dns_suffix="azureiotcentral.com",
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    if not device_id:
        return provider.get_all_registration_info(central_dns_suffix=central_dns_suffix)
    return provider.get_device_registration_info(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )
