# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List
from azext_iot.central.models.deviceGroupPreview import DeviceGroupPreview
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.enum import ApiVersion

logger = get_logger(__name__)


class CentralDeviceGroupProviderPreview:
    def __init__(self, cmd, app_id: str, token=None):
        """
        Provider for device groups APIs

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
        self._device_groups = {}

    def list_device_groups(self, central_dns_suffix=CENTRAL_ENDPOINT) -> List[DeviceGroupPreview]:
        device_groups = central_services.device_group.list_device_groups(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=ApiVersion.preview.value,
        )

        # add to cache
        self._device_groups.update({device_group.id: device_group for device_group in device_groups})

        return self._device_groups
