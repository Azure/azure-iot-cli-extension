# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from knack.log import get_logger

from azext_iot.constants import IOTDPS_PROVISIONING_HOST
from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider

logger = get_logger(__name__)


def create_device_registration(
    cmd,
    registration_id: str,
    enrollment_group_id: str = None,
    device_symmetric_key: str = None,
    compute_key: bool = False,
    certificate_file: str = None,
    key_file: str = None,
    passphrase: str = None,
    payload: str = None,
    id_scope: str = None,
    dps_name_or_hostname: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
    provisioning_host: str = IOTDPS_PROVISIONING_HOST,
):
    device_provider = DeviceRegistrationProvider(
        cmd=cmd,
        registration_id=registration_id,
        id_scope=id_scope,
        dps_name_or_hostname=dps_name_or_hostname,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    return device_provider.create(
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        compute_key=compute_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase,
        payload=payload,
        provisioning_host=provisioning_host
    )
