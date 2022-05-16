# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from logging import getLogger
from azext_iot.common.certops import open_certificate
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import AttestationType
from azext_iot.common.utility import handle_service_exception
from azext_iot.common.x509_auth import X509Authentication
from azext_iot.constants import IOTDPS_RESOURCE_ID, USER_AGENT
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import iot_dps_compute_device_key, iot_dps_device_enrollment_get, iot_dps_device_enrollment_group_get
from azext_iot.sdk.dps.device.provisioning_device_client import ProvisioningDeviceClient
from azext_iot.sdk.dps.service.models.provisioning_service_error_details_py3 import ProvisioningServiceErrorDetailsException
from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError, RequiredArgumentMissingError

from azext_iot.sdk.dps.service.models.tpm_attestation_py3 import TpmAttestation

logger = getLogger(__name__)


class DeviceRegistrationProvider():
    def __init__(
        self,
        cmd,
        id_scope: str = None,
        dps_name: str = None,
        resource_group_name: str = None,
        login: str = None,
        auth_type_dataplane: str = None,
    ):
        self.cmd = cmd
        self.id_scope = id_scope
        self.dps_name = dps_name
        self.resource_group_name = resource_group_name
        self.login = login
        self.auth_type_dataplane = auth_type_dataplane

        # Use discovery to get id_scope if not provided
        if not id_scope:
            discovery = DPSDiscovery(cmd)
            self.target = discovery.get_target(
                dps_name,
                resource_group_name,
                login=login,
                auth_type=auth_type_dataplane,
            )
            self.id_scope = self.target.get("idscope")
            # Todo: figure out if this should be done
            # issue is that cstring does not have idscope - will need to get with
            # az iot dps show -n dps-name which may not be what we want to do
            if self.target.get("idscope") is None:
                self.id_scope = self._get_idscope()

    def _get_idscope(self):
        dps_name = self.target['entity'].split(".")[0]
        return self.cmd(
            f"iot dps show -n {dps_name}"
        ).get_output_in_json()["properties"]["idScope"]

    def _get_dps_device_sdk(
        self,
        registration_id: str,
        device_symmetric_key: str = None,
        certificate: str = None,
    ):
        from azext_iot.sdk.dps.device import ProvisioningDeviceClient

        credentials = certificate
        if device_symmetric_key:
            credentials = SasTokenAuthentication(
                uri=f"{self.id_scope}/registrations/{registration_id}",
                shared_access_policy_name=None,
                shared_access_key=device_symmetric_key,
            )
        else:
            credentials = X509Authentication(
                certificate_info=certificate
            )

        return ProvisioningDeviceClient(credentials=credentials)

    def get_sdk(self, endpoint: str = None):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        # TODO: figure out if this can be used with the device sym key.

        client = get_mgmt_service_client(
            cli_ctx=self.cmd.cli_ctx,
            client_or_resource_type=ProvisioningDeviceClient,
            base_url=endpoint,
            resource=IOTDPS_RESOURCE_ID,
            subscription_bound=False,
            base_url_bound=False,
        )

        client.config.add_user_agent(USER_AGENT)
        return client

    def create(
        self,
        registration_id: str,
        attestation_mechanism: str = AttestationType.symmetricKey.value,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
        # endorsement_key: str = None,
        # storage_root_key: str = None,
        # certificate_path: str = None,
        payload: str = None,
    ):
        try:
            sdk = None
            tpm = None
            if attestation_mechanism == AttestationType.tpm.value:
                raise NotImplementedError("Device registration with TPM attestation is not supported yet.")
                # if not endorsement_key:
                #     endorsement_key = self._get_endorsement_key(
                #         registration_id=registration_id,
                #         enrollment_group_id=enrollment_group_id,
                #     )
                # tpm = TpmAttestation(
                #     endorsement_key=endorsement_key,
                #     storage_root_key=storage_root_key
                # )
                # sdk = self._get_dps_device_sdk(
                #     registration_id=registration_id,

                # )
            elif attestation_mechanism == AttestationType.x509.value:
                raise NotImplementedError("Device registration with x509 attestation is not supported yet.")
                # if not certificate_path:
                #     raise RequiredArgumentMissingError("Certificate file required for device registration.")
                # certificate = open_certificate(
                #     certificate_path=certificate_path
                # )
                # sdk = self._get_dps_device_sdk(
                #     registration_id=registration_id,
                #     certificate=certificate
                # )
            elif attestation_mechanism == AttestationType.symmetricKey.value:
                # symmetric key
                if not device_symmetric_key:
                    device_symmetric_key = self._get_device_symmetric_key(
                        registration_id=registration_id,
                        enrollment_group_id=enrollment_group_id,
                        group_symmetric_key=group_symmetric_key,
                    )
                sdk = self._get_dps_device_sdk(
                    registration_id=registration_id,
                    device_symmetric_key=device_symmetric_key
                )
            else:
                raise InvalidArgumentValueError("Given attestation type is not supported.")

            return sdk.runtime_registration.register_device(
                registration_id=registration_id,
                device_registration={
                    "registration_id": registration_id,
                    "tpm": tpm,
                    "payload": payload,
                },
                id_scope=self.id_scope
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def get(
        self,
        registration_id: str,
        attestation_mechanism: str = AttestationType.symmetricKey.value,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
        payload: str = None,
    ):
        try:
            sdk = None
            tpm = None
            if attestation_mechanism == AttestationType.tpm.value:
                raise NotImplementedError("Device registration with TPM attestation is not supported yet.")
            elif attestation_mechanism == AttestationType.x509.value:
                raise NotImplementedError("Device registration with x509 attestation is not supported yet.")
            elif attestation_mechanism == AttestationType.symmetricKey.value:
                # symmetric key
                if not device_symmetric_key:
                    device_symmetric_key = self._get_device_symmetric_key(
                        registration_id=registration_id,
                        enrollment_group_id=enrollment_group_id,
                        group_symmetric_key=group_symmetric_key,
                    )
                sdk = self._get_dps_device_sdk(
                    registration_id=registration_id,
                    device_symmetric_key=device_symmetric_key
                )
            else:
                raise InvalidArgumentValueError("Given attestation type is not supported.")

            return sdk.runtime_registration.device_registration_status_lookup(
                registration_id=registration_id,
                device_registration={
                    "registration_id": registration_id,
                    "tpm": tpm,
                    "payload": payload,
                },
                id_scope=self.id_scope
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def operation_get(
        self,
        registration_id: str,
        operation_id: str,
        attestation_mechanism: str = AttestationType.symmetricKey.value,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
    ):
        try:
            sdk = None
            if attestation_mechanism == AttestationType.tpm.value:
                raise NotImplementedError("Device registration with TPM attestation is not supported yet.")
            elif attestation_mechanism == AttestationType.x509.value:
                raise NotImplementedError("Device registration with x509 attestation is not supported yet.")
            elif attestation_mechanism == AttestationType.symmetricKey.value:
                if not device_symmetric_key:
                    device_symmetric_key = self._get_device_symmetric_key(
                        registration_id=registration_id,
                        enrollment_group_id=enrollment_group_id,
                        group_symmetric_key=group_symmetric_key,
                    )
                sdk = self._get_dps_device_sdk(
                    registration_id=registration_id,
                    device_symmetric_key=device_symmetric_key
                )
            else:
                raise InvalidArgumentValueError("Given attestation type is not supported.")

            return sdk.runtime_registration.operation_status_lookup(
                registration_id=registration_id,
                operation_id=operation_id,
                id_scope=self.id_scope
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def _get_device_symmetric_key(
        self,
        registration_id: str,
        enrollment_group_id: str = None,
        group_symmetric_key: str = None,
    ) -> str:
        if group_symmetric_key and not enrollment_group_id:
            raise ArgumentUsageError("Individual enrollments do not have enrollment group keys.")
        elif not enrollment_group_id:
            enrollment = iot_dps_device_enrollment_get(
                cmd=self.cmd,
                enrollment_id=registration_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                show_keys=True,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )
            return enrollment["attestation"]["symmetricKey"]["primaryKey"]

        return iot_dps_compute_device_key(
            cmd=self.cmd,
            registration_id=registration_id,
            enrollment_id=enrollment_group_id,
            dps_name=self.dps_name,
            resource_group_name=self.resource_group_name,
            symmetric_key=group_symmetric_key,
            login=self.login,
            auth_type_dataplane=self.auth_type_dataplane,
        )

    def _get_endorsement_key(
        self,
        registration_id: str = None,
        enrollment_group_id: str = None,
    ) -> str:
        enrollment = None
        if enrollment_group_id:
            enrollment = iot_dps_device_enrollment_group_get(
                cmd=self.cmd,
                enrollment_id=enrollment_group_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )
        else:
            enrollment = iot_dps_device_enrollment_get(
                cmd=self.cmd,
                enrollment_id=registration_id,
                dps_name=self.dps_name,
                resource_group_name=self.resource_group_name,
                login=self.login,
                auth_type_dataplane=self.auth_type_dataplane,
            )

        if not enrollment["attestation"].get("tpm"):
            raise InvalidArgumentValueError("Enrollment does not use TPM attestation.")

        return enrollment["attestation"]["tpm"]["endorsementKey"]
