# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.central.models.enum import DeviceStatus


class DevicePreview:
    def __init__(self, device: dict):
        self.enabled = device.get("enabled")
        self.display_name = device.get("displayName")
        self.etag = device.get("etag")
        self.id = device.get("id")
        self.template = device.get("template")
        self.provisioned = device.get("provisioned")
        self.simulated = device.get("simulated")
        self.organizations = device.get("organizations")
        self.device_status = self._parse_device_status()
        pass

    def _parse_device_status(self) -> DeviceStatus:
        if not self.enabled:
            return DeviceStatus.blocked

        if not self.template:
            return DeviceStatus.unassociated

        if not self.provisioned:
            return DeviceStatus.registered

        return DeviceStatus.provisioned

    def get_registration_info(self) -> dict:
        registration_info = {
            "device_status": self.device_status.value,
            "display_name": self.display_name,
            "id": self.id,
            "simulated": self.simulated,
            "template": self.template,
        }

        return registration_info
