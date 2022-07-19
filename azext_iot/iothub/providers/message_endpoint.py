# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum
from typing import Dict, Optional
from knack.log import get_logger
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    RequiredArgumentMissingError,
    ResourceNotFoundError
)
from azext_iot._factory import SdkResolver
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.sdk.iothub.controlplane.models import (
    ManagedIdentity,
    RoutingEventHubProperties,
    RoutingServiceBusQueueEndpointProperties,
    RoutingServiceBusTopicEndpointProperties,
    RoutingCosmosDBSqlApiProperties,
    RoutingStorageContainerProperties
)
from azext_iot.common._azure import parse_cosmos_db_connection_string


logger = get_logger(__name__)


class AuthenticationType(Enum):
    """
    Type of the Authentication for the routing endpoint.
    """
    KeyBased = 'keyBased'
    IdentityBased = 'identityBased'


class EndpointType(Enum):
    """
    Type of the routing endpoint.
    """
    EventHub = 'eventhub'
    ServiceBusQueue = 'servicebusqueue'
    ServiceBusTopic = 'servicebustopic'
    AzureStorageContainer = 'azurestoragecontainer'
    CosmosDBCollection = 'cosmosdbcollection'


class IdentityType(Enum):
    """
    Type of managed identity for the IoT Hub.
    """
    system_assigned = "SystemAssigned"
    user_assigned = "UserAssigned"
    system_assigned_user_assigned = "SystemAssigned, UserAssigned"
    none = "None"

class EncodingFormat(Enum):
    """
    Type of the encoding format for the container.
    """
    JSON = 'json'
    AVRO = 'avro'

SYSTEM_ASSIGNED_IDENTITY = '[system]'


