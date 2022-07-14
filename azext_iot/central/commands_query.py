# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Command handling for query device telemetry or property data


from azext_iot.central.providers import CentralQueryProvider
from azext_iot.sdk.central.preview_2022_06_30.models import QueryResponse


def query_run(
    cmd,
    app_id: str,
    query_string: str,
) -> QueryResponse:
    provider = CentralQueryProvider(cmd=cmd, app_id=app_id, query=query_string)
    return provider.run()
