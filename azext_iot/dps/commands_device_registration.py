# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from knack.log import get_logger
from azext_iot.common.shared import AttestationType

from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider

logger = get_logger(__name__)


def create_device_registration(
    cmd,
    registration_id: str,
    attestation_mechanism: str = AttestationType.symmetricKey.value,
    enrollment_group_id: str = None,
    device_symmetric_key: str = None,
    group_symmetric_key: str = None,
    # certificate_path: str = None,
    payload: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.create(
        registration_id=registration_id,
        attestation_mechanism=attestation_mechanism,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        group_symmetric_key=group_symmetric_key,
        # certificate_path=certificate_path,
        payload=payload
    )


def show_device_registration(
    cmd,
    registration_id: str,
    attestation_mechanism: str = AttestationType.symmetricKey.value,
    enrollment_group_id: str = None,
    device_symmetric_key: str = None,
    group_symmetric_key: str = None,
    payload: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.get(
        registration_id=registration_id,
        attestation_mechanism=attestation_mechanism,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        group_symmetric_key=group_symmetric_key,
        payload=payload
    )


def show_device_registration_operation(
    cmd,
    registration_id: str,
    operation_id: str,
    attestation_mechanism: str = AttestationType.symmetricKey.value,
    enrollment_group_id: str = None,
    device_symmetric_key: str = None,
    group_symmetric_key: str = None,
    dps_name: str = None,
    id_scope: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return device_provider.operation_get(
        registration_id=registration_id,
        attestation_mechanism=attestation_mechanism,
        operation_id=operation_id,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        group_symmetric_key=group_symmetric_key
    )
