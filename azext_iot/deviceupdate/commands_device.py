# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.common.utility import handle_service_exception
from azext_iot.deviceupdate.providers.base import (
    DeviceUpdateDataManager,
    AzureError,
)
from azext_iot.deviceupdate.common import ADUManageDeviceImportType
from azure.cli.core.azclierror import ArgumentUsageError
from typing import Optional

logger = get_logger(__name__)


def import_devices(
    cmd,
    name: str,
    instance_name: str,
    import_type: str = ADUManageDeviceImportType.ALL.value,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        # @digimaun - There is a mismatch between spec and implementation expectation.
        return data_manager.data_client.device_management.begin_import_devices(import_type={"importType": import_type})
    except AzureError as e:
        handle_service_exception(e)


def list_devices(
    cmd, name: str, instance_name: str, filter: Optional[str] = None, resource_group_name: Optional[str] = None
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.list_devices(filter=filter)
    except AzureError as e:
        handle_service_exception(e)


def show_device(cmd, name: str, instance_name: str, device_id: str, resource_group_name: Optional[str] = None):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.get_device(device_id=device_id)
    except AzureError as e:
        handle_service_exception(e)


def show_device_module(
    cmd, name: str, instance_name: str, device_id: str, module_id: str, resource_group_name: Optional[str] = None
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.get_device_module(device_id=device_id, module_id=module_id)
    except AzureError as e:
        handle_service_exception(e)


def list_device_groups(
    cmd, name: str, instance_name: str, order_by: Optional[str] = None, resource_group_name: Optional[str] = None
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_management.list_groups(order_by=order_by)
    except AzureError as e:
        handle_service_exception(e)


def show_device_group(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    update_compliance: Optional[bool] = None,
    best_updates: Optional[bool] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    if update_compliance and best_updates:
        raise ArgumentUsageError("--update-compliance and --best-updates cannot be used at the same time.")

    try:
        if update_compliance:
            return data_manager.data_client.device_management.get_update_compliance_for_group(group_id=device_group_id)

        if best_updates:
            return data_manager.data_client.device_management.list_best_updates_for_group(group_id=device_group_id)

        return data_manager.data_client.device_management.get_group(group_id=device_group_id)
    except AzureError as e:
        handle_service_exception(e)


def delete_device_group(
    cmd, name: str, instance_name: str, device_group_id: str, resource_group_name: Optional[str] = None
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_management.delete_group(group_id=device_group_id)
    except AzureError as e:
        handle_service_exception(e)


def show_update_compliance(cmd, name: str, instance_name: str, resource_group_name: Optional[str] = None):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_management.get_update_compliance()
    except AzureError as e:
        handle_service_exception(e)


# @digimaun, pageable but not attributed correctly.
def list_device_health(cmd, name: str, instance_name: str, filter: str, resource_group_name: Optional[str] = None):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        # "deviceId eq 'd0'"
        # "state eq 'Healthy'"
        return data_manager.data_client.device_management.list_device_health(filter=filter)
    except AzureError as e:
        handle_service_exception(e)
