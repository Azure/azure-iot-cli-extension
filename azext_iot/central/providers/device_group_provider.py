# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Optional

from azure.cli.core.azclierror import (
    RequiredArgumentMissingError,
    ResourceNotFoundError
)

from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import DeviceGroup


class CentralDeviceGroupProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().device_groups

        # Cache
        self._device_groups = {}

    def create(
        self,
        device_group_id,
        display_name: str,
        filter: str,
        description: Optional[str] = None,
        etag: Optional[str] = None,
        organizations: Optional[List[str]] = None,
    ) -> DeviceGroup:
        payload = {
            "display_name": display_name,
            "filter": filter,
            "description": description,
            "etag": etag,
            "organizations": organizations
        }

        try:
            device_group = self.sdk.create(
                device_group_id=device_group_id,
                body=payload
            )
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._device_groups[device_group.id] = device_group
        return device_group

    def list(self) -> List[DeviceGroup]:
        try:
            device_groups = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

        # Update cache     
        self._device_groups.update({device_group.id: device_group for device_group in device_groups})

        return device_groups

    def get(
        self,
        device_group_id
    ) -> DeviceGroup:
        # Try cache
        device_group = self._device_groups.get(device_group_id)

        if not device_group:
            try:
                device_group = self.sdk.get(device_group_id=device_group_id)
            except CloudError as e:
                handle_service_exception(e)

            # Update cache
            self._device_groups[device_group_id] = device_group

        if not device_group:
            raise ResourceNotFoundError(
                "No device group for device group with id: '{}'.".format(
                    device_group_id
                )
            )

        return device_group

    def update(
        self,
        device_group_id,
        display_name: Optional[str] = None,
        filter: Optional[str] = None,
        description: Optional[str] = None,
        organizations: Optional[List[str]] = None,
    ) -> DeviceGroup:
        payload = {
            "display_name": display_name,
            "filter": filter,
            "description": description,
            "organizations": organizations
        }

        try:
            device_group = self.sdk.update(
                device_group_id=device_group_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        self._device_groups[device_group.id] = device_group
        return device_group

    def delete(
        self,
        device_group_id,
    ):
        if not device_group_id:
            raise RequiredArgumentMissingError("Device group id must be specified.")

        try:
            result = self.sdk.remove(device_group_id=device_group_id)
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache
        self._device_groups.pop(device_group_id, None)
        return result
