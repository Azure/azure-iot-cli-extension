# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Optional

from azext_iot.common import utility
from azext_iot.central.providers import CentralExportProvider
from azext_iot.sdk.central.preview_2022_06_30.models import Export


def get_export(
    cmd,
    app_id: str,
    export_id: str,
) -> Export:
    provider = CentralExportProvider(cmd=cmd, app_id=app_id)
    return provider.get(export_id=export_id)


def delete_export(
    cmd,
    app_id: str,
    export_id: str,
):
    provider = CentralExportProvider(cmd=cmd, app_id=app_id)
    provider.delete(export_id=export_id)


def list_exports(
    cmd,
    app_id: str,
) -> List[Export]:
    provider = CentralExportProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def create_export(
    cmd,
    app_id: str,
    export_id: str,
    source: str,
    destinations: List,
    display_name: str,
    enabled: Optional[bool] = True,
    filter: Optional[str] = None,
    enrichments: Optional[dict] = None,
) -> Export:
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

    provider = CentralExportProvider(cmd=cmd, app_id=app_id)
    return provider.create(
        export_id=export_id,
        payload=export,
    )


def update_export(
    cmd,
    app_id: str,
    export_id: str,
    content: str,
) -> Export:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralExportProvider(cmd=cmd, app_id=app_id)
    return provider.update(
        export_id=export_id,
        payload=payload,
    )
