# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError

from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.constants import PREVIEW
from azext_iot.constants import V1
from azext_iot.central.providers.preview import CentralDeviceProviderPreview
from azext_iot.central.providers.v1 import CentralDeviceProviderV1
from azext_iot.central.utils import process_version
from azext_iot.central.utils import throw_unsupported_version
from azure.core.exceptions import ResourceNotFoundError

def list_devices(cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id, token=token)
    return provider.list_devices()

def get_device(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)
    
    return provider.get_device(device_id, central_dns_suffix)

def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    instance_of=None,
    simulated=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    if simulated and not instance_of:
        raise CLIError(
            "Error: if you supply --simulated you must also specify --instance-of"
        )

    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    # See if device exists
    try:
        provider.get_device(device_id, central_dns_suffix=central_dns_suffix)
    except ResourceNotFoundError:
        return provider.create_device(
            device_id=device_id,
            device_name=device_name,
            instance_of=instance_of,
            simulated=simulated,
            central_dns_suffix=central_dns_suffix,
        )
    raise CLIError("Device already exists with id: '{}'.".format(device_id))


def delete_device(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    try:
        provider.get_device(device_id, central_dns_suffix=central_dns_suffix)
    except ResourceNotFoundError:
        raise CLIError("Device does not exist with id: '{}'.".format(device_id)) 
    
    return provider.delete_device(device_id, central_dns_suffix)


def registration_info(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.get_device_registration_info(
        device_id=device_id, central_dns_suffix=central_dns_suffix,
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
    version=None
):
    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.run_component_command(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix
    )


def get_command_history(
    cmd,
    app_id: str,
    device_id: str,
    interface_id: str,
    command_name: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)
    return provider.get_component_command_history(
        device_id=device_id, interface_id=interface_id, command_name=command_name, central_dns_suffix=central_dns_suffix
    )


def registration_summary(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)
    return provider.get_device_registration_summary(
        central_dns_suffix=central_dns_suffix,
    )


def get_credentials(
    cmd, app_id: str, device_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT,version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = CentralDeviceProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == V1):
        provider = CentralDeviceProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.get_device_credentials(
        device_id=device_id, central_dns_suffix=central_dns_suffix,
    )


def compute_device_key(cmd, primary_key, device_id):
    return utility.compute_device_key(
        primary_key=primary_key, registration_id=device_id
    )
