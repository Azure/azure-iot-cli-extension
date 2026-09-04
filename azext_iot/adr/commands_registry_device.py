# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azext_iot.adr.common import (
    DeviceAttributeReportedType,
    RegistryDeviceEnablementState,
)
from azext_iot.adr.providers.registry_device import RegistryDeviceProvider


def adr_registry_device_create(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    enablement_state: str = RegistryDeviceEnablementState.enabled.value,
    external_device_id: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    hardware_revision: Optional[str] = None,
    software_revision: Optional[str] = None,
    no_wait: bool = False,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.create(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
        enablement_state=enablement_state,
        external_device_id=external_device_id,
        manufacturer=manufacturer,
        model=model,
        hardware_revision=hardware_revision,
        software_revision=software_revision,
        no_wait=no_wait,
    )


def adr_registry_device_show(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    registry_device_name: Optional[str] = None,
    external_device_id: Optional[str] = None,
):
    provider = RegistryDeviceProvider(cmd)
    kwargs = {
        "registry_device_name": registry_device_name,
        "namespace_name": namespace_name,
        "resource_group_name": resource_group_name,
    }
    if external_device_id is not None:
        kwargs["external_device_id"] = external_device_id
    return provider.show(**kwargs)


def adr_registry_device_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_update(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    enablement_state: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    hardware_revision: Optional[str] = None,
    software_revision: Optional[str] = None,
    no_wait: bool = False,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.update(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        tags=tags,
        enablement_state=enablement_state,
        manufacturer=manufacturer,
        model=model,
        hardware_revision=hardware_revision,
        software_revision=software_revision,
        no_wait=no_wait,
    )


def adr_registry_device_delete(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.delete(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_registry_device_auth_list(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.auth_list(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_auth_show(
    cmd,
    authentication_profile_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.auth_show(
        authentication_profile_name=authentication_profile_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_auth_show_keys(
    cmd,
    authentication_profile_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.auth_show_keys(
        authentication_profile_name=authentication_profile_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_auth_revoke_certs(
    cmd,
    authentication_profile_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.auth_revoke_certs(
        authentication_profile_name=authentication_profile_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_registry_device_attribute_list(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.attribute_list(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_attribute_show(
    cmd,
    attribute_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.attribute_show(
        attribute_name=attribute_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_attribute_create(
    cmd,
    attribute_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
    reported_by: str = DeviceAttributeReportedType.user.value,
    schema: Optional[str] = None,
    properties: Optional[str] = None,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.attribute_create(
        attribute_name=attribute_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        reported_by=reported_by,
        schema=schema,
        properties=properties,
    )


def adr_registry_device_attribute_delete(
    cmd,
    attribute_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.attribute_delete(
        attribute_name=attribute_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_capability_list(
    cmd,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.capability_list(
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_registry_device_capability_show(
    cmd,
    capability_name: str,
    registry_device_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = RegistryDeviceProvider(cmd)
    return provider.capability_show(
        capability_name=capability_name,
        registry_device_name=registry_device_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )
