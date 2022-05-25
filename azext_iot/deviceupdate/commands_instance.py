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
)

logger = get_logger(__name__)

# Instances


def create_instance(
    cmd,
    name,
    instance_name,
    iothub_resource_ids,
    diagnostics=None,
    storage_resource_id=None,
    location=None,
    tags=None,
    resource_group_name=None,
):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    if not location:
        location = target_container.account.location

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
    except Exception as e:
        handle_service_exception(e)


def update_instance(cmd, parameters: DeviceUpdateMgmtModels.Instance):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)

    try:
        storage_properties = parameters.diagnostic_storage_properties
        if storage_properties:
            if (
                storage_properties.authentication_type == "KeyBased"
                and storage_properties.resource_id
                and storage_properties.connection_string is None
            ):
                parameters.diagnostic_storage_properties = instance_manager.assemble_diagnostic_storage(
                    storage_properties.resource_id
                )
        return instance_manager.mgmt_client.instances.begin_create(
            resource_group_name=parse_account_rg(parameters.id),
            account_name=parameters.account_name,
            instance_name=parameters.name,
            instance=parameters,
        )
    except Exception as e:
        handle_service_exception(e)


def list_instances(cmd, name, resource_group_name=None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    return instance_manager.mgmt_client.instances.list_by_account(
        resource_group_name=target_container.resource_group,
        account_name=target_container.account.name,
    )


def show_instance(cmd, name, instance_name, resource_group_name=None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    try:
        return instance_manager.mgmt_client.instances.get(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
            instance_name=instance_name,
        )
    except Exception as e:
        handle_service_exception(e)


def delete_instance(cmd, name, instance_name, resource_group_name=None):
    instance_manager = DeviceUpdateInstanceManager(cmd=cmd)
    target_container = instance_manager.find_account(target_name=name, target_rg=resource_group_name)
    try:
        return instance_manager.mgmt_client.instances.begin_delete(
            resource_group_name=target_container.resource_group,
            account_name=target_container.account.name,
            instance_name=instance_name,
        )
    except Exception as e:
        handle_service_exception(e)


def wait_on_instance(cmd, name, instance_name, resource_group_name=None):
    return show_instance(
        cmd=cmd,
        name=name,
        instance_name=instance_name,
        resource_group_name=resource_group_name,
    )
