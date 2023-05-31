# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.iothub.providers.message_endpoint import EncodingFormat, EndpointType, MessageEndpoint
from knack.log import get_logger

logger = get_logger(__name__)


def message_endpoint_create_event_hub(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.EventHub.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_create_service_bus_queue(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusQueue.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_create_service_bus_topic(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusTopic.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_create_cosmos_db_container(
    cmd,
    hub_name: str,
    endpoint_name: str,
    container_name: str,
    database_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    primary_key: Optional[str] = None,
    secondary_key: Optional[str] = None,
    partition_key_name: Optional[str] = None,
    partition_key_template: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.CosmosDBContainer.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        container_name=container_name,
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
    container_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    encoding: str = EncodingFormat.AVRO.value,
    batch_frequency: int = 300,
    chunk_size_window: int = 300,
    file_name_format: str = '{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
    endpoint_uri: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.create(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.AzureStorageContainer.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        container_name=container_name,
        encoding=encoding,
        batch_frequency=batch_frequency,
        chunk_size_window=chunk_size_window,
        file_name_format=file_name_format,
        endpoint_uri=endpoint_uri,
        identity=identity
    )


def message_endpoint_update_event_hub(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.update(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.EventHub.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_update_service_bus_queue(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.update(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusQueue.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_update_service_bus_topic(
    cmd,
    hub_name: str,
    endpoint_name: str,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    endpoint_policy_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    entity_path: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.update(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.ServiceBusTopic.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        endpoint_policy_name=endpoint_policy_name,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        entity_path=entity_path,
        identity=identity
    )


def message_endpoint_update_cosmos_db_container(
    cmd,
    hub_name: str,
    endpoint_name: str,
    container_name: Optional[str] = None,
    database_name: Optional[str] = None,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    primary_key: Optional[str] = None,
    secondary_key: Optional[str] = None,
    partition_key_name: Optional[str] = None,
    partition_key_template: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.update(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.CosmosDBContainer.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        endpoint_uri=endpoint_uri,
        container_name=container_name,
        database_name=database_name,
        primary_key=primary_key,
        secondary_key=secondary_key,
        partition_key_name=partition_key_name,
        partition_key_template=partition_key_template,
        identity=identity
    )


def message_endpoint_update_storage_container(
    cmd,
    hub_name: str,
    endpoint_name: str,
    container_name: Optional[str] = None,
    endpoint_account_name: Optional[str] = None,
    endpoint_resource_group: Optional[str] = None,
    endpoint_subscription_id: Optional[str] = None,
    connection_string: Optional[str] = None,
    encoding: Optional[str] = None,
    batch_frequency: Optional[int] = None,
    chunk_size_window: Optional[int] = None,
    file_name_format: Optional[str] = None,
    endpoint_uri: Optional[str] = None,
    identity: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.update(
        endpoint_name=endpoint_name,
        endpoint_type=EndpointType.AzureStorageContainer.value,
        endpoint_account_name=endpoint_account_name,
        endpoint_resource_group=endpoint_resource_group,
        endpoint_subscription_id=endpoint_subscription_id,
        connection_string=connection_string,
        container_name=container_name,
        encoding=encoding,
        batch_frequency=batch_frequency,
        chunk_size_window=chunk_size_window,
        file_name_format=file_name_format,
        endpoint_uri=endpoint_uri,
        identity=identity
    )


def message_endpoint_show(
    cmd,
    hub_name: str,
    endpoint_name: str,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.show(endpoint_name=endpoint_name)


def message_endpoint_list(
    cmd,
    hub_name: str,
    endpoint_type: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.list(endpoint_type=endpoint_type)


def message_endpoint_delete(
    cmd,
    hub_name: str,
    endpoint_name: Optional[str] = None,
    endpoint_type: Optional[str] = None,
    force: bool = False,
    resource_group_name: Optional[str] = None,
):
    message_endpoint_provider = MessageEndpoint(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return message_endpoint_provider.delete(
        endpoint_name=endpoint_name, endpoint_type=endpoint_type, force=force
    )
