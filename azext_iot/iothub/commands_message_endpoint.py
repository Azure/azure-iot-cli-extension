# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.iothub.providers.message_endpoint import EncodingFormat, EndpointType, MessageEndpoint
from knack.log import get_logger

logger = get_logger(__name__)


# TODO: fix typing for auth type
def message_endpoint_create_event_hub(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    authentication_type: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.EventHub.value,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_create_service_bus_queue(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    authentication_type: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusQueue.value,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        identity=identity
    )


def message_endpoint_create_service_bus_topic(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    authentication_type: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusTopic.value,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_create_cosmos_db_collection(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    authentication_type: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    collection_name: Optional[str] = None,
    database_name: Optional[str] = None,
    primary_key: Optional[str] = None,
    secondary_key: Optional[str] = None,
    partition_key_name: Optional[str] = None,
    partition_key_template: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.CosmosDBCollection.value,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        collection_name=collection_name,
        database_name=database_name,
        primary_key=primary_key,
        secondary_key=secondary_key,
        partition_key_name=partition_key_name,
        partition_key_template=partition_key_template,
        identity=identity
    )


def message_endpoint_create_storage_container(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
    encoding: str = EncodingFormat.AVRO.value,
    batch_frequency: int = 300,
    chunk_size_window: int = 300,
    file_name_format: str = '{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
    authentication_type: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.AzureStorageContainer.value,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        container_name=container_name,
        encoding=encoding,
        batch_frequency=batch_frequency,
        chunk_size_window=chunk_size_window,
        file_name_format=file_name_format,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        identity=identity
    )

def message_endpoint_show(
    cmd,
    hub_name: str,
    endpoint_name: str,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.show(endpoint_name=endpoint_name)


def message_endpoint_list(
    cmd,
    hub_name: str,
    endpoint_type: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.list(endpoint_type=endpoint_type)


def message_endpoint_delete(
    cmd,
    hub_name: str,
    endpoint_name: Optional[str] = None,
    endpoint_type: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.delete(endpoint_name=endpoint_name, endpoint_type=endpoint_type)