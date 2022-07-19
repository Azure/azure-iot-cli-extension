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
    ARMPolling,
)
from azure.cli.core.azclierror import ArgumentUsageError
from typing import Optional, List, Union

logger = get_logger(__name__)


def list_updates(
    cmd,
    name,
    instance_name,
    search: Optional[str] = None,
    filter: Optional[str] = None,
    by_provider: Optional[bool] = None,
    by_name: Optional[bool] = None,
    by_version: Optional[bool] = None,
    update_name: Optional[str] = None,
    update_provider: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    if [by_provider, by_name, by_version].count(True) > 1:
        raise ArgumentUsageError("Only a single --by-* flag can be used at a time.")

    try:
        if by_provider:
            return data_manager.data_client.device_update.list_providers()
        if by_name:
            if not update_provider:
                raise ArgumentUsageError("--update-provider is required when using --by-name.")
            return data_manager.data_client.device_update.list_names(provider=update_provider)
        if by_version:
            if not all([update_provider, update_name]):
                raise ArgumentUsageError(
                    "--update-provider and --update-name are required when using --by-version"
                )
            return data_manager.data_client.device_update.list_versions(
                provider=update_provider, name=update_name, filter=filter
            )
        return data_manager.data_client.device_update.list_updates(search=search, filter=filter)
    except AzureError as e:
        handle_service_exception(e)


def list_update_files(
    cmd,
    name,
    instance_name,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.list_files(
            provider=update_provider, name=update_name, version=update_version
        )
    except AzureError as e:
        handle_service_exception(e)


def show_update(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.get_update(
            provider=update_provider, name=update_name, version=update_version
        )
    except AzureError as e:
        handle_service_exception(e)


def show_update_file(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    update_file_id: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.get_file(
            name=update_name, provider=update_provider, version=update_version, file_id=update_file_id
        )
    except AzureError as e:
        handle_service_exception(e)


def import_update(
    cmd,
    name: str,
    instance_name: str,
    url: str,
    size: Optional[int] = None,
    hashes: Optional[List[str]] = None,
    friendly_name: Optional[str] = None,
    file: Optional[List[List[str]]] = None,
    resource_group_name: Optional[str] = None,
):
    from azext_iot.deviceupdate.providers.base import MicroObjectCache

    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    client_calculated_meta = None
    if not size or not hashes:
        client_calculated_meta = data_manager.calculate_manifest_metadata(url)

    hashes = data_manager.assemble_hashes(hash_list=hashes) or {"sha256": client_calculated_meta.hash}
    size = size or client_calculated_meta.bytes

    manifest_metadata = DeviceUpdateDataModels.ImportManifestMetadata(url=url, size_in_bytes=size, hashes=hashes)
    import_update_item = DeviceUpdateDataModels.ImportUpdateInputItem(
        import_manifest=manifest_metadata,
        friendly_name=friendly_name,
        files=data_manager.assemble_files(file_list_col=file),
    )
    cache = MicroObjectCache(cmd, DeviceUpdateDataModels)
    cache_resource_name = f"{name}_{instance_name}_importUpdate"
    cache_resource_type = "DeviceUpdate"
    cache_serialization_model = "[ImportUpdateInputItem]"
    defer = cmd.cli_ctx.data.get("_cache", False)
    cached_imports: Union[List[DeviceUpdateDataModels.ImportUpdateInputItem], None] = cache.get(
        resource_name=cache_resource_name,
        resource_group=data_manager.container.resource_group,
        resource_type=cache_resource_type,
        serialization_model=cache_serialization_model,
    )
    update_to_import = cached_imports if cached_imports else []
    update_to_import.append(import_update_item)

    if defer:
        cache.set(
            resource_name=cache_resource_name,
            resource_group=data_manager.container.resource_group,
            resource_type=cache_resource_type,
            payload=update_to_import,
            serialization_model=cache_serialization_model,
        )
        return
    else:
        import_poller = data_manager.data_client.device_update.begin_import_update(update_to_import=update_to_import)

        def import_handler(lro: ARMPolling):
            if lro.status() == "Succeeded":
                cache.remove(
                    resource_name=cache_resource_name,
                    resource_group=data_manager.container.resource_group,
                    resource_type=cache_resource_type,
                )
            elif lro.status() == "Failed":
                try:
                    logger.error(lro._pipeline_response.http_response.text())
                except Exception:
                    pass

        import_poller.add_done_callback(import_handler)
        # @digimaun - TODO: Investigate better LRO error handling.
        return import_poller


def delete_update(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    # @digimaun - TODO: Investigate better LRO error handling.
    return data_manager.data_client.device_update.begin_delete_update(
        name=update_name, provider=update_provider, version=update_version
    )


def list_operations(
    cmd,
    name: str,
    instance_name: str,
    filter=None,
    top: Optional[int] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.list_operations(filter=filter, top=top)
    except AzureError as e:
        handle_service_exception(e)


def show_operation(cmd, name: str, instance_name: str, operation_id: str, resource_group_name: Optional[str] = None):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.get_operation(operation_id=operation_id)
    except AzureError as e:
        handle_service_exception(e)
