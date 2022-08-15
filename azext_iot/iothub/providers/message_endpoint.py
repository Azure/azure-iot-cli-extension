# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional
from knack.log import get_logger
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    RequiredArgumentMissingError,
    ResourceNotFoundError
)
from azext_iot.constants import USER_AGENT
from azext_iot.iothub.common import (
    SYSTEM_ASSIGNED_IDENTITY, AuthenticationType, EncodingFormat, EndpointType, IdentityType
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.common._azure import parse_cosmos_db_connection_string
from azure.cli.core.commands.client_factory import get_subscription_id
from azext_iot.sdk.iothub.controlplane.models import ManagedIdentity


logger = get_logger(__name__)


class MessageEndpoint(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
    ):
        self.cmd = cmd
        self.api_version = "2022-04-30-preview"
        self.client = self.get_client()
        self.discovery = IotHubDiscovery(cmd)
        self.discovery.track2 = True
        self.discovery.client = self.client.iot_hub_resource
        self.discovery.sub_id = get_subscription_id(self.cmd.cli_ctx)
        # Need to get the direct resource
        self.hub_resource = self.get_iot_hub_resource(hub_name, rg)

    def get_client(self):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azext_iot.sdk.iothub.controlplane import IotHubClient
        client = get_mgmt_service_client(self.cmd.cli_ctx, IotHubClient, api_version=self.api_version)

        # Adding IoT Ext User-Agent is done with best attempt.
        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client

    def get_iot_hub_resource(self, hub_name, rg):
        return self.discovery.find_resource(hub_name, rg)

    def create(
        self,
        endpoint_name: str,
        endpoint_type: str,
        endpoint_resource_group: Optional[str] = None,
        endpoint_subscription_id: Optional[str] = None,
        connection_string: Optional[str] = None,
        container_name: Optional[str] = None,
        encoding: Optional[str] = None,
        batch_frequency: int = 300,
        chunk_size_window: int = 300,
        file_name_format: str = '{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
        authentication_type: Optional[str] = None,
        endpoint_uri: Optional[str] = None,
        entity_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        database_name: Optional[str] = None,
        primary_key: Optional[str] = None,
        secondary_key: Optional[str] = None,
        partition_key_name: Optional[str] = None,
        partition_key_template: Optional[str] = None,
        identity: Optional[str] = None
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
            endpoint_identity = ManagedIdentity(
                user_assigned_identity=identity
            )
            # endpoint_identity = {"userAssignedIdentity" : identity}

        endpoints = self.hub_resource.properties.routing.endpoints

        if EndpointType.EventHub.value == endpoint_type.lower():
            endpoints.event_hubs.append({
                "connectionString": connection_string,
                "name": endpoint_name,
                "subscriptionId": endpoint_subscription_id,
                "resourceGroup": endpoint_resource_group,
                "authenticationType": authentication_type,
                "endpointUri": endpoint_uri,
                "entityPath": entity_path,
                "identity": endpoint_identity
            })
        elif EndpointType.ServiceBusQueue.value == endpoint_type.lower():
            # check connection string? Endpoint uri?
            endpoints.service_bus_queues.append({
                "connectionString": connection_string,
                "name": endpoint_name,
                "subscriptionId": endpoint_subscription_id,
                "resourceGroup": endpoint_resource_group,
                "authenticationType": authentication_type,
                "endpointUri": endpoint_uri,
                "entityPath": entity_path,
                "identity": endpoint_identity
            })
        elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
            endpoints.service_bus_topics.append({
                "connection_string": connection_string,
                "name": endpoint_name,
                "subscriptionId": endpoint_subscription_id,
                "resourceGroup": endpoint_resource_group,
                "authenticationType": authentication_type,
                "endpointUri": endpoint_uri,
                "entityPath": entity_path,
                "identity": endpoint_identity
            })
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
            if authentication_type != AuthenticationType.IdentityBased.value and not any([primary_key, secondary_key]):
                raise RequiredArgumentMissingError("Primary key via --primary-key, secondary key via --secondary-key, or connection string via --connection-string is required.")
            if primary_key and not secondary_key:
                secondary_key = primary_key
            if secondary_key and not primary_key:
                primary_key = secondary_key
            if not endpoint_uri:
                raise RequiredArgumentMissingError("Endpoint uri via --endpoint-uri or connection string via --connection-string is required.")
            if partition_key_name and not partition_key_template:
                partition_key_template = '{deviceid}-{YYYY}-{MM}'
            endpoints.cosmos_db_sql_collections.append({
                "name": endpoint_name,
                "databaseName": database_name,
                "collectionName": collection_name,
                "primaryKey": primary_key,
                "secondaryKey": secondary_key,
                "partitionKeyName": partition_key_name,
                "partitionKeyTemplate": partition_key_template,
                "subscriptionId": endpoint_subscription_id,
                "resourceGroup": endpoint_resource_group,
                "authenticationType": authentication_type,
                "endpointUri": endpoint_uri,
                "identity": endpoint_identity
            })
        elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
            if not container_name:
                raise RequiredArgumentMissingError("Container name is required.")
            endpoints.storage_containers.append({
                "connectionString": connection_string,
                "name": endpoint_name,
                "subscriptionId": endpoint_subscription_id,
                "resourceGroup": endpoint_resource_group,
                "containerName": container_name,
                "encoding": encoding.lower() if encoding else EncodingFormat.AVRO.value,
                "fileNameFormat": file_name_format,
                "batchFrequencyInSeconds": batch_frequency,
                "maxChunkSizeInBytes": (chunk_size_window * 1048576),
                "authenticationType": authentication_type,
                "endpointUri": endpoint_uri,
                "identity": endpoint_identity
            })

        return self.client.iot_hub_resource.begin_create_or_update(
            resource_group_name,
            self.hub_resource.name,
            self.hub_resource,
            if_match = self.hub_resource.etag
        )

    def show(self, endpoint_name: str):
        endpoints = self.hub_resource.properties.routing.endpoints
        endpoint_lists = [endpoints.event_hubs, endpoints.service_bus_queues, endpoints.service_bus_topics, endpoints.cosmos_db_sql_collections, endpoints.storage_containers]
        for endpoint_list in endpoint_lists:
            for endpoint in endpoint_list:
                if endpoint.name.lower() == endpoint_name.lower():
                    return endpoint
        raise ResourceNotFoundError("No endpoint found.")

    def list(self, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource.properties.routing.endpoints
        if not endpoint_type:
            return endpoints
        endpoint_type = endpoint_type.lower()
        if EndpointType.EventHub.value == endpoint_type:
            return endpoints.event_hubs
        if EndpointType.ServiceBusQueue.value == endpoint_type:
            return endpoints.service_bus_queues
        if EndpointType.ServiceBusTopic.value == endpoint_type:
            return endpoints.service_bus_topics
        if EndpointType.CosmosDBCollection.value == endpoint_type:
            return endpoints.cosmos_db_sql_collections
        if EndpointType.AzureStorageContainer.value == endpoint_type:
            return endpoints.storage_containers

    def delete(self, endpoint_name: Optional[str] = None, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource.properties.routing.endpoints
        if endpoint_type:
            endpoint_type = endpoint_type.lower()
        if endpoint_name:
            endpoint_name = endpoint_name.lower()

            if not endpoint_type or EndpointType.EventHub.value == endpoint_type:
                endpoints.event_hubs = [e for e in endpoints.event_hubs if e.name.lower() != endpoint_name]
            elif not endpoint_type or EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints.service_bus_queues = [e for e in endpoints.service_bus_queues if e.name.lower() != endpoint_name]
            elif not endpoint_type or EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints.service_bus_topics = [e for e in endpoints.service_bus_topics if e.name.lower() != endpoint_name]
            elif not endpoint_type or EndpointType.CosmosDBCollection.value == endpoint_type:
                endpoints.cosmos_db_sql_collections = [e for e in endpoints.cosmos_db_sql_collections if e.name.lower() != endpoint_name]
            elif not endpoint_type or EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints.storage_containers = [e for e in endpoints.storage_containers if e.name.lower() != endpoint_name]

        elif endpoint_type:
            if EndpointType.EventHub.value == endpoint_type:
                endpoints.event_hubs = []
            elif EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints.service_bus_queues = []
            elif EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints.service_bus_topics = []
            elif EndpointType.CosmosDBCollection.value == endpoint_type:
                endpoints.cosmos_db_sql_collections = []
            elif EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints.storage_containers = []

        if not endpoint_type and not endpoint_name:
            endpoints.event_hubs = []
            endpoints.service_bus_queues = []
            endpoints.service_bus_topics = []
            endpoints.cosmos_db_sql_collections = []
            endpoints.storage_containers = []

        # prob not necessary cause of pointers
        # self.hub_resource.properties.routing.endpoints = endpoints
        return self.client.iot_hub_resource.begin_create_or_update(
            self.hub_resource.additional_properties['resourcegroup'],
            self.hub_resource.name,
            self.hub_resource,
            if_match = self.hub_resource.etag
        )