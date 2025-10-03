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
from typing import Optional, List

logger = get_logger(__name__)


def collect_logs(
    cmd,
    name: str,
    instance_name: str,
    log_collection_id: str,
    agent_id: List[List[str]],
    description: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    log_collection = DeviceUpdateDataModels.LogCollection(
        device_list=data_manager.assemble_agent_ids(agent_id), description=description, log_collection_id=log_collection_id
    )

    try:
        return data_manager.data_client.device_management.start_log_collection(
            log_collection_id=log_collection_id, log_collection=log_collection
        )
    except AzureError as e:
        handle_service_exception(e)


def list_log_collections(cmd, name: str, instance_name: str, resource_group_name: Optional[str] = None):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        return data_manager.data_client.device_management.list_log_collections()
    except AzureError as e:
        handle_service_exception(e)


def show_log_collection(
    cmd,
    name: str,
    instance_name: str,
    log_collection_id: str,
    detailed_status: Optional[bool] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        if detailed_status:
            return data_manager.data_client.device_management.get_log_collection_detailed_status(log_collection_id)

        return data_manager.data_client.device_management.get_log_collection(log_collection_id)
    except AzureError as e:
        handle_service_exception(e)
