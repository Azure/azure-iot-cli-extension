# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)
from knack.util import CLIError
from typing import Union, List, Any
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


def update_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    template=None,
    simulated=None,
    enabled=None,
    organizations=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> DeviceType:

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.update_device(
        device_id=device_id,
        device_name=device_name,
        template=template,
        simulated=simulated,
        enabled=enabled,
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
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1.value
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


def list_edge_devices(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> List[DeviceType]:
    edge_devices = []
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    devices = provider.list_devices(central_dns_suffix=central_dns_suffix)
    for device in devices:
        if device.provisioned:
            twin = provider.get_device_twin(
                device.id, central_dns_suffix=central_dns_suffix
            )
            if twin.device_twin["capabilities"]["iotEdge"]:
                edge_devices.append(device)

    return edge_devices


def get_children_devices(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> List[DeviceType]:
    children = []
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    # get iotedge device
    edge_twin = provider.get_device_twin(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )
    edge_scope_id = edge_twin.device_twin.get("deviceScope")

    # list all application device twins
    devices = provider.list_devices(central_dns_suffix=central_dns_suffix)
    for device in devices:
        if device.provisioned:
            twin = provider.get_device_twin(
                device.id, central_dns_suffix=central_dns_suffix
            )
            device_scope_id = twin.device_twin.get("deviceScope")
            if (
                device_scope_id
                and device_scope_id == edge_scope_id
                and device.id != device_id  # skip current device
            ):
                children.append(device)

    return children


def get_edge_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
) -> Any:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    def raise_error():
        raise CLIError("The specified device Id does not identify an IoT Edge device.")

    # check if device is edge
    try:
        twin = provider.get_device_twin(
            device_id, central_dns_suffix=central_dns_suffix
        )
        capabilities = twin.device_twin.get("capabilities")
        if not capabilities:
            raise_error()

        iot_edge = capabilities.get("iotEdge")
        if not iot_edge:
            raise_error()

        return provider.get_device(
            device_id=device_id, central_dns_suffix=central_dns_suffix
        )
    except Exception:
        raise_error()


def list_device_modules(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[EdgeModule]:

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1.value
    )

    return provider.list_device_modules(
        device_id, central_dns_suffix=central_dns_suffix
    )


def get_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> EdgeModule:

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1.value
    )

    modules = provider.list_device_modules(
        device_id, central_dns_suffix=central_dns_suffix
    )

    for module in modules:
        if module.module_id == module_id:
            return module

    raise CLIError(
        f"A module named '{module_id}' does not exist on device {device_id} or is not currently available"
    )


def get_edge_manifest(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT
):
    # force API v1.1 for this to work
    template_provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1_1_preview.value
    )

    device = get_edge_device(
        cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
    )
    template = template_provider.get_device_template(
        device.template, central_dns_suffix=central_dns_suffix
    )
    return template.deployment_manifest


def restart_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[EdgeModule]:

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1.value
    )

    return provider.restart_device_module(
        device_id, module_id, central_dns_suffix=central_dns_suffix
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


def compute_device_key(cmd, primary_key, device_id):
    return utility.compute_device_key(
        primary_key=primary_key, registration_id=device_id
    )
