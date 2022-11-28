# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.common.utility import handle_service_exception
from azext_iot.deviceupdate.providers.base import (
    DeviceUpdateMgmtModels,
    DeviceUpdateInstanceManager,
    parse_account_rg,
    AzureError,
)
from typing import Optional, List, Union

logger = get_logger(__name__)


def create_instance(
    cmd,
    name: str,
    instance_name: str,
    iothub_resource_ids: List[str],
    diagnostics: Optional[bool] = None,
    storage_resource_id: Optional[str] = None,
    tags: Optional[dict] = None,
    resource_group_name: Optional[str] = None,
    set_du_principal: Optional[bool] = None,
):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    # @digimaun - the location of an instance must be the same as the account container.
    location = target_container.account.location

    if set_du_principal:
        from azext_iot.deviceupdate.common import AUTH_RESOURCE_ID
        for scope in iothub_resource_ids:
            instance_manager.assign_msi_scope(
                principal_id=AUTH_RESOURCE_ID,
                scope=scope,
                role="IoT Hub Data Contributor",
                use_basic_assignee=True)

    instance = DeviceUpdateMgmtModels.Instance(
        location=location,
        tags=tags,
        iot_hubs=instance_manager.assemble_iothub_resources(iothub_resource_ids),
        enable_diagnostics=diagnostics,
    )
    if storage_resource_id:
        instance.diagnostic_storage_properties = instance_manager.assemble_diagnostic_storage(storage_resource_id)
    try:
        return instance_manager.mgmt_client.instances.begin_create(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
            instance_name=instance_name,
            instance=instance,
        )
    except AzureError as e:
        handle_service_exception(e)


def update_instance(cmd, parameters: DeviceUpdateMgmtModels.Instance):
    from azext_iot.deviceupdate.common import ADUInstanceDiagnosticStorageAuthType

    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    storage_properties: Union[
        DeviceUpdateMgmtModels.DiagnosticStorageProperties, dict
    ] = parameters.diagnostic_storage_properties
    if storage_properties:
        # Storage properties can be a dict or DeviceUpdateMgmtModels.DiagnosticStorageProperties
        # depending on how the CLI core generic update helpers are used i.e. --set with an existing object vs new.
        if isinstance(storage_properties, dict):
            authentication_type = storage_properties.get("authenticationType")
            resource_id = storage_properties.get("resourceId")
            connection_string = storage_properties.get("connectionString")
        else:
            authentication_type = storage_properties.authentication_type
            resource_id = storage_properties.resource_id
            connection_string = storage_properties.connection_string

        if not authentication_type:
            authentication_type = ADUInstanceDiagnosticStorageAuthType.KEYBASED.value

        if (
            authentication_type == ADUInstanceDiagnosticStorageAuthType.KEYBASED.value
            and resource_id
            and not connection_string
        ):
            parameters.diagnostic_storage_properties = instance_manager.assemble_diagnostic_storage(resource_id)

    try:
        return instance_manager.mgmt_client.instances.begin_create(
            resource_group_name=parse_account_rg(parameters.id),
            account_name=parameters.account_name,
            instance_name=parameters.name,
            instance=parameters,
        )
    except AzureError as e:
        handle_service_exception(e)


def list_instances(cmd, name: str, resource_group_name: Optional[str] = None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    try:
        return instance_manager.mgmt_client.instances.list_by_account(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
        )
    except AzureError as e:
        handle_service_exception(e)


def show_instance(cmd, name: str, instance_name: str, resource_group_name: Optional[str] = None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    try:
        return instance_manager.mgmt_client.instances.get(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
            instance_name=instance_name,
        )
    except AzureError as e:
        handle_service_exception(e)


def delete_instance(cmd, name: str, instance_name: str, resource_group_name: Optional[str] = None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    try:
        return instance_manager.mgmt_client.instances.begin_delete(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
            instance_name=instance_name,
        )
    except AzureError as e:
        handle_service_exception(e)


def wait_on_instance(cmd, name: str, instance_name: str, resource_group_name: Optional[str] = None):
    return show_instance(
        cmd=cmd,
        name=name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )
