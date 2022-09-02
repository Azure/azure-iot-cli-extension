# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.common.utility import handle_service_exception
from azext_iot.deviceupdate.providers.base import (
    DeviceUpdateDataModels,
    DeviceUpdateDataManager,
    AzureError,
)
from azure.cli.core.azclierror import ArgumentUsageError
from typing import Optional

logger = get_logger(__name__)


def list_device_classes(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: Optional[str] = None,
    filter: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    if device_group_id:
        return data_manager.data_client.device_management.list_device_class_subgroups_for_group(
            group_id=device_group_id, filter=filter
        )
    try:
        return data_manager.data_client.device_management.list_device_classes(filter=filter)
    except AzureError as e:
        handle_service_exception(e)


def show_device_class(
    cmd,
    name: str,
    instance_name: str,
    device_class_id: str,
    device_group_id: Optional[str] = None,
    update_compliance: Optional[bool] = None,
    best_update: Optional[bool] = None,
    installable_updates: Optional[bool] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    if [update_compliance, best_update, installable_updates].count(True) > 1:
        raise ArgumentUsageError(
            "Only a single flag among --update-compliance, --best-update and --installable-updates can be used at a time."
        )

    if (update_compliance or best_update) and not device_group_id:
        raise ArgumentUsageError("--group-id is required when using --update-compliance or --best-update.")

    try:
        if installable_updates:
            return data_manager.data_client.device_management.list_installable_updates_for_device_class(
                device_class_id=device_class_id
            )
        if device_group_id:
            if update_compliance:
                return data_manager.data_client.device_management.get_device_class_subgroup_update_compliance(
                    group_id=device_group_id, device_class_id=device_class_id
                )
            if best_update:
                return data_manager.data_client.device_management.get_best_updates_for_device_class_subgroup(
                    group_id=device_group_id, device_class_id=device_class_id
                )
            return data_manager.data_client.device_management.get_device_class_subgroup(
                group_id=device_group_id, device_class_id=device_class_id
            )
        return data_manager.data_client.device_management.get_device_class(device_class_id=device_class_id)
    except AzureError as e:
        handle_service_exception(e)


def update_device_class(
    cmd,
    name: str,
    instance_name: str,
    device_class_id: str,
    friendly_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    patch_body = None
    if friendly_name:
        patch_body = DeviceUpdateDataModels.PatchBody(friendly_name=friendly_name)

    if patch_body:
        try:
            return data_manager.data_client.device_management.update_device_class(
                device_class_id=device_class_id, device_class_patch=patch_body
            )
        except AzureError as e:
            handle_service_exception(e)
    else:
        logger.warning("No patch body option values provided. Update device class has no work to be done.")


def delete_device_class(
    cmd,
    name: str,
    instance_name: str,
    device_class_id: str,
    device_group_id: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        if device_group_id:
            return data_manager.data_client.device_management.delete_device_class_subgroup(
                device_class_id=device_class_id, group_id=device_group_id
            )
        # @digimaun, this operation returns a 404 today.
        return data_manager.data_client.device_management.delete_device_class(device_class_id=device_class_id)
    except AzureError as e:
        handle_service_exception(e)
