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
from azext_iot.sdk.central.preview_2022_06_30.models import Export


class CentralExportProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk_preview = self.get_sdk_preview().exports

        # Cache
        self._exports = {}

    def list(self) -> List[Export]:
        try:
            exports = self.sdk_preview.list()
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        for export in exports:
            self._exports.update({export["id"]: export})

        return exports

    def create(
        self,
        export_id: str,
        payload: dict
    ) -> Export:
        if export_id in self._exports:
            raise ClientRequestError("Destination already exists")

        try:
            export = self.sdk_preview.create(
                export_id=export_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not export:
            raise AzureResponseError("Failed to create export with id: '{}'.".format(export_id))

        # Update cache
        self._exports[export["id"]] = export

        return export

    def update(
        self,
        export_id: str,
        payload: dict,
    ) -> Export:
        try:
            export = self.sdk_preview.update(
                export_id=export_id,
                body=payload,
            )
        except CloudError as e:
            handle_service_exception(e)

        if not export:
            raise AzureResponseError("Failed to create export with id: '{}'.".format(export_id))

        # Update cache
        self._exports[export_id] = export

        return export

    def get(
        self,
        export_id: str,
    ) -> Export:
        # Try cache
        export = self._exports.get(export_id)

        if not export:
            try:
                export = self.sdk_preview.get(export_id=export_id)
            except CloudError as e:
                handle_service_exception(e)

        if not export:
            raise ResourceNotFoundError("No export found with id: '{}'.".format(export_id))
        else:
            self._exports[export_id] = export

        return export

    def delete(
        self,
        export_id: str
    ):
        try:
            result = self.sdk_preview.remove(export_id=export_id)
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache
        self._exports.pop(export_id, None)

        return result
