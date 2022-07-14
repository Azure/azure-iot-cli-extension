# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import Optional, List
from knack.log import get_logger

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    ForbiddenError,
)
from azext_iot.common import utility
from azext_iot.sdk.central.ga_2022_05_31.models import Device, DeviceCommand
from azext_iot.central.common import EDGE_ONLY_FILTER
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)

logger = get_logger(__name__)


def list_devices(
    cmd,
    app_id: str,
    edge_only: Optional[bool] = False,
) -> List[Device]:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    devices = provider.list(
        filter=EDGE_ONLY_FILTER if edge_only else None,
    )

    if edge_only:
        template_provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)

        templates = {}
        filtered = []
        for device in devices:
            template_id = get_template_id(device)
            if template_id is None:
                continue
            if template_id not in templates:
                templates[template_id] = template_provider.get(template_id)

            template = templates[template_id]
            if "EdgeModel" in template.raw_template["@type"]:
                filtered.append(device)
        return filtered

    return devices


def get_device(
    cmd,
    app_id: str,
    device_id: str,
) -> Device:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get(device_id)


def get_device_twin(
    cmd,
    app_id: str,
    device_id: str,
) -> DeviceTwin:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_twin(device_id).device_twin


def create_device(
    cmd,
    app_id: str,
    device_id: str,
    device_name=None,
    template=None,
    simulated=False,
    organizations=None,
) -> Device:
    if simulated and not template:
        raise RequiredArgumentMissingError(
            "Error: if you supply --simulated you must also specify --template"
        )

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.create(
        device_id=device_id,
        display_name=device_name,
        template=template,
        simulated=simulated,
        organizations=organizations,
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
) -> Device:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.update(
        device_id=device_id,
        display_name=device_name,
        template=template,
        simulated=simulated,
        enabled=enabled,
        organizations=organizations,
    )


