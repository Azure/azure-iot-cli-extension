# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Union

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.central.providers.central_provider import CentralProvider
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.v1_1_preview import (
    DestinationV1_1_preview,
    WebhookDestinationV1_1_preview,
    AdxDestinationV1_1_preview,
)

logger = get_logger(__name__)


class CentralDestinationProvider(CentralProvider):
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        super().__init__(cmd, app_id, api_version, token=token)
        self._destinations = {}

    def list_dataExport_destinations(
        self, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> List[
        Union[
            DestinationV1_1_preview,
            WebhookDestinationV1_1_preview,
            AdxDestinationV1_1_preview,
        ]
    ]:
        destinations = central_services.destination.list_dataExport_destinations(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        for destination in destinations:
            self._destinations.update({destination["id"]: destination})

        return destinations

    def add_dataExport_destination(
        self, destination_id, payload, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[
        DestinationV1_1_preview,
        WebhookDestinationV1_1_preview,
        AdxDestinationV1_1_preview,
    ]:
        if destination_id in self._destinations:
            raise CLIError("Destination already exists")

        destination = central_services.destination.add_dataExport_destination(
            self._cmd,
            self._app_id,
            destination_id=destination_id,
            payload=payload,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dnx_suffix,
        )

        if not destination:
            raise CLIError(
                "Failed to create destination with id: '{}'.".format(destination_id)
            )

        # add to cache
        self._destinations[destination_id] = destination

        return destination

    def update_dataExport_destination(
        self, destination_id, payload, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[
        DestinationV1_1_preview,
        WebhookDestinationV1_1_preview,
        AdxDestinationV1_1_preview,
    ]:
        destination = central_services.destination.update_dataExport_destination(
            self._cmd,
            self._app_id,
            destination_id=destination_id,
            payload=payload,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dnx_suffix,
        )

        if not destination:
            raise CLIError(
                "Failed to create destination with id: '{}'.".format(destination_id)
            )

        # add to cache
        self._destinations[destination_id] = destination

        return destination

    def get_dataExport_destination(
        self, destination_id, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[
        DestinationV1_1_preview,
        WebhookDestinationV1_1_preview,
        AdxDestinationV1_1_preview,
    ]:
        # get or add to cache
        destination = self._destinations.get(destination_id)
        if not destination:
            destination = central_services.destination.get_dataExport_destination(
                cmd=self._cmd,
                app_id=self._app_id,
                token=self._token,
                api_version=self._api_version,
                destination_id=destination_id,
                central_dns_suffix=central_dnx_suffix,
            )

        if not destination:
            raise CLIError("No destination found with id: '{}'.".format(destination_id))
        else:
            self._destinations[destination_id] = destination

        return destination

    def delete_dataExport_destination(
        self, destination_id, central_dnx_suffix=CENTRAL_ENDPOINT
    ):
        central_services.destination.delete_dataExport_destination(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            api_version=self._api_version,
            destination_id=destination_id,
            central_dns_suffix=central_dnx_suffix,
        )

        self._destinations.pop(destination_id, None)
