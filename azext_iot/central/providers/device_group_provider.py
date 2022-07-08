# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Union
from azure.cli.core.azclierror import (
    RequiredArgumentMissingError,
    ResourceNotFoundError
)
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.preview import DeviceGroupPreview
from azext_iot.central.models.v1_1_preview import DeviceGroupV1_1_preview
from azext_iot.central.models.ga_2022_05_31 import DeviceGroupGa20220531

logger = get_logger(__name__)


class CentralDeviceGroupProvider:
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        """
        Provider for device groups APIs

        Args:
            cmd: command passed into az
            app_id: name of app (used for forming request URL)
            api_version: API version (appendend to request URL)
            token: (OPTIONAL) authorization token to fetch device details from IoTC.
                MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
                Useful in scenarios where user doesn't own the app
                therefore AAD token won't work, but a SAS token generated by owner will
        """
        self._cmd = cmd
        self._app_id = app_id
        self._token = token
        self._api_version = api_version
        self._device_groups = {}

    def list_device_groups(
        self, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> List[Union[DeviceGroupPreview, DeviceGroupV1_1_preview]]:
        device_groups = central_services.device_group.list_device_groups(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        self._device_groups.update(
            {device_group.id: device_group for device_group in device_groups}
        )

        return device_groups

    def get_device_group(
        self, device_group_id, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> Union[DeviceGroupPreview, DeviceGroupV1_1_preview, DeviceGroupGa20220531]:
        # get or add to cache
        device_group = self._device_groups.get(device_group_id)
        if not device_group:
            device_group = central_services.device_group.get_device_group(
                cmd=self._cmd,
                app_id=self._app_id,
                device_group_id=device_group_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=self._api_version,
            )
            # add to cache
            self._device_groups[device_group_id] = device_group

        if not device_group:
            raise ResourceNotFoundError(
                "No device group for device group with id: '{}'.".format(
                    device_group_id
                )
            )

        return device_group

    def create_device_group(
        self,
        device_group_id,
        display_name: str,
        filter: str,
        description: str = None,
        etag: str = None,
        organizations: List[str] = None,
        central_dns_suffix=CENTRAL_ENDPOINT
    ) -> Union[DeviceGroupPreview, DeviceGroupV1_1_preview, DeviceGroupGa20220531]:
        device_group = central_services.device_group.create_device_group(
            cmd=self._cmd,
            app_id=self._app_id,
            device_group_id=device_group_id,
            display_name=display_name,
            filter=filter,
            description=description,
            etag=etag,
            organizations=organizations,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        self._device_groups[device_group.id] = device_group

        return device_group

    def update_device_group(
        self,
        device_group_id,
        display_name: str = None,
        filter: str = None,
        description: str = None,
        organizations: List[str] = None,
        central_dns_suffix=CENTRAL_ENDPOINT
    ) -> Union[DeviceGroupPreview, DeviceGroupV1_1_preview, DeviceGroupGa20220531]:
        device_group = central_services.device_group.update_device_group(
            cmd=self._cmd,
            app_id=self._app_id,
            device_group_id=device_group_id,
            display_name=display_name,
            filter=filter,
            description=description,
            organizations=organizations,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        self._device_groups[device_group.id] = device_group

        return device_group

    def delete_device_group(
        self,
        device_group_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        if not device_group_id:
            raise RequiredArgumentMissingError("Device group id must be specified.")

        result = central_services.device_group.delete_device_group(
            cmd=self._cmd,
            token=self._token,
            app_id=self._app_id,
            device_group_id=device_group_id,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # remove from cache
        # pop "miss" raises a KeyError if None is not provided
        self._device_groups.pop(device_group_id, None)

        return result
