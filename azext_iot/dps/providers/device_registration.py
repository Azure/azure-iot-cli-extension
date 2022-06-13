# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from typing import TypeVar
from azext_iot.common.shared import AttestationType
from azext_iot.constants import IOTDPS_PROVISIONING_HOST
from azext_iot.dps.common import (
    DISABLED_REGISTRATION_ERROR,
    FAILED_REGISTRATION_ERROR,
    UNAUTHORIZED_ERROR,
    COMPUTE_KEY_ERROR,
    CERTIFICATE_FILE_ERROR,
    CERTIFICATE_RETRIEVAL_ERROR,
    TPM_SUPPORT_ERROR,
)
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import (
    iot_dps_compute_device_key,
    iot_dps_device_enrollment_get,
    iot_dps_device_enrollment_group_get
)
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    AzureResponseError,
    AzureConnectionError,
    UnauthorizedError
)

logger = get_logger(__name__)
ProvisioningDeviceClient = TypeVar('ProvisioningDeviceClient')


class DeviceRegistrationProvider():
    def __init__(
        self,
        cmd,
        registration_id: str,
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

        self.id_scope = id_scope or self._get_idscope()
        self.registration_id = registration_id

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
        return discovery.get_id_scope(resource_name=dps_name, rg=self.resource_group_name)

    def create(
        self,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
        provisioning_host: str = IOTDPS_PROVISIONING_HOST,
        payload: str = None,
    ):
        self._validate_attestation_params(
            enrollment_group_id=enrollment_group_id,
            device_symmetric_key=device_symmetric_key,
            compute_key=compute_key,
            certificate_file=certificate_file,
            key_file=key_file,
            passphrase=passphrase
        )

        # Retrieve sdk.runtime_registration
        sdk = self._get_dps_device_sdk(provisioning_host)

        from azure.iot.device.exceptions import (
            ClientError,
            OperationTimeout
        )
        try:
            sdk.provisioning_payload = payload
            registration_result = sdk.register()
            return {
                "operationId": registration_result.operation_id,
                "status": registration_result.status,
                "registrationState": {
                    "registrationId": self.registration_id,
                    "deviceId": registration_result.registration_state.device_id,
                    "assignedHub": registration_result.registration_state.assigned_hub,
                    "substatus": registration_result.registration_state.sub_status,
                    "createdDateTimeUtc": registration_result.registration_state.created_date_time,
                    "lastUpdatedDateTimeUtc": registration_result.registration_state.last_update_date_time,
                    "etag": registration_result.registration_state.etag,
                    "responsePayload": registration_result.registration_state.response_payload,
                }
            }
        except (ClientError, OperationTimeout) as e:
            raise self._handle_exception(e, is_group=bool(enrollment_group_id))

    def _validate_attestation_params(
        self,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        compute_key: bool = False,
        certificate_file: str = None,
        key_file: str = None,
        passphrase: str = None,
    ):
        from azure.iot.device import X509
        if compute_key and not (enrollment_group_id or device_symmetric_key):
            raise RequiredArgumentMissingError(COMPUTE_KEY_ERROR)

        self.device_symmetric_key = None
        self.certificate = None
        if device_symmetric_key:
            if not compute_key:
                self.device_symmetric_key = device_symmetric_key
            else:
                self.device_symmetric_key = iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    symmetric_key=device_symmetric_key,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
        elif certificate_file or key_file:
            self.certificate = X509(
                cert_file=certificate_file,
                key_file=key_file,
                pass_phrase=passphrase or ""
            )
        elif certificate_file or key_file:
            raise RequiredArgumentMissingError(CERTIFICATE_FILE_ERROR)
        # Retrieve the attestation if nothing is provided.
        else:
            self._get_attestation_params(enrollment_group_id=enrollment_group_id)

    def _get_dps_device_sdk(
        self,
        provisioning_host: str = IOTDPS_PROVISIONING_HOST
    ) -> ProvisioningDeviceClient:
        from azure.iot.device import ProvisioningDeviceClient
        from ssl import SSLError
        if self.device_symmetric_key:
            return ProvisioningDeviceClient.create_from_symmetric_key(
                provisioning_host=provisioning_host,
                registration_id=self.registration_id,
                id_scope=self.id_scope,
                symmetric_key=self.device_symmetric_key,
            )
        elif self.certificate:
            try:
                return ProvisioningDeviceClient.create_from_x509_certificate(
                    provisioning_host=provisioning_host,
                    registration_id=self.registration_id,
                    id_scope=self.id_scope,
                    x509=self.certificate,
                )
            except SSLError as e:
                reason = getattr(e, "reason", "Unknown error occurred")
                raise InvalidArgumentValueError(f"Could not open certificate files: {reason}.")

        raise InvalidArgumentValueError(TPM_SUPPORT_ERROR)

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
                self.device_symmetric_key = iot_dps_compute_device_key(
                    cmd=self.cmd,
                    registration_id=self.registration_id,
                    enrollment_id=enrollment_group_id,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )
            elif attestation["type"] == AttestationType.x509.value:
                raise InvalidArgumentValueError(CERTIFICATE_RETRIEVAL_ERROR)
            else:
                raise InvalidArgumentValueError(TPM_SUPPORT_ERROR)
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
                self.device_symmetric_key = iot_dps_device_enrollment_get(
                    cmd=self.cmd,
                    enrollment_id=self.registration_id,
                    show_keys=True,
                    dps_name=self.dps_name,
                    resource_group_name=self.resource_group_name,
                    login=self.login,
                    auth_type_dataplane=self.auth_type_dataplane,
                )["attestation"]["symmetricKey"]["primaryKey"]
            elif attestation["type"] == AttestationType.x509.value:
                raise InvalidArgumentValueError(CERTIFICATE_RETRIEVAL_ERROR)
            else:
                raise InvalidArgumentValueError(TPM_SUPPORT_ERROR)

    def _handle_exception(self, error: Exception, is_group: bool = False) -> Exception:
        from azure.iot.device.exceptions import (
            ClientError,
            CredentialError,
            ConnectionFailedError,
            ConnectionDroppedError,
            OperationTimeout
        )
        if isinstance(error, CredentialError):
            return UnauthorizedError("Unauthorized.")
        elif isinstance(error, ConnectionFailedError):
            return AzureConnectionError("Connection Failed.")
        elif isinstance(error, ConnectionDroppedError):
            return AzureConnectionError("Connection Dropped.")
        elif isinstance(error, OperationTimeout):
            return AzureConnectionError("Operation Timeout.")
        elif isinstance(error, ClientError):
            cause = str(error.__cause__)
            msg = "See registration status with `az iot dps {} registration show`.".format(
                "enrollment-group" if is_group else "enrollment"
            )
            if cause == DISABLED_REGISTRATION_ERROR:
                return AzureResponseError(f"Created registration is disabled. {msg}")
            elif cause == FAILED_REGISTRATION_ERROR:
                return AzureResponseError(f"Registration failed. {msg}")
            elif cause == UNAUTHORIZED_ERROR:
                return UnauthorizedError("Unauthorized.")
            else:
                return AzureResponseError(f"{cause}. {msg}")
        else:
            return error
