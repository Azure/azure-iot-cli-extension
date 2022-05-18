# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from knack.log import get_logger

from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider

logger = get_logger(__name__)


def create_device_registration(
    cmd,
    registration_id: str,
    enrollment_group_id: str = None,
    symmetric_key: str = None,
    compute_key: bool = False,
    payload: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
    wait: bool = False,
    poll_interval: int = 5,
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        registration_id=registration_id,
        enrollment_group_id=enrollment_group_id,
        symmetric_key=symmetric_key,
        compute_key=compute_key,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.create(
        payload=payload,
        wait=wait,
        poll_interval=poll_interval
    )


def show_device_registration(
    cmd,
    registration_id: str,
    enrollment_group_id: str = None,
    symmetric_key: str = None,
    compute_key: bool = False,
    payload: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        registration_id=registration_id,
        enrollment_group_id=enrollment_group_id,
        symmetric_key=symmetric_key,
        compute_key=compute_key,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.get(
        payload=payload,
    )


def show_device_registration_operation(
    cmd,
    registration_id: str,
    operation_id: str,
    enrollment_group_id: str = None,
    symmetric_key: str = None,
    compute_key: bool = False,
    payload: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        registration_id=registration_id,
        enrollment_group_id=enrollment_group_id,
        symmetric_key=symmetric_key,
        compute_key=compute_key,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.operation_get(
        operation_id=operation_id,
    )
