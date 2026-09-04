# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from dataclasses import dataclass
from typing import Any, Dict, Optional

from knack.log import get_logger

from azext_iot.dps.providers.device_registration import DeviceRegistrationProvider

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeviceRegistrationAuthContext:
    """Typed authentication/discovery inputs shared by registration wrappers."""

    id_scope: Optional[str] = None
    dps_name: Optional[str] = None
    resource_group_name: Optional[str] = None
    login: Optional[str] = None
    auth_type_dataplane: Optional[str] = None
    provisioning_host: Optional[str] = None
    enrollment_group_id: Optional[str] = None
    device_symmetric_key: Optional[str] = None
    compute_key: bool = False
    certificate_file: Optional[str] = None
    key_file: Optional[str] = None
    passphrase: Optional[str] = None

    def provider_kwargs(self) -> Dict[str, Any]:
        return {
            "id_scope": self.id_scope,
            "dps_name": self.dps_name,
            "resource_group_name": self.resource_group_name,
            "login": self.login,
            "auth_type_dataplane": self.auth_type_dataplane,
            "provisioning_host": self.provisioning_host,
            "enrollment_group_id": self.enrollment_group_id,
            "device_symmetric_key": self.device_symmetric_key,
            "compute_key": self.compute_key,
            "certificate_file": self.certificate_file,
            "key_file": self.key_file,
            "passphrase": self.passphrase,
        }


def create_device_registration(
    cmd,
    registration_id: str,
    enrollment_group_id: str = None,
    device_symmetric_key: str = None,
    compute_key: bool = False,
    certificate_file: str = None,
    key_file: str = None,
    passphrase: str = None,
    csr: str = None,
    payload=None,
    endorsement_key: str = None,
    storage_root_key: str = None,
    id_scope: str = None,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
    provisioning_host: str = None,
):
    device_provider = _get_provider(
        cmd=cmd,
        registration_id=registration_id,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
        provisioning_host=provisioning_host,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        compute_key=compute_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase,
    )
    return device_provider.create(
        csr=csr,
        payload=payload,
        endorsement_key=endorsement_key,
        storage_root_key=storage_root_key,
    )


def _get_provider(
    cmd,
    registration_id: str,
    id_scope: Optional[str] = None,
    dps_name: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    login: Optional[str] = None,
    auth_type_dataplane: Optional[str] = None,
    provisioning_host: Optional[str] = None,
    enrollment_group_id: Optional[str] = None,
    device_symmetric_key: Optional[str] = None,
    compute_key: bool = False,
    certificate_file: Optional[str] = None,
    key_file: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> DeviceRegistrationProvider:
    auth = DeviceRegistrationAuthContext(
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
        provisioning_host=provisioning_host,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        compute_key=compute_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase,
    )
    return DeviceRegistrationProvider(
        cmd=cmd,
        registration_id=registration_id,
        **auth.provider_kwargs(),
    )


def show_device_registration_operation(
    cmd,
    registration_id,
    operation_id,
    id_scope=None,
    dps_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
    provisioning_host=None,
    enrollment_group_id=None,
    device_symmetric_key=None,
    compute_key=False,
    certificate_file=None,
    key_file=None,
    passphrase=None,
):
    return _get_provider(
        cmd=cmd,
        registration_id=registration_id,
        id_scope=id_scope,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
        provisioning_host=provisioning_host,
        enrollment_group_id=enrollment_group_id,
        device_symmetric_key=device_symmetric_key,
        compute_key=compute_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase,
    ).operation_status(operation_id)
