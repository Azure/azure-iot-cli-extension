# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Union
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralDestinationProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.v1_1_preview import (
    DestinationV1_1_preview,
    WebhookDestinationV1_1_preview,
    AdxDestinationV1_1_preview,
)


def get_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[
    DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview
]:
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_dataExport_destination(
        destination_id=destination_id, central_dnx_suffix=central_dns_suffix
    )


def delete_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    provider.delete_dataExport_destination(
        destination_id=destination_id, central_dnx_suffix=central_dns_suffix
    )


def list_dataExport_destinations(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[
    Union[
        DestinationV1_1_preview,
        WebhookDestinationV1_1_preview,
        AdxDestinationV1_1_preview,
    ]
]:
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_dataExport_destinations(central_dns_suffix=central_dns_suffix)


def add_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[
    DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview
]:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.add_dataExport_destination(
        destination_id=destination_id,
        payload=payload,
        central_dnx_suffix=central_dns_suffix,
    )


def update_dataExport_destination(
    cmd,
    app_id: str,
    destination_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> Union[
    DestinationV1_1_preview, WebhookDestinationV1_1_preview, AdxDestinationV1_1_preview
]:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.update_dataExport_destination(
        destination_id=destination_id,
        payload=payload,
        central_dnx_suffix=central_dns_suffix,
    )
