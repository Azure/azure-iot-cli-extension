# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from knack.log import get_logger
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    InvalidArgumentValueError
)
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.iothub.common import (
    BYTES_PER_MEGABYTE, INVALID_CLI_CORE_FOR_COSMOS, SYSTEM_ASSIGNED_IDENTITY, AuthenticationType, EncodingFormat, EndpointType
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common._azure import parse_cosmos_db_connection_string
from azure.mgmt.iothub.models import ManagedIdentity


logger = get_logger(__name__)


class MessageEndpoint(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(MessageEndpoint, self).__init__(cmd, hub_name, rg, dataplane=False)
        self.support_cosmos = hasattr(self.hub_resource.properties.routing.endpoints, "cosmos_db_sql_collections")
        self.cli = EmbeddedCLI(cli_ctx=self.cmd.cli_ctx)

    def create(
        self,
        endpoint_name: str,
        endpoint_type: str,
        endpoint_account_name: Optional[str] = None,
        endpoint_resource_group: Optional[str] = None,
        endpoint_subscription_id: Optional[str] = None,
        endpoint_policy_name: Optional[str] = None,
        connection_string: Optional[str] = None,
        container_name: Optional[str] = None,
        encoding: Optional[str] = None,
        batch_frequency: int = 300,
        chunk_size_window: int = 300,
        file_name_format: str = '{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
        endpoint_uri: Optional[str] = None,
        entity_path: Optional[str] = None,
        database_name: Optional[str] = None,
        primary_key: Optional[str] = None,
        secondary_key: Optional[str] = None,
        partition_key_name: Optional[str] = None,
        partition_key_template: Optional[str] = None,
        identity: Optional[str] = None
    ):
        if not endpoint_resource_group:
            endpoint_resource_group = self.hub_resource.additional_properties["resourcegroup"]
        if not endpoint_subscription_id:
            endpoint_subscription_id = self.hub_resource.additional_properties['subscriptionid']

        authentication_type = AuthenticationType.KeyBased.value
        endpoint_identity = None
        if identity:
            authentication_type = AuthenticationType.IdentityBased.value
            if identity != SYSTEM_ASSIGNED_IDENTITY:
                endpoint_identity = ManagedIdentity(
                    user_assigned_identity=identity
                )
        elif not connection_string:
            # check for args to get the connection string
            error_msg = "Please provide a connection string '--connection-string/-c'"
            if not (
                endpoint_account_name and entity_path and endpoint_policy_name
            ) and endpoint_type.lower() in [
                EndpointType.EventHub.value, EndpointType.ServiceBusQueue.value, EndpointType.ServiceBusTopic.value
            ]:
                raise ArgumentUsageError(
                    error_msg + " or endpoint namespace '--endpoint-namespace', endpoint "
                    "entity path '--entity-path', and policy name '--policy-name'."
                )
            elif not endpoint_account_name and endpoint_type.lower() in [
                EndpointType.AzureStorageContainer.value, EndpointType.CosmosDBContainer.value
            ]:
                raise ArgumentUsageError(
                    error_msg + " or endpoint account '--endpoint-account'."
                )

        # Base props shared among all endpoints
        new_endpoint = {
            "connectionString": connection_string,
            "name": endpoint_name,
            "subscriptionId": endpoint_subscription_id,
            "resourceGroup": endpoint_resource_group,
            "authenticationType": authentication_type,
            "endpointUri": endpoint_uri,
            "identity": endpoint_identity
        }
        fetch_connection_string = identity is None and not connection_string

        endpoints = self.hub_resource.properties.routing.endpoints
        if EndpointType.EventHub.value == endpoint_type.lower():
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_eventhub_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    eventhub_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            new_endpoint["entityPath"] = entity_path
            endpoints.event_hubs.append(new_endpoint)
        elif EndpointType.ServiceBusQueue.value == endpoint_type.lower():
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_servicebus_queue_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    queue_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            new_endpoint["entityPath"] = entity_path
            endpoints.service_bus_queues.append(new_endpoint)
        elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_servicebus_topic_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    topic_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            new_endpoint["entityPath"] = entity_path
            endpoints.service_bus_topics.append(new_endpoint)
        elif EndpointType.CosmosDBContainer.value == endpoint_type.lower():
            if fetch_connection_string:
                # try to get connection string
                new_endpoint["connectionString"] = get_cosmos_db_cstring(
                    cmd=self.cli,
                    account_name=endpoint_account_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            if connection_string:
                # parse out key from connection string
                if not primary_key and not secondary_key:
                    parsed_cs = parse_cosmos_db_connection_string(connection_string)
                    primary_key = parsed_cs["AccountKey"]
                    secondary_key = parsed_cs["AccountKey"]
                # parse out endpoint uri from connection string
                if not endpoint_uri:
                    new_endpoint["endpointUri"] = parsed_cs["AccountEndpoint"]
            if authentication_type != AuthenticationType.IdentityBased.value and not any([primary_key, secondary_key]):
                raise RequiredArgumentMissingError(
                    "Primary key via --primary-key, secondary key via --secondary-key, or connection string via "
                    "--connection-string is required."
                )
            if primary_key and not secondary_key:
                secondary_key = primary_key
            if secondary_key and not primary_key:
                primary_key = secondary_key
            if not new_endpoint["endpointUri"]:
                raise RequiredArgumentMissingError(
                    "Endpoint uri via --endpoint-uri or connection string via --connection-string is required."
                )
            if partition_key_name and not partition_key_template:
                partition_key_template = '{deviceid}-{YYYY}-{MM}'
            del new_endpoint["connectionString"]
            new_endpoint.update({
                "databaseName": database_name,
                "collectionName": container_name,
                "primaryKey": primary_key,
                "secondaryKey": secondary_key,
                "partitionKeyName": partition_key_name,
                "partitionKeyTemplate": partition_key_template,
            })
            endpoints.cosmos_db_sql_collections.append(new_endpoint)
        elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
            if fetch_connection_string:
                # try to get connection string
                new_endpoint["connectionString"] = get_storage_cstring(
                    cmd=self.cli,
                    account_name=endpoint_account_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            if not container_name:
                raise RequiredArgumentMissingError("Container name is required.")
            new_endpoint.update({
                "containerName": container_name,
                "encoding": encoding.lower() if encoding else EncodingFormat.AVRO.value,
                "fileNameFormat": file_name_format,
                "batchFrequencyInSeconds": batch_frequency,
                "maxChunkSizeInBytes": (chunk_size_window * BYTES_PER_MEGABYTE),
            })
            endpoints.storage_containers.append(new_endpoint)

        return self.discovery.client.begin_create_or_update(
            self.hub_resource.additional_properties["resourcegroup"],
            self.hub_resource.name,
            self.hub_resource,
            if_match=self.hub_resource.etag
        )

    def show(self, endpoint_name: str):
        endpoints = self.hub_resource.properties.routing.endpoints
        endpoint_lists = [
            endpoints.event_hubs,
            endpoints.service_bus_queues,
            endpoints.service_bus_topics,
            endpoints.storage_containers
        ]
        if self.support_cosmos:
            endpoint_lists.append(endpoints.cosmos_db_sql_collections)
        for endpoint_list in endpoint_lists:
            for endpoint in endpoint_list:
                if endpoint.name.lower() == endpoint_name.lower():
                    return endpoint
        raise ResourceNotFoundError(f"Endpoint {endpoint_name} not found in IoT Hub {self.hub_resource.name}.")

    def list(self, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource.properties.routing.endpoints
        if not endpoint_type:
            return endpoints
        endpoint_type = endpoint_type.lower()
        if EndpointType.EventHub.value == endpoint_type:
            return endpoints.event_hubs
        elif EndpointType.ServiceBusQueue.value == endpoint_type:
            return endpoints.service_bus_queues
        elif EndpointType.ServiceBusTopic.value == endpoint_type:
            return endpoints.service_bus_topics
        elif EndpointType.CosmosDBContainer.value == endpoint_type and self.support_cosmos:
            return endpoints.cosmos_db_sql_collections
        elif EndpointType.CosmosDBContainer.value == endpoint_type:
            raise InvalidArgumentValueError(INVALID_CLI_CORE_FOR_COSMOS)
        elif EndpointType.AzureStorageContainer.value == endpoint_type:
            return endpoints.storage_containers

    def delete(self, endpoint_name: Optional[str] = None, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource.properties.routing.endpoints
        if endpoint_type:
            endpoint_type = endpoint_type.lower()
            if EndpointType.CosmosDBContainer.value == endpoint_type and not self.support_cosmos:
                raise InvalidArgumentValueError(INVALID_CLI_CORE_FOR_COSMOS)

        if endpoint_name:
            # Delete endpoint by name
            endpoint_name = endpoint_name.lower()

            if not endpoint_type or EndpointType.EventHub.value == endpoint_type:
                endpoints.event_hubs = [e for e in endpoints.event_hubs if e.name.lower() != endpoint_name]
            if not endpoint_type or EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints.service_bus_queues = [e for e in endpoints.service_bus_queues if e.name.lower() != endpoint_name]
            if not endpoint_type or EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints.service_bus_topics = [e for e in endpoints.service_bus_topics if e.name.lower() != endpoint_name]
            if self.support_cosmos and not endpoint_type or EndpointType.CosmosDBContainer.value == endpoint_type:
                endpoints.cosmos_db_sql_collections = [
                    e for e in endpoints.cosmos_db_sql_collections if e.name.lower() != endpoint_name
                ]
            if not endpoint_type or EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints.storage_containers = [e for e in endpoints.storage_containers if e.name.lower() != endpoint_name]
        elif endpoint_type:
            # Delete all endpoints in type
            if EndpointType.EventHub.value == endpoint_type:
                endpoints.event_hubs = []
            elif EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints.service_bus_queues = []
            elif EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints.service_bus_topics = []
            elif EndpointType.CosmosDBContainer.value == endpoint_type and self.support_cosmos:
                endpoints.cosmos_db_sql_collections = []
            elif EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints.storage_containers = []
        else:
            # Delete all endpoints
            endpoints.event_hubs = []
            endpoints.service_bus_queues = []
            endpoints.service_bus_topics = []
            if self.support_cosmos:
                endpoints.cosmos_db_sql_collections = []
            endpoints.storage_containers = []

        return self.discovery.client.begin_create_or_update(
            self.hub_resource.additional_properties["resourcegroup"],
            self.hub_resource.name,
            self.hub_resource,
            if_match=self.hub_resource.etag
        )


def get_eventhub_cstring(
    cmd, namespace_name: str, eventhub_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
        "--eventhub-name {} --name {} --subscription {}".format(
            namespace_name, rg, eventhub_name, policy_name, sub
        )
    ).as_json()["primaryConnectionString"]


def get_servicebus_topic_cstring(
    cmd, namespace_name: str, topic_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
        "--topic-name {} --name {} --subscription {}".format(
            namespace_name, rg, topic_name, policy_name, sub
        )
    ).as_json()["primaryConnectionString"]


def get_servicebus_queue_cstring(
    cmd, namespace_name: str, queue_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
        "--queue-name {} --name {}  --subscription {}".format(
            namespace_name, rg, queue_name, policy_name, sub
        )
    ).as_json()["primaryConnectionString"]


def get_cosmos_db_cstring(
    cmd, account_name: str, rg: str, sub: str
) -> str:
    output = cmd.invoke(
        'cosmosdb keys list --resource-group {} --name {} --type connection-strings --subscription {}'.format(
            rg, account_name, sub
        )
    ).as_json()

    for cs_object in output["connectionStrings"]:
        if cs_object["description"] == "Primary SQL Connection String":
            return cs_object["connectionString"]


def get_storage_cstring(cmd, account_name: str, rg: str, sub: str) -> str:
    return cmd.invoke(
        "storage account show-connection-string -n {} -g {}  --subscription {}".format(
            account_name, rg, sub
        )
    ).as_json()["connectionString"]
