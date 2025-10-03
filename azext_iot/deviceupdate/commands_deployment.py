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


# @digimaun - combine op?
def list_devices_for_deployment(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    device_class_id: str,
    deployment_id: str,
    filter: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    return data_manager.data_client.device_management.list_device_states_for_device_class_subgroup_deployment(
        group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id, filter=filter
    )


def create_deployment(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    deployment_id: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    start_date_time: Optional[str] = None,
    rollback_update_name: Optional[str] = None,
    rollback_update_provider: Optional[str] = None,
    rollback_update_version: Optional[str] = None,
    devices_failed_percentage: Optional[str] = None,
    devices_failed_count: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    if any(
        [
            devices_failed_percentage,
            devices_failed_count,
            rollback_update_name,
            rollback_update_provider,
            rollback_update_version,
        ]
    ) and not all(
        [
            devices_failed_percentage,
            devices_failed_count,
            rollback_update_name,
            rollback_update_provider,
            rollback_update_version,
        ]
    ):
        raise ArgumentUsageError(
            "To create deployment with a cloud initiated rollback policy all rollback policy arg group values must be provided."
        )
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    update_info = DeviceUpdateDataModels.UpdateInfo(
        update_id=DeviceUpdateDataModels.UpdateId(provider=update_provider, name=update_name, version=update_version)
    )
    rollback_policy = (
        None
        if not devices_failed_percentage
        else DeviceUpdateDataModels.CloudInitiatedRollbackPolicy(
            update=DeviceUpdateDataModels.UpdateInfo(
                update_id=DeviceUpdateDataModels.UpdateId(
                    provider=rollback_update_provider, name=rollback_update_name, version=rollback_update_version
                )
            ),
            failure=DeviceUpdateDataModels.CloudInitiatedRollbackPolicyFailure(
                devices_failed_percentage=devices_failed_percentage, devices_failed_count=devices_failed_count
            ),
        )
    )

    if not start_date_time:
        from datetime import datetime, timezone

        start_date_time = datetime.now(tz=timezone.utc)
    deployment = DeviceUpdateDataModels.Deployment(
        deployment_id=deployment_id,
        start_date_time=start_date_time,
        group_id=device_group_id,
        update=update_info,
        rollback_policy=rollback_policy,
    )
    try:
        return data_manager.data_client.device_management.create_or_update_deployment(
            group_id=device_group_id, deployment_id=deployment_id, deployment=deployment
        )
    except AzureError as e:
        handle_service_exception(e)


def list_deployments(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    device_class_id: Optional[str] = None,
    order_by: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        if device_class_id:
            return data_manager.data_client.device_management.list_deployments_for_device_class_subgroup(
                group_id=device_group_id, device_class_id=device_class_id, order_by=order_by
            )
        return data_manager.data_client.device_management.list_deployments_for_group(
            group_id=device_group_id, order_by=order_by
        )
    except AzureError as e:
        handle_service_exception(e)


def show_deployment(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    deployment_id: str,
    device_class_id: Optional[str] = None,
    status: Optional[bool] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        if status:
            if device_class_id:
                return data_manager.data_client.device_management.get_device_class_subgroup_deployment_status(
                    group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id
                )
            return data_manager.data_client.device_management.get_deployment_status(
                group_id=device_group_id, deployment_id=deployment_id
            )
        if device_class_id:
            return data_manager.data_client.device_management.get_deployment_for_device_class_subgroup(
                group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id
            )
        return data_manager.data_client.device_management.get_deployment(
            group_id=device_group_id, deployment_id=deployment_id
        )
    except AzureError as e:
        handle_service_exception(e)


def delete_deployment(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    deployment_id: str,
    device_class_id: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        if device_class_id:
            return data_manager.data_client.device_management.delete_deployment_for_device_class_subgroup(
                group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id
            )

        return data_manager.data_client.device_management.delete_deployment(
            group_id=device_group_id, deployment_id=deployment_id
        )
    except AzureError as e:
        handle_service_exception(e)


def cancel_deployment_for_class(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    device_class_id: str,
    deployment_id: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.stop_deployment(
            group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id
        )
    except AzureError as e:
        handle_service_exception(e)


def retry_deployment_for_class(
    cmd,
    name: str,
    instance_name: str,
    device_group_id: str,
    device_class_id: str,
    deployment_id: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.retry_deployment(
            group_id=device_group_id, device_class_id=device_class_id, deployment_id=deployment_id
        )
    except AzureError as e:
        handle_service_exception(e)
