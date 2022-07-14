# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Union
from azure.cli.core.azclierror import (
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import DeviceTemplate


class CentralDeviceTemplateProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().device_templates
        # For some places whhere needs Preview version device templates
        self.sdk_preview = self.get_sdk_preview().device_templates

        # Cache
        self._device_templates = {}

    def get(
        self,
        device_template_id,
    ) -> DeviceTemplate:
        # Get cache
        device_template = self._device_templates.get(device_template_id)

        if not device_template:
            try:
                device_template = self.sdk.get(device_template_id=device_template_id)
            except CloudError as e:
                handle_service_exception(e)

            self._device_templates[device_template_id] = device_template

        if not device_template:
            raise ResourceNotFoundError(
                "No device template for device template with id: '{}'.".format(
                    device_template_id
                )
            )

        return device_template

    def list(
        self,
        compact=False
    ) -> List[DeviceTemplate]:
        try:
            templates = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

        # If asked for compact, just keep reduced info
        if compact:
            for template in templates:
                self._device_templates.update(
                    {
                        template.id: {
                            "displayName": template.raw_template["displayName"],
                            template.get_id_key(): template.raw_template[
                                template.get_id_key()
                            ],
                            template.get_type_key(): template.raw_template[
                                template.get_type_key()
                            ],
                        }
                    }
                )
        else:
            self._device_templates.update(
                {template.id: template.raw_template for template in templates}
            )
        return list(self._device_templates.values())

    def map(self):
        """
        Maps each template name to the corresponding template id
        """
        try:
            templates = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)
        return {template.name: template.id for template in templates}

    def create(
        self,
        device_template_id: str,
        payload: str,
    ):
        try:
            template = self.sdk.create(
                device_template_id=device_template_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        self._device_templates[template.id] = template

        return template

    def update(
        self,
        device_template_id: str,
        payload: str,
    ):
        try:
            template = self.sdk.update(
                device_template_id=device_template_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        self._device_templates[template.id] = template

        return template

    def delete(
        self,
        device_template_id: str,
    ):
        if not device_template_id:
            raise RequiredArgumentMissingError("Device template id must be specified.")

        try:
            result = self.sdk.remove(device_template_id=device_template_id)
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache
        # pop "miss" raises a KeyError if None is not provided
        self._device_templates.pop(device_template_id, None)

        return result
