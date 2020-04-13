# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.services import central


class CentralDeviceProvider:
    _device_templates = {}
    _devices = {}

    def __init__(self):
        pass

    def get_device_template(
        self,
        cmd,
        device_id,
        app_name,
        token=None,
        central_dns_suffix="azureiotcentral.com",
    ):
        device = self.get_device(cmd, device_id, app_name, token, central_dns_suffix)
        device_template_urn = device["instanceOf"]

        if not device_template_urn:
            raise ValueError(
                "No device template urn found for device '{}'".format(device_id)
            )

        if (
            device_template_urn not in self._device_templates
            or not self._device_templates.get(device_template_urn)
        ):
            self._device_templates[
                device_template_urn
            ] = central.device_template.get_device_template(
                cmd, device_template_urn, app_name, token, central_dns_suffix
            )

        device_template = self._device_templates.get(device_template_urn)
        if not device_template:
            raise UnboundLocalError(
                "No device template for device with id: '{}'.".format(device_id)
            )

        return device_template

    def get_device(
        self,
        cmd,
        device_id,
        app_name,
        token=None,
        central_dns_suffix="azureiotcentral.com",
    ):
        if not device_id:
            raise ValueError("Device id must be specified.")

        if device_id not in self._devices or not self._devices.get(device_id):
            self._devices[device_id] = central.device.get_device(
                cmd, device_id, app_name, token, central_dns_suffix
            )

        device = self._devices.get(device_id)
        if not device:
            raise UnboundLocalError("No device found with id: '{}'.".format(device_id))

        return device
