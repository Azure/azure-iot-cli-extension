# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Union

from knack.log import get_logger
from knack.util import CLIError

from azext_iot.central.providers.central_provider import CentralProvider
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.v1_1_preview import ExportV1_1_preview

logger = get_logger(__name__)


class CentralExportProvider(CentralProvider):
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        super().__init__(cmd, app_id, api_version, token=token)
        self._exports = {}

    def list_exports(
        self, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> List[Union[dict, ExportV1_1_preview]]:
        exports = central_services.export.list_exports(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        for export in exports:
            self._exports.update({export["id"]: export})

        return exports

    def add_export(
        self, export_id, payload, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[dict, ExportV1_1_preview]:
        if export_id in self._exports:
            raise CLIError("Destination already exists")

        export = central_services.export.add_export(
            self._cmd,
            self._app_id,
            export_id=export_id,
            payload=payload,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dnx_suffix,
        )

        if not export:
            raise CLIError("Failed to create export with id: '{}'.".format(export_id))

        # add to cache
        self._exports[export["id"]] = export

        return export

    def update_export(
        self, export_id, payload, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[dict, ExportV1_1_preview]:
        export = central_services.export.update_export(
            self._cmd,
            self._app_id,
            export_id=export_id,
            payload=payload,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dnx_suffix,
        )

        if not export:
            raise CLIError("Failed to create export with id: '{}'.".format(export_id))

        # add to cache
        self._exports[export_id] = export

        return export

    def get_export(
        self, export_id, central_dnx_suffix=CENTRAL_ENDPOINT
    ) -> Union[dict, ExportV1_1_preview]:
        # get or add to cache
        export = self._exports.get(export_id)
        if not export:
            export = central_services.export.get_export(
                cmd=self._cmd,
                app_id=self._app_id,
                token=self._token,
                api_version=self._api_version,
                export_id=export_id,
                central_dns_suffix=central_dnx_suffix,
            )

        if not export:
            raise CLIError("No export found with id: '{}'.".format(export_id))
        else:
            self._exports[export_id] = export

        return export

    def delete_export(self, export_id, central_dnx_suffix=CENTRAL_ENDPOINT):
        central_services.export.delete_export(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            api_version=self._api_version,
            export_id=export_id,
            central_dns_suffix=central_dnx_suffix,
        )

        self._exports.pop(export_id, None)