class MessageEndpoint(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
    ):
        self.cmd = cmd
        self.discovery = IotHubDiscovery(cmd)
        # Need to get the direct resource
        self.hub_resource = self.get_iot_hub_resource(hub_name, rg)
        self.client = self.get_client()

    def get_client(self):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azext_iot.sdk.iothub.controlplane import IotHubClient
        return get_mgmt_service_client(self.cmd.cli_ctx, IotHubClient)

    def create(
        self,
        endpoint_name: str,
        endpoint_type: str,
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
        identity=None
    ):
        resource_group_name = self.hub_resource.additional_properties['resourcegroup']
        if not endpoint_resource_group:
            endpoint_resource_group = resource_group_name
        if not endpoint_subscription_id:
            endpoint_subscription_id = self.hub_resource.additional_properties['subscriptionid']

        endpoint_identity = None
        if identity and authentication_type != AuthenticationType.IdentityBased.value:
            raise ArgumentUsageError("In order to use an identity for authentication, you must select --auth-type as 'identityBased'")
        elif identity and identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY]:
            endpoint_identity = ManagedIdentity(user_assigned_identity=identity)

        if EndpointType.EventHub.value == endpoint_type.lower():
            # check connection string? endpoint uri? Entity path?
            self.hub_resource.properties.routing.endpoints.event_hubs.append(
                RoutingEventHubProperties(
                    connection_string=connection_string,
                    name=endpoint_name,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    entity_path=entity_path,
                    identity=endpoint_identity
                )
            )
        elif EndpointType.ServiceBusQueue.value == endpoint_type.lower():
            # check connection string? Endpoint uri?
            self.hub_resource.properties.routing.endpoints.service_bus_queues.append(
                RoutingServiceBusQueueEndpointProperties(
                    connection_string=connection_string,
                    name=endpoint_name,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    identity=endpoint_identity
                )
            )
        elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
            self.hub_resource.properties.routing.endpoints.service_bus_topics.append(
                RoutingServiceBusTopicEndpointProperties(
                    connection_string=connection_string,
                    name=endpoint_name,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    entity_path=entity_path,
                    identity=endpoint_identity
                )
            )
        elif EndpointType.CosmosDBCollection.value == endpoint_type.lower():
            if connection_string:
                # parse out key from connection string
                if not primary_key and not secondary_key:
                    parsed_cs = parse_cosmos_db_connection_string(connection_string)
                    primary_key = parsed_cs["AccountKey"]
                    secondary_key = parsed_cs["AccountKey"]
                # parse out endpoint uri from connection string
                if not endpoint_uri:
                    endpoint_uri = parsed_cs["AccountEndpoint"]
            if not primary_key and not secondary_key:
                raise RequiredArgumentMissingError("Primary key via --primary-key, secondary key via --secondary-key, or connection string via --connection-string is required.")
            if primary_key and not secondary_key:
                secondary_key = primary_key
            if secondary_key and not primary_key:
                primary_key = secondary_key
            if not endpoint_uri:
                raise RequiredArgumentMissingError("Endpoint uri via --endpoint-uri or connection string via --connection-string is required.")
            if not database_name:
                raise RequiredArgumentMissingError("Database name via --database-name is required.")
            if not collection_name:
                raise RequiredArgumentMissingError("Collection name via --collection-name is required.")
            if partition_key_name and not partition_key_template:
                partition_key_template = '{deviceid}-{YYYY}-{MM}'
            print(RoutingCosmosDBSqlApiProperties(
                    name=endpoint_name,
                    database_name=database_name,
                    collection_name=collection_name,
                    primary_key=primary_key,
                    secondary_key=secondary_key,
                    partition_key_name=partition_key_name,
                    partition_key_template=partition_key_template,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    entity_path=entity_path,
                    identity=endpoint_identity
                ).__dict__)
            self.hub_resource.properties.routing.endpoints.cosmos_db_sql_collections.append(
                RoutingCosmosDBSqlApiProperties(
                    name=endpoint_name,
                    database_name=database_name,
                    collection_name=collection_name,
                    primary_key=primary_key,
                    secondary_key=secondary_key,
                    partition_key_name=partition_key_name,
                    partition_key_template=partition_key_template,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    entity_path=entity_path,
                    identity=endpoint_identity
                )
            )
        elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
            if not container_name:
                raise RequiredArgumentMissingError("Container name is required.")
            self.hub_resource.properties.routing.endpoints.storage_containers.append(
                RoutingStorageContainerProperties(
                    connection_string=connection_string,
                    name=endpoint_name,
                    subscription_id=endpoint_subscription_id,
                    resource_group=endpoint_resource_group,
                    container_name=container_name,
                    encoding=encoding.lower() if encoding else EncodingFormat.AVRO.value,
                    file_name_format=file_name_format,
                    batch_frequency_in_seconds=batch_frequency,
                    max_chunk_size_in_bytes=(chunk_size_window * 1048576),
                    authentication_type=authentication_type,
                    endpoint_uri=endpoint_uri,
                    identity=endpoint_identity
                )
            )

        return self.client.iot_hub_resource.create_or_update(
            resource_group_name,
            self.hub_resource.name,
            self.hub_resource,
            {'IF-MATCH': self.hub_resource.etag}
        )

    def show(self, endpoint_name: str):
        for endpoint_list in self.hub_resource.properties.routing.endpoints:
            for endpoint in endpoint_list:
                if endpoint.name.lower() == endpoint_name.lower():
                    return endpoint
        raise ResourceNotFoundError("No endpoint found.")

    def list(self, endpoint_type: Optional[str] = None):
        if not endpoint_type:
            return self.hub_resource.properties.routing.endpoints
        if EndpointType.EventHub.value == endpoint_type.lower():
            return self.hub_resource.properties.routing.endpoints.event_hubs
        if EndpointType.ServiceBusQueue.value == endpoint_type.lower():
            return self.hub_resource.properties.routing.endpoints.service_bus_queues
        if EndpointType.ServiceBusTopic.value == endpoint_type.lower():
            return self.hub_resource.properties.routing.endpoints.service_bus_topics
        if EndpointType.AzureStorageContainer.value == endpoint_type.lower():
            return self.hub_resource.properties.routing.endpoints.storage_containers

    def delete(self, endpoint_name: Optional[str] = None, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource.properties.routing.endpoints
        if endpoint_type:
            if EndpointType.ServiceBusQueue.value == endpoint_type.lower():
                endpoints.service_bus_queues = []
            elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
                endpoints.service_bus_topics = []
            elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
                endpoints.storage_containers = []
            elif EndpointType.EventHub.value == endpoint_type.lower():
                endpoints.event_hubs = []

        if endpoint_name:
            if any(e.name.lower() == endpoint_name.lower() for e in endpoints.service_bus_queues):
                sbq_endpoints = [e for e in endpoints.service_bus_queues if e.name.lower() != endpoint_name.lower()]
                endpoints.service_bus_queues = sbq_endpoints
            elif any(e.name.lower() == endpoint_name.lower() for e in endpoints.service_bus_topics):
                sbt_endpoints = [e for e in endpoints.service_bus_topics if e.name.lower() != endpoint_name.lower()]
                endpoints.service_bus_topics = sbt_endpoints
            elif any(e.name.lower() == endpoint_name.lower() for e in endpoints.storage_containers):
                sc_endpoints = [e for e in endpoints.storage_containers if e.name.lower() != endpoint_name.lower()]
                endpoints.storage_containers = sc_endpoints
            elif any(e.name.lower() == endpoint_name.lower() for e in endpoints.event_hubs):
                eh_endpoints = [e for e in endpoints.event_hubs if e.name.lower() != endpoint_name.lower()]
                endpoints.event_hubs = eh_endpoints

        if not endpoint_type and not endpoint_name:
            endpoints.service_bus_queues = []
            endpoints.service_bus_topics = []
            endpoints.storage_containers = []
            endpoints.event_hubs = []

        self.hub_resource.properties.routing.endpoints = endpoints
        return self.client.iot_hub_resource.create_or_update(
            self.hub_resource.additional_properties['resourcegroup'],
            self.hub_resource.name,
            self.hub_resource,
            {'IF-MATCH': self.hub_resource.etag}
        )