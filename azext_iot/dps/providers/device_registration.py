# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import handle_service_exception
from azext_iot.constants import IOTDPS_RESOURCE_ID, USER_AGENT
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.operations.dps import iot_dps_compute_device_key, iot_dps_device_enrollment_get
from azext_iot.sdk.dps.device.provisioning_device_client import ProvisioningDeviceClient
from azext_iot.sdk.dps.service.models.provisioning_service_error_details_py3 import ProvisioningServiceErrorDetailsException


class DeviceRegistrationProvider():
    def __init__(
        self,
        cmd,
        dps_name: str = None,
        resource_group_name: str = None,
        login: str = None,
        auth_type_dataplane: str = None,
    ):
        self.cmd = cmd
        discovery = DPSDiscovery(cmd)
        self.target = discovery.get_target(
            dps_name,
            resource_group_name,
            login=login,
            auth_type=auth_type_dataplane,
        )
        self.dps_name = dps_name
        self.resource_group_name = resource_group_name
        self.login = login
        self.auth_type_dataplane = auth_type_dataplane

    def _get_dps_device_sdk(
        self,
        registration_id: str,
        device_symmetric_key: str,
        endpoint: str = None,
    ):
        from azext_iot.sdk.dps.device import ProvisioningDeviceClient
        credentials = SasTokenAuthentication(
            uri=f"{self.target['idscope']}/registrations/{registration_id}",
            shared_access_policy_name=None,
            shared_access_key=device_symmetric_key,
        )

        return ProvisioningDeviceClient(credentials=credentials, base_url=endpoint)

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
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
    ):
        try:
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

            return sdk.runtime_registration.register_device(
                registration_id=registration_id,
                device_registration={
                    "registration_id": registration_id,
                    "tpm": None,
                    "payload": None,
                },
                id_scope=self.target["idscope"]
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def get(
        self,
        registration_id: str,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
    ):
        try:
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

            return sdk.runtime_registration.device_registration_status_lookup(
                registration_id=registration_id,
                device_registration={},
                id_scope=self.target["idscope"]
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def operation_get(
        self,
        registration_id: str,
        operation_id: str,
        enrollment_group_id: str = None,
        device_symmetric_key: str = None,
        group_symmetric_key: str = None,
    ):
        try:
            device_symmetric_key = self._get_device_symmetric_key(
                registration_id=registration_id,
                enrollment_group_id=enrollment_group_id,
                group_symmetric_key=group_symmetric_key,
            )
            sdk = self._get_dps_device_sdk(
                registration_id=registration_id,
                device_symmetric_key=device_symmetric_key,
                endpoint=self.target["entity"]
            )
            return sdk.runtime_registration.operation_status_lookup(
                registration_id=registration_id,
                operation_id=operation_id,
                id_scope=self.target["idscope"]
            )
        except ProvisioningServiceErrorDetailsException as e:
            handle_service_exception(e)

    def _get_device_symmetric_key(
        self,
        registration_id: str,
        enrollment_group_id: str = None,
        group_symmetric_key: str = None,
    ) -> str:
        if not enrollment_group_id:
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