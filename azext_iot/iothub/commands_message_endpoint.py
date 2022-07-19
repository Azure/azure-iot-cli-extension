# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.iothub.providers.message_endpoint import EndpointType, MessageEndpoint
from knack.log import get_logger

logger = get_logger(__name__)


def message_endpoint_create_event_hub(
    cmd,
    endpoint_name: str,
    endpoint_type,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string=None,
    authentication_type=None,
    endpoint_uri=None,
    entity_path=None,
    identity=None,
    hub_name=None,
    resource_group_name=None,
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
    endpoint_name: str,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string=None,
    authentication_type=None,
    endpoint_uri=None,
    identity=None,
    hub_name=None,
    resource_group_name=None,
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
    endpoint_name: str,
    endpoint_type,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string=None,
    container_name=None,
    encoding=None,
    batch_frequency=300,
    chunk_size_window=300,
    file_name_format='{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
    authentication_type=None,
    endpoint_uri=None,
    entity_path=None,
    collection_name=None,
    database_name=None,
    primary_key=None,
    secondary_key=None,
    partition_key_name=None,
    partition_key_template=None,
    identity=None,
    hub_name=None,
    resource_group_name=None,
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
    endpoint_name: str,
    endpoint_type,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string=None,
    container_name=None,
    encoding=None,
    batch_frequency=300,
    chunk_size_window=300,
    file_name_format='{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
    authentication_type=None,
    endpoint_uri=None,
    entity_path=None,
    collection_name=None,
    database_name=None,
    primary_key=None,
    secondary_key=None,
    partition_key_name=None,
    partition_key_template=None,
    identity=None,
    hub_name=None,
    resource_group_name=None,
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
        container_name=container_name,
        encoding=encoding,
        batch_frequency=batch_frequency,
        chunk_size_window=chunk_size_window,
        file_name_format=file_name_format,
        authentication_type=authentication_type,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
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
    endpoint_name: str,
    endpoint_type,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string=None,
    container_name=None,
    encoding=None,
    batch_frequency=300,
    chunk_size_window=300,
    file_name_format='{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
    authentication_type=None,
    endpoint_uri=None,
    entity_path=None,
    collection_name=None,
    database_name=None,
    primary_key=None,
    secondary_key=None,
    partition_key_name=None,
    partition_key_template=None,
    identity=None,
    hub_name=None,
    resource_group_name=None,
):
    messaging_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=endpoint_type,
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
        entity_path=entity_path,
        collection_name=collection_name,
        database_name=database_name,
        primary_key=primary_key,
        secondary_key=secondary_key,
        partition_key_name=partition_key_name,
        partition_key_template=partition_key_template,
        identity=identity
    )
