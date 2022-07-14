# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List

from azure.cli.core.azclierror import AzureResponseError, ClientRequestError, ResourceNotFoundError

from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.preview_2022_06_30.models import Destination


class CentralDestinationProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd, app_id)
        self.sdk = self.get_sdk_preview().destinations
        self._destinations = {}

    def create(
        self,
        destination_id: str,
        payload,
    ) -> Destination:
        if destination_id in self._destinations:
            raise ClientRequestError("Destination already exists")

        try:
            destination = self.sdk.create(
                destination_id=destination_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not destination:
            raise AzureResponseError(
                "Failed to create destination with id: '{}'.".format(destination_id)
            )

        # add to cache
        self._destinations[destination_id] = destination

        return destination

    def update(
        self,
        destination_id: str,
        payload,
    ) -> Destination:
        try:
            destination = self.sdk.update(
                destination_id=destination_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not destination:
            raise AzureResponseError(
                "Failed to update destination with id: '{}'.".format(destination_id)
            )

        # add to cache
        self._destinations[destination_id] = destination

        return destination

    def list(self) -> List[Destination]:
        try:
            destinations = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

        # add to cache
        for destination in destinations:
            self._destinations.update({destination["id"]: destination})

        return destinations

    def get(
        self,
        destination_id: str,
    ) -> Destination:
        # get from cache
        destination = self._destinations.get(destination_id)

        if not destination:
            try:
                destination = self.sdk.get(destination_id=destination_id)
            except CloudError as e:
                handle_service_exception(e)

        if not destination:
            raise ResourceNotFoundError("No destination found with id: '{}'.".format(destination_id))
        else:
            self._destinations[destination_id] = destination

        return destination

    def delete(
        self,
        destination_id: str,
    ):
        try:
            destination = self.sdk.remove(destination_id=destination_id)
        except CloudError as e:
            handle_service_exception(e)

        self._destinations.pop(destination_id, None)

        # Should be empty json
        return destination
