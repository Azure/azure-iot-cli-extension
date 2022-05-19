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
from azext_iot.constants import IOTDPS_RESOURCE_ID, USER_AGENT
from azext_iot.dps.common import MAX_REGISTRATION_ASSIGNMENT_RETRIES, DeviceRegistrationStatus
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import (
    iot_dps_compute_device_key,
    iot_dps_device_enrollment_get,
    iot_dps_device_enrollment_group_get
)
from azext_iot.sdk.dps.device.provisioning_device_client import ProvisioningDeviceClient
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
            compute_key=compute_key
        )

        # Retrieve sdk.runtime_registration
        self.runtime_registration = self._get_dps_device_sdk().runtime_registration

    def _validate_attestation_params(
        self,
        enrollment_group_id: str = None,
        symmetric_key: str = None,
        compute_key: bool = False,
    ):
        if compute_key and not enrollment_group_id:
            raise RequiredArgumentMissingError("Enrollment group id via --group-id is required if --compute-key is used.")

        self.symmetric_key = None
        # Retrieve the attestation if nothing is provided.
        if not symmetric_key:
            self._get_attestation_params(enrollment_group_id=enrollment_group_id)
        # user provided attestation mechanisms; TODO: support other mechanisms in the future
        else:
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
        credentials = SasTokenAuthentication(
            uri=f"{self.id_scope}/registrations/{self.registration_id}",
            shared_access_policy_name=None,
            shared_access_key=self.symmetric_key,
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
        payload: str = None,
        wait: bool = False,
        poll_interval: int = 5,
    ):
        try:
            registration_result = self.runtime_registration.register_device(
                registration_id=self.registration_id,
                device_registration={
                    "registration_id": self.registration_id,
                    "tpm": None,
                    "payload": payload,
                },
                id_scope=self.id_scope
            )
            if wait:
                retries = 0
                while (
                    registration_result.status == DeviceRegistrationStatus.assigning.value
                    and retries < MAX_REGISTRATION_ASSIGNMENT_RETRIES
                ):
                    retries += 1
                    sleep(poll_interval)
                    registration_result = self.runtime_registration.operation_status_lookup(
                        registration_id=self.registration_id,
                        operation_id=registration_result.operation_id,
                        id_scope=self.id_scope
                    )
            return registration_result
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def get(
        self,
        payload: str = None,
    ):
        try:
            return self.runtime_registration.device_registration_status_lookup(
                registration_id=self.registration_id,
                device_registration={
                    "registration_id": self.registration_id,
                    "tpm": None,
                    "payload": payload,
                },
                id_scope=self.id_scope
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def operation_get(
        self,
        operation_id: str,
    ):
        try:
            return self.runtime_registration.operation_status_lookup(
                registration_id=self.registration_id,
                operation_id=operation_id,
                id_scope=self.id_scope
            )
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
            else:
                raise InvalidArgumentValueError(
                    f"Device registration with {attestation['type']} attestation is not supported yet."
                )
