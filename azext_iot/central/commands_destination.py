# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azure.cli.core.azclierror import RequiredArgumentMissingError
from azext_iot.central.common import DestinationType
from azext_iot.common import utility
from azext_iot.central.providers import CentralDestinationProvider
from azext_iot.sdk.central.preview_2022_06_30.models import Destination


def create_destination(
    cmd,
    app_id: str,
    destination_id: str,
    type: str,
    display_name: str,
    url=None,
    cluster_url=None,
    database=None,
    table=None,
    header_customizations=None,
    authorization=None,
) -> Destination:
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

    provider = CentralDestinationProvider(cmd=cmd, app_id=app_id)
    return provider.create(destination_id=destination_id, payload=destination)


def list_destinations(
    cmd,
    app_id: str,
) -> Destination:
    provider = CentralDestinationProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def get_destination(
    cmd,
    app_id: str,
    destination_id: str,
) -> Destination:
    provider = CentralDestinationProvider(cmd=cmd, app_id=app_id)
    return provider.get(destination_id=destination_id)


def update_destination(
    cmd,
    app_id: str,
    destination_id: str,
    content: str,
) -> Destination:
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDestinationProvider(cmd=cmd, app_id=app_id)
    return provider.update(destination_id=destination_id, payload=payload)


def delete_destination(
    cmd,
    app_id: str,
    destination_id: str,
):
    provider = CentralDestinationProvider(cmd=cmd, app_id=app_id)
    return provider.delete(destination_id=destination_id)
