# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.central.common import EDGE_ONLY_FILTER
from azext_iot.central.models.devicetwin import DeviceTwin
from azext_iot.central.models.edge import EdgeModule
from azext_iot.central.providers import (
    CentralDeviceProvider,
    CentralDeviceTemplateProvider,
)

from typing import Union, List, Any
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    ForbiddenError,
)
from azext_iot.central.models.v1 import DeviceV1
from azext_iot.central.models.preview import DevicePreview
from azext_iot.central.models.v1_1_preview import DeviceV1_1_preview
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.enum import ApiVersion
from knack.log import get_logger

logger = get_logger(__name__)

DeviceType = Union[DevicePreview, DeviceV1, DeviceV1_1_preview]


def list_devices(
    cmd,
    app_id: str,
    edge_only=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> List[DeviceType]:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    devices = provider.list_devices(
        filter=EDGE_ONLY_FILTER if edge_only else None,
        central_dns_suffix=central_dns_suffix,
    )

    if edge_only and api_version != ApiVersion.v1_1_preview.value:
        template_provider = CentralDeviceTemplateProvider(
            cmd=cmd, app_id=app_id, token=token, api_version=api_version
        )
        templates = {}
        filtered = []
        for device in devices:
            template_id = get_template_id(device, api_version=api_version)
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
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
) -> DeviceType:
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
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.run_command(
        device_id=device_id,
        interface_id=interface_id,
        command_name=command_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def run_module_command(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    command_name: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.run_module_command(
        device_id=device_id,
        module_name=module_name,
        component_name=None,
        command_name=command_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def run_module_component_command(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    component_name: str,
    command_name: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.run_module_command(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
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
    api_version=ApiVersion.ga_2022_05_31.value,
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


def get_module_command_history(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    command_name: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_command_history(
        device_id=device_id,
        module_name=module_name,
        component_name=None,
        command_name=command_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_module_component_command_history(
    cmd,
    app_id: str,
    device_id: str,
    module_name: str,
    component_name: str,
    command_name: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_command_history(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
        command_name=command_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_module_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_properties(
        device_id=device_id,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def replace_module_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.replace_module_properties(
        device_id=device_id,
        module_name=module_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def update_module_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_module_properties(
        device_id=device_id,
        module_name=module_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def get_module_telemetry_value(
    cmd,
    app_id: str,
    device_id,
    module_name,
    telemetry_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_telemetry_value(
        device_id=device_id,
        module_name=module_name,
        telemetry_name=telemetry_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_module_component_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    component_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_component_properties(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
        central_dns_suffix=central_dns_suffix,
    )


def replace_module_component_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    component_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.replace_module_component_properties(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def update_module_component_properties(
    cmd,
    app_id: str,
    device_id,
    module_name,
    component_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_module_component_properties(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def get_module_component_telemetry_value(
    cmd,
    app_id: str,
    device_id,
    module_name,
    component_name,
    telemetry_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_module_component_telemetry_value(
        device_id=device_id,
        module_name=module_name,
        component_name=component_name,
        telemetry_name=telemetry_name,
        central_dns_suffix=central_dns_suffix,
    )


def list_children(
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

    # use new apis
    if api_version == ApiVersion.v1_1_preview.value:
        rel_name = get_downstream_rel_name(
            cmd,
            app_id=app_id,
            device_id=device_id,
            token=token,
            central_dns_suffix=central_dns_suffix,
            api_version=api_version,
        )
        rels = provider.list_relationships(
            device_id=device_id,
            rel_name=rel_name,
            central_dns_suffix=central_dns_suffix,
        )
        # only show children info
        for idx, rel in enumerate(rels):
            if idx == 0:
                filter = f"id eq '{rel.target}'"
            else:
                filter += f" or id eq '{rel.target}'"
        return provider.list_devices(filter=filter)

    warning = (
        "This command may take a long time to complete when running with this api version."
        "\nConsider using Api Version 1.1-preview when listing edge devices "
        "as it supports server filtering speeding up the process."
    )
    logger.warning(warning)

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
    api_version=ApiVersion.v1.value,
):
    from uuid import uuid4

    if api_version != ApiVersion.v1_1_preview.value:
        raise InvalidArgumentValueError(
            (
                "Adding children devices to IoT Edge is still in preview "
                "and only available for Api version >= 1.1-preview. "
                'Please pass the right "api_version" to the command.'
            )
        )

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    rel_name = get_downstream_rel_name(
        cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    if not rel_name:
        raise ResourceNotFoundError(
            f'Relationship name cannot be found in the template for device with id "{device_id}"'
        )

    return [
        provider.add_relationship(
            device_id=device_id,
            target_id=child_id,
            rel_id=str(uuid4()),
            rel_name=rel_name,
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
    api_version=ApiVersion.v1.value,
):

    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )
    rel_name = get_downstream_rel_name(
        cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    if not rel_name:
        raise ResourceNotFoundError(
            f'Relationship name cannot be found in the template for device with id "{device_id}"'
        )

    rels = provider.list_relationships(
        device_id=device_id, rel_name=rel_name, central_dns_suffix=central_dns_suffix
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
    api_version=ApiVersion.v1.value,
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
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.ga_2022_05_31.value
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
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.ga_2022_05_31.value
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
    api_version=ApiVersion.ga_2022_05_31.value,
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


def get_template_id(device: DeviceType, api_version=ApiVersion.v1.value):
    return getattr(
        device,
        "instanceOf" if api_version == ApiVersion.preview.value else "template",
    )


def get_downstream_rel_name(
    cmd,
    app_id: str,
    device_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1.value,
):
    # force API v1.1 for this to work
    template_provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=ApiVersion.v1_1_preview.value
    )
    device = get_device(
        cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    if not device:
        raise ResourceNotFoundError(f'Device with id "{device_id}" cannot be found.')

    template = template_provider.get_device_template(
        get_template_id(device, api_version=api_version),
        central_dns_suffix=central_dns_suffix,
    )

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
                        a in content[template.get_type_key()]
                        for a in ["Relationship", "GatewayDevice"]
                    ]
                )
            ):
                rel_name = content.get("name")

    return rel_name


def get_attestation(
    cmd,
    app_id: str,
    device_id,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
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
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_device_modules(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_components(
    cmd,
    app_id: str,
    device_id,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_device_components(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_module_components(
    cmd,
    app_id: str,
    device_id,
    module_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_device_module_components(
        device_id=device_id,
        module_name=module_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_properties(
    cmd,
    app_id: str,
    device_id,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_properties(
        device_id=device_id,
        central_dns_suffix=central_dns_suffix,
    )


def replace_properties(
    cmd,
    app_id: str,
    device_id,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.replace_device_properties(
        device_id=device_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def update_properties(
    cmd,
    app_id: str,
    device_id,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_device_properties(
        device_id=device_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def get_telemetry_value(
    cmd,
    app_id: str,
    device_id,
    telemetry_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_telemetry_value(
        device_id=device_id,
        telemetry_name=telemetry_name,
        central_dns_suffix=central_dns_suffix,
    )


def get_component_properties(
    cmd,
    app_id: str,
    device_id,
    component_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_component_properties(
        device_id=device_id,
        component_name=component_name,
        central_dns_suffix=central_dns_suffix,
    )


def replace_component_properties(
    cmd,
    app_id: str,
    device_id,
    component_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.replace_device_component_properties(
        device_id=device_id,
        component_name=component_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def update_component_properties(
    cmd,
    app_id: str,
    device_id,
    component_name,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    payload = utility.process_json_arg(content, argument_name="content")

    return provider.update_device_component_properties(
        device_id=device_id,
        component_name=component_name,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def get_component_telemetry_value(
    cmd,
    app_id: str,
    device_id,
    component_name,
    telemetry_name,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> dict:
    provider = CentralDeviceProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_device_component_telemetry_value(
        device_id=device_id,
        component_name=component_name,
        telemetry_name=telemetry_name,
        central_dns_suffix=central_dns_suffix,
    )
