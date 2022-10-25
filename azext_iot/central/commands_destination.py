# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Union
from azure.cli.core.azclierror import RequiredArgumentMissingError
from azext_iot.central.common import DestinationType
from azext_iot.common import utility
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralDestinationProvider
from azext_iot.central.models.v2022_06_30_preview import (
    DestinationPreview,
    WebhookDestinationPreview,
    AdxDestinationPreview,
)
from azext_iot.central.common import API_VERSION_PREVIEW


def get_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_destination(
        destination_id=destination_id, central_dnx_suffix=central_dns_suffix
    )


def delete_destination(
    cmd,
    app_id: str,
    destination_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    provider.delete_destination(
        destination_id=destination_id, central_dnx_suffix=central_dns_suffix
    )


def list_destinations(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
) -> List[
    Union[
        DestinationPreview,
        WebhookDestinationPreview,
        AdxDestinationPreview,
    ]
]:
    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_destinations(central_dns_suffix=central_dns_suffix)


def add_destination(
    cmd,
    app_id: str,
    destination_id: str,
    type,
    display_name,
    url=None,
    cluster_url=None,
    database=None,
    table=None,
    header_customizations=None,
    authorization=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    destination = {
        "id": destination_id,
        "type": type,
        "displayName": display_name,
    }

    if type == DestinationType.Webhook.value:
        if not url:
            raise RequiredArgumentMissingError(
                "Parameter url is required when creating webhook destination."
            )
        destination.update({"url": url})
        if header_customizations is not None:
            destination.update(
                {
                    "headerCustomizations": utility.process_json_arg(
                        header_customizations, argument_name="header"
                    )
                }
            )

    if type == DestinationType.AzureDataExplorer.value:
        if not cluster_url:
            raise RequiredArgumentMissingError(
                "Parameter cluster-url is required when creating an azure data explorer destination."
            )
        if not database:
            raise RequiredArgumentMissingError(
                "Parameter database is required when creating an azure data explorer destination."
            )
        if not table:
            raise RequiredArgumentMissingError(
                "Parameter table is required when creating an azure data explorer destination."
            )
        destination.update(
            {"clusterUrl": cluster_url, "database": database, "table": table}
        )

    if authorization:
        destination.update(
            {
                "authorization": utility.process_json_arg(
                    authorization, argument_name="authorization"
                )
            }
        )
    else:
        if type != DestinationType.Webhook.value:
            raise RequiredArgumentMissingError(
                "Parameter authorization is required when creating a non-webhook destination."
            )

    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.add_destination(
        destination_id=destination_id,
        payload=destination,
        central_dnx_suffix=central_dns_suffix,
    )


def update_destination(
    cmd,
    app_id: str,
    destination_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
) -> Union[
    DestinationPreview, WebhookDestinationPreview, AdxDestinationPreview
]:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDestinationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.update_destination(
        destination_id=destination_id,
        payload=payload,
        central_dnx_suffix=central_dns_suffix,
    )
