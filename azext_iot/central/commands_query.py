# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Command handling for query device telemetry or property data

from azext_iot.central import providers
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralQueryProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.v1_1_preview import QueryReponseV1_1_preview

def query_run(
    cmd,
    app_id: str,
    query_string: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> QueryReponseV1_1_preview:
    provider = CentralQueryProvider(
        cmd=cmd, app_id=app_id, query=query_string, api_version=api_version, token=token
    )

    return provider.query_run(central_dns_suffix=central_dns_suffix)