def delete_device(
    cmd,
    app_id: str,
    device_id: str,
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.delete(device_id)


def registration_info(
    cmd,
    app_id: str,
    device_id,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_registration_info(
        device_id=device_id,
        device_status=None,
    )


def run_command(
    cmd,
    app_id: str,
    device_id: str,
    command_name: str,
    content: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    interface_id: Optional[str] = None,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.run_command(
        device_id=device_id,
        interface_id=interface_id,
        component_name=component_name,
        module_name=module_name,
        command_name=command_name,
        payload=payload,
    )


def run_manual_failover(
    cmd,
    app_id: str,
    device_id: str,
    ttl_minutes: Optional[int] = None,
) -> dict:
    if ttl_minutes and ttl_minutes < 1:
        raise InvalidArgumentValueError(
            "TTL value should be a positive integer: {}".format(ttl_minutes)
        )

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.run_manual_failover(
        device_id=device_id,
        ttl_minutes=ttl_minutes,
    )


def run_manual_failback(
    cmd,
    app_id: str,
    device_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.run_manual_failback(device_id=device_id)


def purge_c2d_messages(
    cmd,
    app_id: str,
    device_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.purge_c2d_messages(device_id=device_id)


def get_command_history(
    cmd,
    app_id: str,
    device_id: str,
    command_name: str,
    interface_id: Optional[str] = None,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
) -> List[DeviceCommand]:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_command_history(
        device_id=device_id,
        interface_id=interface_id,
        component_name=component_name,
        module_name=module_name,
        command_name=command_name,
    )


def list_children(
    cmd,
    app_id: str,
    device_id: str,
) -> List[Device]:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)

    # We're using Preview version device template here
    rel_name = get_downstream_rel_name(
        cmd,
        app_id=app_id,
        device_id=device_id,
    )
    rels = provider.list_relationships(
        device_id=device_id,
        rel_name=rel_name,
    )
    # Only get children info
    for idx, rel in enumerate(rels):
        if idx == 0:
            filter = f"id eq '{rel.target}'"
        else:
            filter += f" or id eq '{rel.target}'"
    return provider.list(filter=filter)


def add_children(
    cmd,
    app_id: str,
    device_id: str,
    children_ids: List[str],
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)

    # We're using Preview version device template here
    rel_name = get_downstream_rel_name(
        cmd,
        app_id=app_id,
        device_id=device_id,
    )
    if not rel_name:
        raise ResourceNotFoundError(
            f'Relationship name cannot be found in the template for device with id "{device_id}"'
        )

    from uuid import uuid4
    return [
        provider.create_relationship(
            device_id=device_id,
            target_id=child_id,
            rel_id=str(uuid4()),
        )
        for child_id in children_ids
    ]


def remove_children(
    cmd,
    app_id: str,
    device_id: str,
    children_ids: List[str],
):
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)

    # We're using Preview version device template here
    rel_name = get_downstream_rel_name(
        cmd,
        app_id=app_id,
        device_id=device_id,
    )

    if not rel_name:
        raise ResourceNotFoundError(
            f'Relationship name cannot be found in the template for device with id "{device_id}"'
        )

    rels = provider.list_relationships(device_id=device_id, rel_name=rel_name)
    deleted = []
    for rel in rels:
        if rel.target in children_ids:
            deleted.append(
                provider.delete_relationship(
                    device_id=device_id,
                    rel_id=rel.id,
                )
            )

    if not deleted:
        raise ForbiddenError(f"Childs {children_ids} cannot be removed.")

    return deleted


def get_edge_device(
    cmd,
    app_id: str,
    device_id: str,
) -> Device:
    def raise_error():
        raise InvalidArgumentValueError(
            "The specified device Id does not identify as an IoT Edge device."
        )

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    # Check if device is edge device
    try:
        twin = provider.get_device_twin(device_id)
        capabilities = twin.device_twin.get("capabilities")
        if not capabilities:
            raise_error()

        iot_edge = capabilities.get("iotEdge")
        if not iot_edge:
            raise_error()

        return provider.get(device_id=device_id)
    except Exception:
        raise_error()


def list_device_modules(
    cmd,
    app_id: str,
    device_id: str,
) -> List[EdgeModule]:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.list_device_modules(device_id)


def get_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
) -> EdgeModule:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    modules = provider.list_device_modules(device_id)
    for module in modules:
        if module.module_id == module_id:
            return module

    raise ResourceNotFoundError(
        f"A module named '{module_id}' does not exist on device {device_id} or is not currently available"
    )


def get_edge_manifest(
    cmd,
    app_id: str,
    device_id: str,
):
    device = get_edge_device(
        cmd,
        app_id=app_id,
        device_id=device_id,
    )
    template_provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    template = template_provider.sdk_preview.get(device.template)
    return template.deployment_manifest


def restart_device_module(
    cmd,
    app_id: str,
    device_id: str,
    module_id: str,
) -> List[EdgeModule]:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.restart_device_module(device_id, module_id)


def registration_summary(
    cmd,
    app_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_registration_summary()


def get_credentials(
    cmd,
    app_id: str,
    device_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_credentials(device_id=device_id)


def get_attestation(
    cmd,
    app_id: str,
    device_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_attestation(device_id=device_id)


def delete_attestation(
    cmd,
    app_id: str,
    device_id: str,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.delete_device_attestation(device_id=device_id)


def update_attestation(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.update_device_attestation(device_id, payload=payload)


def create_attestation(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.create_device_attestation(device_id, payload=payload)


def list_modules(
    cmd,
    app_id: str,
    device_id,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.list_modules(device_id=device_id)


def list_components(
    cmd,
    app_id: str,
    device_id: str,
    module_name: Optional[str] = None,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.list_device_components(
        device_id=device_id,
        module_name=module_name,
    )


def get_properties(
    cmd,
    app_id: str,
    device_id: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_device_properties(
        device_id=device_id,
        component_name=component_name,
        module_name=module_name,
    )


def update_properties(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.update_device_properties(
        device_id=device_id,
        payload=payload,
        component_name=component_name,
        module_name=module_name,
    )


def replace_properties(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.replace_device_properties(
        device_id=device_id,
        payload=payload,
        component_name=component_name,
        module_name=module_name,
    )


def get_telemetry_value(
    cmd,
    app_id: str,
    device_id: str,
    telemetry_name: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,,
) -> dict:
    provider = CentralDeviceProvider(cmd=cmd, app_id=app_id)
    return provider.get_telemetry_value(
        device_id=device_id,
        component_name=component_name,
        module_name=module_name,
        telemetry_name=telemetry_name,
    )


def compute_device_key(cmd, primary_key, device_id):
    return utility.compute_device_key(
        primary_key=primary_key, registration_id=device_id
    )


def get_template_id(device: Device):
    return getattr(device, "template")


def get_downstream_rel_name(
    cmd,
    app_id: str,
    device_id: str,
):
    device = get_device(
        cmd,
        app_id=app_id,
        device_id=device_id,
    )

    if not device:
        raise ResourceNotFoundError(f'Device with id "{device_id}" cannot be found.')

    template_provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    # Get Preview version device template
    template = template_provider.sdk_preview.get(get_template_id(device))

    if not template:
        raise ResourceNotFoundError(
            f'Template for device with id "{device_id}" cannot be found.'
        )

    # Get Gateway relationship name
    for _, interface in template.interfaces.items():
        for _, content in interface.items():
            if all(
                (
                    cond is True
                    for cond in [
                        a in content["@type"]
                        for a in ["Relationship", "GatewayDevice"]
                    ]
                )
            ):
                rel_name = content.get("name")

    return rel_name
