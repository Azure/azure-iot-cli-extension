# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from logging import getLogger
from time import sleep
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import AttestationType
from azext_iot.common.utility import handle_service_exception
from azext_iot.constants import IOTDPS_PROVISIONING_HOST
from azext_iot.dps.common import MAX_REGISTRATION_ASSIGNMENT_RETRIES, DeviceRegistrationStatus
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import (
    iot_dps_compute_device_key,
    iot_dps_device_enrollment_get,
    iot_dps_device_enrollment_group_get
)
from azure.iot.device import ProvisioningDeviceClient, X509
from azext_iot.sdk.dps.device.models import ProvisioningServiceErrorDetailsException
from azure.cli.core.azclierror import InvalidArgumentValueError, RequiredArgumentMissingError

logger = getLogger(__name__)


class DeviceRegistrationProvider():
    def __init__(
        self,
        cmd,
        registration_id: str,
        enrollment_group_id: str = None,
        symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
        id_scope: str = None,
        dps_name: str = None,
        resource_group_name: str = None,
        login: str = None,
        auth_type_dataplane: str = None,
    ):
        self.cmd = cmd
        self.dps_name = dps_name
        self.resource_group_name = resource_group_name
        self.login = login
        self.auth_type_dataplane = auth_type_dataplane
        self.registration_id = registration_id
        self.id_scope = id_scope or self._get_idscope()

        self._validate_attestation_params(
            enrollment_group_id=enrollment_group_id,
            symmetric_key=symmetric_key,
            compute_key=compute_key,
            certificate_file=certificate_file,
            key_file=key_file,
            passphrase=passphrase
        )

        # Retrieve sdk.runtime_registration
        self.sdk = self._get_dps_device_sdk()

    def _validate_attestation_params(
        self,
        enrollment_group_id: str = None,
        symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
    ):
        if compute_key and not enrollment_group_id:
            raise RequiredArgumentMissingError("Enrollment group id via --group-id is required if --compute-key is used.")

        self.symmetric_key = None
        self.certificate = None
        if symmetric_key:
            if not compute_key:
                self.symmetric_key = symmetric_key
            else:
                self.symmetric_key = iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    symmetric_key=symmetric_key,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
        elif certificate_file and key_file:
            self.certificate = X509(
                cert_file=certificate_file,
                key_file=key_file,
                pass_phrase=passphrase or ""
            )
        elif certificate_file or key_file:
            raise RequiredArgumentMissingError("Both certificate and key files are required for registration with x509.")
        # Retrieve the attestation if nothing is provided.
        else:
            self._get_attestation_params(enrollment_group_id=enrollment_group_id)

    def _get_idscope(self) -> str:
        discovery = DPSDiscovery(self.cmd)
        target = discovery.get_target(
            self.dps_name,
            self.resource_group_name,
            login=self.login,
            auth_type=self.auth_type_dataplane,
        )
        if target.get("idscope"):
            return target["idscope"]
        # If cstring is used, will need to retrieve the id scope manually
        dps_name = target['entity'].split(".")[0]
        return discovery.get_id_scope(resource_name=dps_name)

    def _get_dps_device_sdk(
        self
    ) -> ProvisioningDeviceClient:
        if self.symmetric_key:
            return ProvisioningDeviceClient.create_from_symmetric_key(
                provisioning_host=IOTDPS_PROVISIONING_HOST,
                registration_id=self.registration_id,
                id_scope=self.id_scope,
                symmetric_key=self.symmetric_key,
            )
        elif self.certificate:
            return ProvisioningDeviceClient.create_from_x509(
                provisioning_host=IOTDPS_PROVISIONING_HOST,
                registration_id=self.registration_id,
                id_scope=self.id_scope,
                x509=self.certificate,
            )

    def create(
        self,
        payload: str = None,
    ):
        try:
            self.sdk.provisioning_payload = payload
            registration_result = self.sdk.register()
            return {
                "operation_id": registration_result.operation_id,
                "status:": registration_result.status,
                "registration_state": {
                    "device_id": registration_result.registration_state.device_id,
                    "assigned_hub": registration_result.registration_state.assigned_hub,
                    "sub_status": registration_result.registration_state.sub_status,
                    "created_date_time": registration_result.registration_state.created_date_time,
                    "last_update_date_time": registration_result.registration_state.last_update_date_time,
                    "etag": registration_result.registration_state.etag,
                    "response_payload": registration_result.registration_state.response_payload,
                }
            }
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def _get_attestation_params(
        self,
        enrollment_group_id: str = None,
    ):
        if enrollment_group_id:
            attestation = iot_dps_device_enrollment_group_get(
                cmd=self.cmd,
                enrollment_id=enrollment_group_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )["attestation"]
            if attestation["type"] == AttestationType.symmetricKey.value:
                self.symmetric_key = iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
            elif attestation["type"] == AttestationType.symmetricKey.value:
                raise InvalidArgumentValueError(
                    "Please provide the certificate and key files via --certificate-file and --key-file."
                )
            else:
                raise InvalidArgumentValueError(
                    f"Device registration with {attestation['type']} attestation is not supported yet."
                )
        else:
            attestation = iot_dps_device_enrollment_get(
                cmd=self.cmd,
                enrollment_id=self.registration_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )["attestation"]
            if attestation["type"] == AttestationType.symmetricKey.value:
                self.symmetric_key = iot_dps_device_enrollment_get(
                    cmd=self.cmd,
                    enrollment_id=self.registration_id,
                    show_keys=True,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )["attestation"]["symmetricKey"]["primaryKey"]
            elif attestation["type"] == AttestationType.symmetricKey.value:
                raise InvalidArgumentValueError(
                    "Please provide the certificate and key files via --certificate-file and --key-file."
                )
            else:
                raise InvalidArgumentValueError(
                    f"Device registration with {attestation['type']} attestation is not supported yet."
                )
