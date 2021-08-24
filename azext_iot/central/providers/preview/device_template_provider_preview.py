# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List

from azure.cli.core.azclierror import RequiredArgumentMissingError, ResourceNotFoundError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central import models as central_models


class CentralDeviceTemplateProviderPreview:
    def __init__(self, cmd, app_id, token=None):
        """
        Provider for device_template APIs

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
        self._device_templates = {}

    def get_device_template(
        self, device_template_id, central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> central_models.TemplatePreview:
        # get or add to cache
        device_template = self._device_templates.get(device_template_id)
        if not device_template:
            device_template = central_services.device_template.get_device_template(
                cmd=self._cmd,
                app_id=self._app_id,
                device_template_id=device_template_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=ApiVersion.preview.value,
            )
            self._device_templates[device_template_id] = device_template

        if not device_template:
            raise ResourceNotFoundError(
                "No device template for device template with id: '{}'.".format(
                    device_template_id
                )
            )

        return device_template

    def list_device_templates(
        self, central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> List[central_models.TemplatePreview]:
        templates = central_services.device_template.list_device_templates(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.preview.value,
        )

        self._device_templates.update({template.id: template.raw_template for template in templates})

        return self._device_templates

    def map_device_templates(self, central_dns_suffix=CENTRAL_ENDPOINT,) -> dict:
        """
        Maps each template name to the corresponding template id
        """
        templates = central_services.device_template.list_device_templates(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            api_version=ApiVersion.preview.value,
        )
        return {template.name: template.id for template in templates}

    def create_device_template(
        self,
        device_template_id: str,
        payload: str,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> central_models.TemplatePreview:
        template = central_services.device_template.create_device_template(
            cmd=self._cmd,
            app_id=self._app_id,
            device_template_id=device_template_id,
            payload=payload,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.preview.value,
        )

        self._device_templates[template.id] = template

        return template

    def delete_device_template(
        self, device_template_id, central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> dict:
        if not device_template_id:
            raise RequiredArgumentMissingError("Device template id must be specified.")

        result = central_services.device_template.delete_device_template(
            cmd=self._cmd,
            token=self._token,
            app_id=self._app_id,
            device_template_id=device_template_id,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.preview.value,
        )

        # remove from cache
        # pop "miss" raises a KeyError if None is not provided
        self._device_templates.pop(device_template_id, None)

        return result
