# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.central import services as central_services
from .device_template_provider import CentralDeviceTemplateProvider


class CentralDeviceProvider:
    def __init__(self, cmd, app_id, token=None):
        """
        Provider for device/device_template APIs

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

    def get_device(
        self, device_id, central_dns_suffix="azureiotcentral.com",
    ):
        if not device_id:
            raise CLIError("Device id must be specified.")

        # get or add to cache
        if device_id not in self._devices or not self._devices.get(device_id):
            self._devices[device_id] = central_services.device.get_device(
                self._cmd, device_id, self._app_id, self._token, central_dns_suffix
            )

        device = self._devices[device_id]
        if not device:
            raise CLIError("No device found with id: '{}'.".format(device_id))

        return device

    def get_device_template_by_device_id(
        self, device_id, central_dns_suffix="azureiotcentral.com",
    ):
        if not device_id:
            raise CLIError("Device id must be specified.")

        device = self.get_device(device_id, central_dns_suffix)
        device_template_id = device["instanceOf"]

        template = CentralDeviceTemplateProvider.get_device_template(
            self=self,
            device_template_id=device_template_id,
            central_dns_suffix=central_dns_suffix,
        )
        return template

    def list_devices(
        self, central_dns_suffix="azureiotcentral.com",
    ):
        devices = central_services.device.list_devices(
            cmd=self._cmd, app_id=self._app_id, token=self._token
        )
        for device in devices:
            self._devices[device["id"]] = device

        return self._devices

    def create_device(
        self,
        device_id,
        device_name=None,
        instance_of=None,
        simulated=False,
        central_dns_suffix="azureiotcentral.com",
    ):
        if not device_id:
            raise CLIError("Device id must be specified.")

        if device_id in self._devices:
            raise CLIError("Device already exists")

        # get or add to cache
        if device_id not in self._devices or not self._devices.get(device_id):
            self._devices[device_id] = central_services.device.create_device(
                cmd=self._cmd,
                token=self._token,
                app_id=self._app_id,
                device_id=device_id,
                device_name=device_name,
                instance_of=instance_of,
                simulated=simulated,
                central_dns_suffix=central_dns_suffix,
            )

        device = self._devices[device_id]
        if not device:
            raise CLIError("No device found with id: '{}'.".format(device_id))

        return device

    def delete_device(
        self, device_id, central_dns_suffix="azureiotcentral.com",
    ):
        if not device_id:
            raise CLIError("Device id must be specified.")

        # get or add to cache
        result = central_services.device.delete_device(
            cmd=self._cmd,
            token=self._token,
            app_id=self._app_id,
            device_id=device_id,
            central_dns_suffix=central_dns_suffix,
        )

        return result
