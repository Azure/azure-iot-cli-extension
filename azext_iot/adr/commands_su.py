# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, List, Optional

from azext_iot.adr.providers.device_class import DeviceClassProvider
from azext_iot.adr.providers.software_update import SoftwareUpdateProvider
from azext_iot.adr.providers.update_instance import UpdateInstanceProvider
from azext_iot.deviceupdate.commands_update import (
    calculate_hash as calculate_update_hash,
    manifest_init_v5,
)
from azext_iot.deviceupdate.common import ADUValidHashAlgorithmType


def adr_su_instance_check_name(cmd, update_instance_name: str):
    return UpdateInstanceProvider(cmd).check_name(update_instance_name)


def adr_su_instance_list(cmd, resource_group_name: Optional[str] = None):
    return UpdateInstanceProvider(cmd).list(resource_group_name=resource_group_name)


def adr_su_instance_show(cmd, update_instance_name: str, resource_group_name: str):
    return UpdateInstanceProvider(cmd).show(
        update_instance_name=update_instance_name,
        resource_group_name=resource_group_name,
    )


def adr_su_instance_create(
    cmd,
    update_instance_name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    mi_system_assigned: Optional[bool] = None,
    mi_user_assigned: Optional[List[str]] = None,
    no_wait: bool = False,
):
    return UpdateInstanceProvider(cmd).create(
        update_instance_name=update_instance_name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_su_instance_update(
    cmd,
    update_instance_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    mi_system_assigned: Optional[bool] = None,
    mi_user_assigned: Optional[List[str]] = None,
    no_wait: bool = False,
):
    return UpdateInstanceProvider(cmd).update(
        update_instance_name=update_instance_name,
        resource_group_name=resource_group_name,
        tags=tags,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_su_instance_delete(
    cmd,
    update_instance_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return UpdateInstanceProvider(cmd).delete(
        update_instance_name=update_instance_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_su_software_update_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    search: Optional[str] = None,
    filter: Optional[str] = None,
):
    return SoftwareUpdateProvider(cmd).list_updates(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        search=search,
        filter=filter,
    )


def adr_su_software_update_show(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    update_version: str,
):
    return SoftwareUpdateProvider(cmd).show_update(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        update_version=update_version,
    )


def adr_su_software_update_delete(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    update_version: str,
    no_wait: bool = False,
):
    return SoftwareUpdateProvider(cmd).delete_update(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        update_version=update_version,
        no_wait=no_wait,
    )


def adr_su_software_update_import(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    url: str,
    size: Optional[int] = None,
    hashes: Optional[List[str]] = None,
    friendly_name: Optional[str] = None,
    files: Optional[List[List[str]]] = None,
    enable_scan: Optional[bool] = None,
    no_wait: bool = False,
):
    return SoftwareUpdateProvider(cmd).import_update(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        url=url,
        size=size,
        hashes=hashes,
        friendly_name=friendly_name,
        files=files,
        enable_scan=enable_scan,
        no_wait=no_wait,
    )


def adr_su_software_update_stage(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    manifest_paths: List[str],
    storage_account: str,
    storage_container_name: str,
    storage_account_subscription: Optional[str] = None,
    storage_prefix: Optional[str] = None,
    friendly_name: Optional[str] = None,
    enable_scan: Optional[bool] = None,
    overwrite: bool = False,
    then_import: bool = False,
    sas_expiry_hours: int = 4,
    no_wait: bool = False,
):
    return SoftwareUpdateProvider(cmd).stage_update(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        manifest_paths=manifest_paths,
        storage_account=storage_account,
        storage_container_name=storage_container_name,
        storage_account_subscription=storage_account_subscription,
        storage_prefix=storage_prefix,
        friendly_name=friendly_name,
        enable_scan=enable_scan,
        overwrite=overwrite,
        then_import=then_import,
        sas_expiry_hours=sas_expiry_hours,
        no_wait=no_wait,
    )


def adr_su_software_update_file_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    update_version: str,
):
    return SoftwareUpdateProvider(cmd).list_update_files(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        update_version=update_version,
    )


def adr_su_software_update_file_show(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    update_version: str,
    update_file_id: str,
):
    return SoftwareUpdateProvider(cmd).show_update_file(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        update_version=update_version,
        update_file_id=update_file_id,
    )


def adr_su_software_update_operation_status_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
):
    return SoftwareUpdateProvider(cmd).list_operation_statuses(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_su_software_update_operation_status_show(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    operation_id: str,
):
    return SoftwareUpdateProvider(cmd).show_operation_status(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        operation_id=operation_id,
    )


def adr_su_software_update_provider_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
):
    return SoftwareUpdateProvider(cmd).list_providers(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_su_software_update_name_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
):
    return SoftwareUpdateProvider(cmd).list_names(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
    )


def adr_su_software_update_version_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    update_provider: str,
    update_name: str,
    filter: Optional[str] = None,
):
    return SoftwareUpdateProvider(cmd).list_versions(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        filter=filter,
    )


def adr_su_software_update_calculate_hash(
    file_paths: List[str],
    hash_algo: str = ADUValidHashAlgorithmType.SHA256.value,
):
    return calculate_update_hash(file_paths=file_paths, hash_algo=hash_algo)


def adr_su_software_update_manifest_init_v5(
    cmd,
    update_name: str,
    update_provider: str,
    update_version: str,
    compatibility: List[List[str]],
    steps: List[List[str]],
    files: Optional[List[List[str]]] = None,
    related_files: Optional[List[List[str]]] = None,
    description: Optional[str] = None,
    deployable: Optional[bool] = None,
    no_validation: Optional[bool] = None,
):
    return manifest_init_v5(
        cmd=cmd,
        update_name=update_name,
        update_provider=update_provider,
        update_version=update_version,
        compatibility=compatibility,
        steps=steps,
        files=files,
        related_files=related_files,
        description=description,
        deployable=deployable,
        no_validation=no_validation,
    )


def adr_su_device_class_list(
    cmd, namespace_name: str, resource_group_name: str
):
    return DeviceClassProvider(cmd).list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_su_device_class_show(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    device_class_id: str,
):
    return DeviceClassProvider(cmd).show(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        device_class_id=device_class_id,
    )


def adr_su_device_class_delete(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    device_class_id: str,
):
    return DeviceClassProvider(cmd).delete(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        device_class_id=device_class_id,
    )
