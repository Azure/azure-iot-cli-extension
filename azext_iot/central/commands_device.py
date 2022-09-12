# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.central.common import API_VERSION, EDGE_ONLY_FILTER
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)

from typing import Optional, List, Any
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    ForbiddenError,
)
from azext_iot.central.models.ga_2022_07_31 import DeviceGa
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from knack.log import get_logger

logger = get_logger(__name__)


def list_devices(
    cmd,
    app_id: str,
    edge_only=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> List[DeviceGa]:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    devices = provider.list_devices(
        filter=EDGE_ONLY_FILTER if edge_only else None,
        central_dns_suffix=central_dns_suffix,
    )

    if edge_only:
        template_provider = CentralDeviceTemplateProvider(
            cmd=cmd, app_id=app_id, token=token, api_version=api_version
        )
        templates = {}
        filtered = []
        for device in devices:
            template_id = get_template_id(device)
            if template_id is None:
                continue
            if template_id not in templates:
                templates[template_id] = template_provider.get_device_template(
                    template_id, central_dns_suffix=central_dns_suffix
                )
            template = templates[template_id]
            if "EdgeModel" in template.raw_template[template.get_type_key()]:
                filtered.append(device)
        return filtered

    return devices


def get_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> DeviceGa:
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
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
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
    api_version=API_VERSION,
) -> DeviceGa:
    if simulated and not template:
        raise RequiredArgumentMissingError(
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
    api_version=API_VERSION,
) -> DeviceGa:

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
    api_version=API_VERSION,
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
    api_version=API_VERSION,
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
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    interface_id: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.run_command(
        device_id=device_id,
        interface_id=interface_id,
        component_name=component_name,
        module_name=module_name,
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
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    if ttl_minutes and ttl_minutes < 1:
        raise InvalidArgumentValueError(
            "TTL value should be a positive integer: {}".format(ttl_minutes)
        )

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
    api_version=API_VERSION,
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
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
    )
    return provider.purge_c2d_messages(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )


def get_command_history(
    cmd,
    app_id: str,
    device_id: str,
    command_name: str,
    interface_id: Optional[str] = None,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_command_history(
        device_id=device_id,
        interface_id=interface_id,
        component_name=component_name,
        module_name=module_name,
        command_name=command_name,
        central_dns_suffix=central_dns_suffix,
    )


def list_children(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> List[DeviceGa]:
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


def add_children(
    cmd,
    app_id: str,
    device_id: str,
    children_ids: List[str],
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
):
    from uuid import uuid4

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return [
        provider.add_relationship(
            device_id=device_id,
            target_id=child_id,
            rel_id=str(uuid4()),
            central_dns_suffix=central_dns_suffix,
        )
        for child_id in children_ids
    ]


def remove_children(
    cmd,
    app_id: str,
    device_id: str,
    children_ids: List[str],
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
):

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    rels = provider.list_relationships(
        device_id=device_id, central_dns_suffix=central_dns_suffix
    )
    deleted = []
    for rel in rels:
        if rel.target in children_ids:
            deleted.append(
                provider.delete_relationship(
                    device_id=device_id,
                    rel_id=rel.id,
                    central_dns_suffix=central_dns_suffix,
                )
            )

    if not deleted:
        raise ForbiddenError(f"Childs {children_ids} cannot be removed.")

    return deleted


def get_edge_device(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> Any:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    def raise_error():
        raise InvalidArgumentValueError(
            "The specified device Id does not identify as an IoT Edge device."
        )

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
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
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
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
    )

    modules = provider.list_device_modules(
        device_id, central_dns_suffix=central_dns_suffix
    )

    for module in modules:
        if module.module_id == module_id:
            return module

    raise ResourceNotFoundError(
        f"A module named '{module_id}' does not exist on device {device_id} or is not currently available"
    )


def get_edge_manifest(
    cmd, app_id: str, device_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT
):
    template_provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
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
        cmd=cmd, app_id=app_id, token=token, api_version=API_VERSION
    )

    return provider.restart_device_module(
        device_id, module_id, central_dns_suffix=central_dns_suffix
    )


def registration_summary(
    cmd,
    app_id: str,
    token=None,
    api_version=API_VERSION,
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
    api_version=API_VERSION,
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


def get_template_id(device: DeviceGa):
    return getattr(device, "template")


def get_attestation(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    return provider.get_device_attestation(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def delete_attestation(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_device_attestation(device_id, central_dns_suffix=central_dns_suffix)


def update_attestation(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_device_attestation(device_id, payload=payload, central_dns_suffix=central_dns_suffix)


def create_attestation(
    cmd,
    app_id: str,
    device_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.create_device_attestation(device_id, payload=payload, central_dns_suffix=central_dns_suffix)


def list_modules(
    cmd,
    app_id: str,
    device_id,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_modules(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_components(
    cmd,
    app_id: str,
    device_id,
    module_name=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_device_components(
        device_id=device_id,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_properties(
    cmd,
    app_id: str,
    device_id: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_properties(
        device_id=device_id,
        component_name=component_name,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def update_properties(
    cmd,
    app_id: str,
    device_id,
    content: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_device_properties(
        device_id=device_id,
        payload=payload,
        component_name=component_name,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def replace_properties(
    cmd,
    app_id: str,
    device_id,
    content: str,
    component_name: Optional[str] = None,
    module_name: Optional[str] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.replace_device_properties(
        device_id=device_id,
        payload=payload,
        component_name=component_name,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_telemetry_value(
    cmd,
    app_id: str,
    device_id,
    telemetry_name,
    component_name=None,
    module_name=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_telemetry_value(
        device_id=device_id,
        component_name=component_name,
        module_name=module_name,
        telemetry_name=telemetry_name,
        central_dns_suffix=central_dns_suffix,
    )
