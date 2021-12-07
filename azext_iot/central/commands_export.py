# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Union
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralExportProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.v1_1_preview import ExportV1_1_preview


def get_export(
    cmd,
    app_id: str,
    export_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[dict, ExportV1_1_preview]:
    provider = CentralExportProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_export(
        export_id=export_id, central_dnx_suffix=central_dns_suffix
    )


def delete_export(
    cmd,
    app_id: str,
    export_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralExportProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    provider.delete_export(export_id=export_id, central_dnx_suffix=central_dns_suffix)


def list_exports(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[Union[dict, ExportV1_1_preview]]:
    provider = CentralExportProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_exports(central_dns_suffix=central_dns_suffix)


def add_export(
    cmd,
    app_id: str,
    export_id: str,
    source,
    destinations,
    display_name,
    enabled=True,
    filter=None,
    enrichments=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[dict, ExportV1_1_preview]:
    export = {
        "id": export_id,
        "source": source,
        "displayName": display_name,
        "enabled": bool(enabled),
    }

    if filter is not None:
        export.update({"filter": filter})

    if enrichments is not None:
        export.update(
            {
                "enrichments": utility.process_json_arg(
                    content=enrichments, argument_name="enrichments"
                )
            }
        )

    if destinations is not None:
        export.update(
            {
                "destinations": utility.process_json_arg(
                    content=destinations, argument_name="destinations"
                )
            }
        )

    provider = CentralExportProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.add_export(
        export_id=export_id,
        payload=export,
        central_dnx_suffix=central_dns_suffix,
    )


def update_export(
    cmd,
    app_id: str,
    export_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[dict, ExportV1_1_preview]:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralExportProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.update_export(
        export_id=export_id,
        payload=payload,
        central_dnx_suffix=central_dns_suffix,
    )
