# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List
from azext_iot.central.models.devicev1 import DeviceV1
from knack.util import CLIError
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.enum import DeviceStatus, ApiVersion
from azext_iot.dps.services import global_service as dps_global_service


logger = get_logger(__name__)


class CentralDeviceProviderV1:
    def __init__(self, cmd, app_id: str, token=None):
        """
        Provider for device APIs

        Args:
            cmd: command passed into az
            app_id: name of app (used for forming request URL)
            token: (OPTIONAL) authorization token to fetch device details from IoTC.
                MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
                Useful in scenarios where user doesn't own the app
                therefore AAD token won't work, but a SAS token generated by owner will
        """
        self._cmd = cmd
        self._app_id = app_id
        self._token = token
        self._devices = {}
        self._device_templates = {}
        self._device_credentials = {}
        self._device_registration_info = {}

    def get_device(
        self,
        device_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> DeviceV1:

        # get or add to cache
        device = self._devices.get(device_id)
        if not device:
            device = central_services.device.get_device(
                cmd=self._cmd,
                app_id=self._app_id,
                device_id=device_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=ApiVersion.v1.value,
            )
            self._devices[device_id] = device

        if not device:
            raise CLIError("No device found with id: '{}'.".format(device_id))

        return device

    def list_devices(
        self,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> List[DeviceV1]:
        devices = central_services.device.list_devices(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

        # add to cache
        self._devices.update({device.id: device for device in devices})

        return self._devices

    def create_device(
        self,
        device_id,
        device_name=None,
        template=None,
        simulated=False,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> DeviceV1:
        if not device_id:
            raise CLIError("Device id must be specified.")

        if device_id in self._devices:
            raise CLIError("Device already exists.")

        device = central_services.device.create_device(
            cmd=self._cmd,
            app_id=self._app_id,
            device_id=device_id,
            device_name=device_name,
            template=template,
            simulated=simulated,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

        if not device:
            raise CLIError("No device found with id: '{}'.".format(device_id))

        # add to cache
        self._devices[device.id] = device

        return device

    def delete_device(
        self,
        device_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> dict:
        if not device_id:
            raise CLIError("Device id must be specified.")

        # get or add to cache
        result = central_services.device.delete_device(
            cmd=self._cmd,
            app_id=self._app_id,
            device_id=device_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

        # remove from cache
        # pop "miss" raises a KeyError if None is not provided
        self._devices.pop(device_id, None)
        self._device_credentials.pop(device_id, None)

        return result

    def get_device_credentials(
        self,
        device_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> dict:
        credentials = self._device_credentials.get(device_id)

        if not credentials:
            credentials = central_services.device.get_device_credentials(
                cmd=self._cmd,
                app_id=self._app_id,
                device_id=device_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=ApiVersion.v1.value,
            )

        if not credentials:
            raise CLIError(
                "Could not find device credentials for device '{}'.".format(device_id)
            )

        # add to cache
        self._device_credentials[device_id] = credentials

        return credentials

    def get_device_registration_info(
        self,
        device_id,
        device_status: DeviceStatus,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> dict:
        dps_state = {}
        info = self._device_registration_info.get(device_id)

        if info:
            return info

        device = self.get_device(device_id, central_dns_suffix)
        if device.device_status == DeviceStatus.provisioned:
            credentials = self.get_device_credentials(
                device_id=device_id,
                central_dns_suffix=central_dns_suffix,
            )
            id_scope = credentials["idScope"]
            key = credentials["symmetricKey"]["primaryKey"]
            dps_state = dps_global_service.get_registration_state(
                id_scope=id_scope, key=key, device_id=device_id
            )
        dps_state = self._dps_populate_essential_info(dps_state, device.device_status)

        info = {
            "@device_id": device_id,
            "dps_state": dps_state,
            "device_registration_info": device.get_registration_info(),
        }

        self._device_registration_info[device_id] = info

        return info

    def get_device_registration_summary(self, central_dns_suffix=CENTRAL_ENDPOINT):
        return central_services.device.get_device_registration_summary(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
        )

    def run_command(
        self,
        device_id: str,
        interface_id: str,
        command_name: str,
        payload: dict,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        if interface_id and self._is_interface_id_component(
            device_id=device_id,
            interface_id=interface_id,
            central_dns_suffix=central_dns_suffix,
        ):
            return central_services.device.run_component_command(
                cmd=self._cmd,
                app_id=self._app_id,
                token=self._token,
                device_id=device_id,
                interface_id=interface_id,
                command_name=command_name,
                payload=payload,
                central_dns_suffix=central_dns_suffix,
                api_version=ApiVersion.v1.value,
            )
        return central_services.device.run_command(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            device_id=device_id,
            command_name=command_name,
            payload=payload,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

    def get_command_history(
        self,
        device_id: str,
        interface_id: str,
        command_name: str,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):

        if interface_id and self._is_interface_id_component(
            device_id=device_id,
            interface_id=interface_id,
            central_dns_suffix=central_dns_suffix,
        ):
            return central_services.device.get_component_command_history(
                cmd=self._cmd,
                app_id=self._app_id,
                token=self._token,
                device_id=device_id,
                interface_id=interface_id,
                command_name=command_name,
                central_dns_suffix=central_dns_suffix,
                api_version=ApiVersion.v1.value,
            )

        return central_services.device.get_command_history(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            device_id=device_id,
            command_name=command_name,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

    def run_manual_failover(
        self,
        device_id: str,
        ttl_minutes: int = None,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        return central_services.device.run_manual_failover(
            cmd=self._cmd,
            app_id=self._app_id,
            device_id=device_id,
            ttl_minutes=ttl_minutes,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
        )

    def run_manual_failback(
        self,
        device_id: str,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        return central_services.device.run_manual_failback(
            cmd=self._cmd,
            app_id=self._app_id,
            device_id=device_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
        )

    def _dps_populate_essential_info(self, dps_info, device_status: DeviceStatus):
        error = {
            DeviceStatus.provisioned: "None.",
            DeviceStatus.registered: "Device is not yet provisioned.",
            DeviceStatus.blocked: "Device is blocked from connecting to IoT Central application."
            " Unblock the device in IoT Central and retry. Learn more: https://aka.ms/iotcentral-docs-dps-SAS",
            DeviceStatus.unassociated: "Device does not have a valid template associated with it.",
        }

        filtered_dps_info = {
            "status": dps_info.get("status"),
            "error": error.get(device_status),
        }
        return filtered_dps_info

    def _is_interface_id_component(
        self,
        device_id: str,
        interface_id: str,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> bool:

        current_device = self.get_device(device_id, central_dns_suffix)

        template = central_services.device_template.get_device_template(
            cmd=self._cmd,
            app_id=self._app_id,
            device_template_id=current_device.template,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.v1.value,
        )

        return bool(interface_id in template.components)