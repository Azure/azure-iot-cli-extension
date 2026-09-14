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
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError
)
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import handle_service_exception
from azext_iot.iothub.common import (
    BYTES_PER_MEGABYTE,
    FORCE_DELETE_WARNING,
    INVALID_CLI_CORE_FOR_COSMOS,
    NULL_WARNING,
    SYSTEM_ASSIGNED_IDENTITY,
    AuthenticationType,
    EncodingFormat,
    EndpointType,
    IoTHubSDKVersion
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common._azure import parse_cosmos_db_connection_string
from azure.core.exceptions import HttpResponseError


logger = get_logger(__name__)


class MessageEndpoint(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(MessageEndpoint, self).__init__(cmd, hub_name, rg, dataplane=False)
        # Modelless SDK omits None/empty fields; ensure enrichments key exists.
        self.hub_resource["properties"]["routing"].setdefault("enrichments", [])
        self.hub_resource["properties"]["routing"]["endpoints"].setdefault("eventStreams", [])
        # Temporary flag to check for which cosmos property to look for.
        self.support_cosmos = IoTHubSDKVersion.NoCosmos.value
        endpoints = self.hub_resource["properties"]["routing"]["endpoints"]
        if "cosmosDBSqlCollections" in endpoints:
            self.support_cosmos = IoTHubSDKVersion.CosmosCollections.value
        if "cosmosDBSqlContainers" in endpoints:
            self.support_cosmos = IoTHubSDKVersion.CosmosContainers.value
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
        identity: Optional[str] = None,
        workspace_id: Optional[str] = None,
        eventstream_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ):
        if not endpoint_resource_group:
            endpoint_resource_group = self.hub_resource["resourcegroup"]
        if not endpoint_subscription_id:
            endpoint_subscription_id = self.hub_resource['subscriptionid']

        if connection_string and identity:
            raise MutuallyExclusiveArgumentError("Please use either --connection-string or --identity, both were provided.")

        authentication_type = AuthenticationType.KeyBased.value
        endpoint_identity = None
        if identity:
            authentication_type = AuthenticationType.IdentityBased.value
            if identity != SYSTEM_ASSIGNED_IDENTITY:
                endpoint_identity = {
                    "userAssignedIdentity": identity
                }
        elif not connection_string:
            # check for args to get the connection string
            self._connection_string_retrieval_args_check(
                endpoint_type=endpoint_type,
                endpoint_account_name=endpoint_account_name,
                entity_path=entity_path,
                endpoint_policy_name=endpoint_policy_name
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

        endpoints = self.hub_resource["properties"]["routing"]["endpoints"]
        if endpoint_type.lower() == EndpointType.EventHub.value:
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_eventhub_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    eventhub_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            elif entity_path:
                new_endpoint["entityPath"] = entity_path.replace("~", "/")
            endpoints["eventHubs"].append(new_endpoint)
        elif endpoint_type.lower() == EndpointType.ServiceBusQueue.value:
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_servicebus_queue_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    queue_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            if entity_path:
                new_endpoint["entityPath"] = entity_path
            endpoints["serviceBusQueues"].append(new_endpoint)
        elif endpoint_type.lower() == EndpointType.ServiceBusTopic.value:
            if fetch_connection_string:
                new_endpoint["connectionString"] = get_servicebus_topic_cstring(
                    cmd=self.cli,
                    namespace_name=endpoint_account_name,
                    topic_name=entity_path,
                    policy_name=endpoint_policy_name,
                    rg=endpoint_resource_group,
                    sub=endpoint_subscription_id
                )
            if entity_path:
                new_endpoint["entityPath"] = entity_path
            endpoints["serviceBusTopics"].append(new_endpoint)
        elif endpoint_type.lower() == EndpointType.CosmosDBContainer.value:
            if fetch_connection_string:
                # try to get connection string - this will be used to get keys + uri
                connection_string = get_cosmos_db_cstring(
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
            # cosmos db doesn't need connection strings
            del new_endpoint["connectionString"]
            new_endpoint.update({
                "databaseName": database_name,
                "primaryKey": primary_key,
                "secondaryKey": secondary_key,
                "partitionKeyName": partition_key_name,
                "partitionKeyTemplate": partition_key_template,
            })
            # @vilit - None checks for when the service breaks things
            if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                new_endpoint["containerName"] = container_name
                if endpoints["cosmosDBSqlContainers"] is None:
                    endpoints["cosmosDBSqlContainers"] = []
                endpoints["cosmosDBSqlContainers"].append(new_endpoint)
            if self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                new_endpoint["collectionName"] = container_name
                if endpoints["cosmosDBSqlCollections"] is None:
                    endpoints["cosmosDBSqlCollections"] = []
                endpoints["cosmosDBSqlCollections"].append(new_endpoint)
        elif endpoint_type.lower() == EndpointType.AzureStorageContainer.value:
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
            endpoints["storageContainers"].append(new_endpoint)
        elif endpoint_type == EndpointType.FabricEventStream.value:
            if not identity:
                raise RequiredArgumentMissingError(
                    "--identity is required for fabric-eventstream endpoints. "
                    "Use --identity [system] for the hub's system-assigned identity, "
                    "or pass a user-assigned identity resource ID."
                )
            if not endpoint_uri or not entity_path:
                raise RequiredArgumentMissingError(
                    "--endpoint-uri and --entity-path are both required for fabric-eventstream endpoints. "
                    "Obtain these values from the Fabric Custom Endpoint source connection details."
                )
            if not workspace_id or not eventstream_id or not source_id:
                raise RequiredArgumentMissingError(
                    "--workspace-id, --eventstream-id, and --source-id are all required for "
                    "fabric-eventstream endpoints. Obtain these from the Fabric Custom Endpoint."
                )
            es_endpoint = {
                "name": endpoint_name,
                "endpointUri": endpoint_uri,
                "entityPath": entity_path,
                "authenticationType": AuthenticationType.IdentityBased.value,
                "identity": endpoint_identity,
                "workspaceId": workspace_id,
                "eventStreamId": eventstream_id,
                "sourceId": source_id,
            }
            endpoints["eventStreams"].append(es_endpoint)

        try:
            return self.discovery.client.begin_create_or_update(
                self.hub_resource["resourcegroup"],
                self.hub_resource["name"],
                self.hub_resource,
                etag=self.hub_resource["etag"]
            )
        except HttpResponseError as e:
            handle_service_exception(e)

    def update(
        self,
        endpoint_name: str,
        endpoint_type: str,
        endpoint_resource_group: Optional[str] = None,
        endpoint_subscription_id: Optional[str] = None,
        connection_string: Optional[str] = None,
        batch_frequency: Optional[int] = None,
        chunk_size_window: Optional[int] = None,
        file_name_format: Optional[str] = None,
        endpoint_uri: Optional[str] = None,
        entity_path: Optional[str] = None,
        database_name: Optional[str] = None,
        primary_key: Optional[str] = None,
        secondary_key: Optional[str] = None,
        partition_key_name: Optional[str] = None,
        partition_key_template: Optional[str] = None,
        identity: Optional[str] = None,
        workspace_id: Optional[str] = None,
        eventstream_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ):
        # if nothing is provided -> should we block?
        # have the user say the type. Will make args easier (as in we do not need to check for unneeded args)
        original_endpoint = self._show_by_type(endpoint_name=endpoint_name, endpoint_type=endpoint_type)

        if any([connection_string, primary_key, secondary_key]) and identity:
            cosmos_db = endpoint_type.lower() == EndpointType.CosmosDBContainer.value
            optional_msg = ", --primary-key and/or --secondary-key," if cosmos_db else ""
            error_msg = "Please use either --connection-string" + optional_msg + " or --identity."
            raise MutuallyExclusiveArgumentError(error_msg)

        # Properties for all endpoint types
        if endpoint_resource_group:
            original_endpoint["resourceGroup"] = endpoint_resource_group
        if endpoint_subscription_id:
            original_endpoint["subscriptionId"] = endpoint_subscription_id
        if endpoint_uri:
            # Handle this later with cosmos db connection string parsing
            original_endpoint["endpointUri"] = endpoint_uri

        # Identity/Connection String schenanigans
        # If Identity and Connection String args are provided, Identity wins
        if identity:
            if endpoint_type.lower() == EndpointType.CosmosDBContainer.value:
                if original_endpoint.get("primaryKey") or original_endpoint.get("secondaryKey"):
                    logger.warning(NULL_WARNING.format("Primary and secondary keys"))
                original_endpoint["primaryKey"] = None
                original_endpoint["secondaryKey"] = None
            else:
                if original_endpoint.get("connectionString"):
                    logger.warning(NULL_WARNING.format("The connection string"))
                original_endpoint["connectionString"] = None
            original_endpoint["authenticationType"] = AuthenticationType.IdentityBased.value
            if identity == SYSTEM_ASSIGNED_IDENTITY:
                original_endpoint["identity"] = None
            else:
                original_endpoint["identity"] = {
                    "userAssignedIdentity": identity
                }
        elif any([connection_string, primary_key, secondary_key]):
            if original_endpoint.get("identity"):
                logger.warning(NULL_WARNING.format("The managed identity property"))
            original_endpoint["identity"] = None
            original_endpoint["authenticationType"] = AuthenticationType.KeyBased.value
            if endpoint_type.lower() != EndpointType.CosmosDBContainer.value:
                original_endpoint["endpointUri"] = None
            if "entityPath" in original_endpoint:
                if original_endpoint["entityPath"]:
                    logger.warning(NULL_WARNING.format("The entity path"))
                original_endpoint["entityPath"] = None

            if endpoint_type.lower() != EndpointType.CosmosDBContainer.value:
                original_endpoint["connectionString"] = connection_string
            else:
                if primary_key:
                    original_endpoint["primaryKey"] = primary_key
                if secondary_key:
                    original_endpoint["secondaryKey"] = secondary_key

        # Properties by specific types
        if endpoint_type in [
            EndpointType.EventHub.value, EndpointType.ServiceBusQueue.value, EndpointType.ServiceBusTopic.value
        ] and entity_path and not connection_string:
            # only set entity_path if no connection string
            original_endpoint["entityPath"] = entity_path

        if endpoint_type == EndpointType.AzureStorageContainer.value:
            if file_name_format:
                original_endpoint["fileNameFormat"] = file_name_format
            if batch_frequency:
                original_endpoint["batchFrequencyInSeconds"] = batch_frequency
            if chunk_size_window:
                original_endpoint["maxChunkSizeInBytes"] = (chunk_size_window * BYTES_PER_MEGABYTE)
        elif endpoint_type == EndpointType.CosmosDBContainer.value:
            if connection_string:
                # parse out key from connection string
                parsed_cs = parse_cosmos_db_connection_string(connection_string)
                if not primary_key and not secondary_key:
                    original_endpoint["primaryKey"] = parsed_cs["AccountKey"]
                    original_endpoint["secondaryKey"] = parsed_cs["AccountKey"]
                # parse out endpoint uri from connection string
                if not endpoint_uri:
                    original_endpoint["endpointUri"] = parsed_cs["AccountEndpoint"]
            if database_name:
                original_endpoint["databaseName"] = database_name
            if partition_key_name:
                original_endpoint["partitionKeyName"] = None if partition_key_name == "" else partition_key_name
            if partition_key_template:
                original_endpoint["partitionKeyTemplate"] = None if partition_key_template == "" else partition_key_template
        elif endpoint_type == EndpointType.FabricEventStream.value:
            if entity_path:
                original_endpoint["entityPath"] = entity_path
            if workspace_id:
                original_endpoint["workspaceId"] = workspace_id
            if eventstream_id:
                original_endpoint["eventStreamId"] = eventstream_id
            if source_id:
                original_endpoint["sourceId"] = source_id

        return self.discovery.client.begin_create_or_update(
            self.hub_resource["resourcegroup"],
            self.hub_resource["name"],
            self.hub_resource,
            etag=self.hub_resource["etag"]
        )

    def _connection_string_retrieval_args_check(
        self,
        endpoint_type: str,
        endpoint_account_name: Optional[str] = None,
        entity_path: Optional[str] = None,
        endpoint_policy_name: Optional[str] = None,
    ):
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

    def _show_by_type(self, endpoint_name: str, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource["properties"]["routing"]["endpoints"]
        endpoint_list = []
        if endpoint_type is None or endpoint_type.lower() == EndpointType.EventHub.value:
            endpoint_list.extend(endpoints["eventHubs"])
        if endpoint_type is None or endpoint_type.lower() == EndpointType.ServiceBusQueue.value:
            endpoint_list.extend(endpoints["serviceBusQueues"])
        if endpoint_type is None or endpoint_type.lower() == EndpointType.ServiceBusTopic.value:
            endpoint_list.extend(endpoints["serviceBusTopics"])
        if endpoint_type is None or endpoint_type.lower() == EndpointType.AzureStorageContainer.value:
            endpoint_list.extend(endpoints["storageContainers"])
        if (endpoint_type is None or endpoint_type.lower() == EndpointType.CosmosDBContainer.value):
            if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                endpoint_list.extend(endpoints["cosmosDBSqlContainers"])
            elif self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                endpoint_list.extend(endpoints["cosmosDBSqlCollections"])
        if endpoint_type is None or endpoint_type.lower() == EndpointType.FabricEventStream.value:
            endpoint_list.extend(endpoints["eventStreams"])

        for endpoint in endpoint_list:
            if endpoint["name"].lower() == endpoint_name.lower():
                return endpoint

        if endpoint_type:
            raise ResourceNotFoundError(
                f"{endpoint_type} endpoint {endpoint_name} not found in IoT Hub {self.hub_resource['name']}."
            )

        raise ResourceNotFoundError(f"Endpoint {endpoint_name} not found in IoT Hub {self.hub_resource['name']}.")

    def show(self, endpoint_name: str):
        return self._show_by_type(endpoint_name=endpoint_name)

    def list(self, endpoint_type: Optional[str] = None):
        endpoints = self.hub_resource["properties"]["routing"]["endpoints"]
        if not endpoint_type:
            return endpoints
        endpoint_type = endpoint_type.lower()
        if EndpointType.EventHub.value == endpoint_type:
            return endpoints["eventHubs"]
        elif EndpointType.ServiceBusQueue.value == endpoint_type:
            return endpoints["serviceBusQueues"]
        elif EndpointType.ServiceBusTopic.value == endpoint_type:
            return endpoints["serviceBusTopics"]
        elif EndpointType.CosmosDBContainer.value == endpoint_type:
            if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                return endpoints["cosmosDBSqlContainers"]
            elif self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                return endpoints["cosmosDBSqlCollections"]
        elif EndpointType.CosmosDBContainer.value == endpoint_type:
            raise InvalidArgumentValueError(INVALID_CLI_CORE_FOR_COSMOS)
        elif EndpointType.AzureStorageContainer.value == endpoint_type:
            return endpoints["storageContainers"]
        elif EndpointType.FabricEventStream.value == endpoint_type:
            return endpoints["eventStreams"]

    def delete(
        self,
        endpoint_name: Optional[str] = None,
        endpoint_type: Optional[str] = None,
        force: bool = False
    ):
        endpoints = self.hub_resource["properties"]["routing"]["endpoints"]
        if endpoint_type:
            endpoint_type = endpoint_type.lower()
            if (
                EndpointType.CosmosDBContainer.value == endpoint_type and self.support_cosmos == IoTHubSDKVersion.NoCosmos.value
            ):
                raise InvalidArgumentValueError(INVALID_CLI_CORE_FOR_COSMOS)

        if self.hub_resource["properties"]["routing"]["enrichments"] or self.hub_resource["properties"]["routing"]["routes"]:
            # collect endpoints to remove
            endpoint_names = []
            if endpoint_name:
                # use show to check if this endpoint "exists" in the current extension state
                try:
                    self.show(endpoint_name)
                    endpoint_names.append(endpoint_name)
                except ResourceNotFoundError:
                    pass
            else:
                if not endpoint_type or endpoint_type == EndpointType.EventHub.value:
                    endpoint_names.extend([e["name"] for e in endpoints["eventHubs"]])
                if not endpoint_type or endpoint_type == EndpointType.ServiceBusQueue.value:
                    endpoint_names.extend([e["name"] for e in endpoints["serviceBusQueues"]])
                if not endpoint_type or endpoint_type == EndpointType.ServiceBusTopic.value:
                    endpoint_names.extend([e["name"] for e in endpoints["serviceBusTopics"]])
                if not endpoint_type or endpoint_type == EndpointType.CosmosDBContainer.value:
                    if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                        endpoint_names.extend([e["name"] for e in endpoints["cosmosDBSqlContainers"]])
                    if self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                        endpoint_names.extend([e["name"] for e in endpoints["cosmosDBSqlCollections"]])
                if not endpoint_type or endpoint_type == EndpointType.AzureStorageContainer.value:
                    endpoint_names.extend([e["name"] for e in endpoints["storageContainers"]])
                if not endpoint_type or endpoint_type == EndpointType.FabricEventStream.value:
                    endpoint_names.extend([e["name"] for e in endpoints["eventStreams"]])

            # only do the routing and enrichment checks if there are endpoints to check.
            if force and endpoint_names:
                # remove enrichments
                if self.hub_resource["properties"]["routing"]["enrichments"]:
                    enrichments = self.hub_resource["properties"]["routing"]["enrichments"]
                    enrichments = [e for e in enrichments if not any(n for n in e["endpointNames"] if n in endpoint_names)]
                    self.hub_resource["properties"]["routing"]["enrichments"] = enrichments
                # remove routes
                if self.hub_resource["properties"]["routing"]["routes"]:
                    routes = self.hub_resource["properties"]["routing"]["routes"]
                    routes = [r for r in routes if r["endpointNames"][0] not in endpoint_names]
                    self.hub_resource["properties"]["routing"]["routes"] = routes
            elif endpoint_names:
                # warn if needed:
                conflicts = []
                if self.hub_resource["properties"]["routing"]["enrichments"]:
                    enrichments = self.hub_resource["properties"]["routing"]["enrichments"]
                    num_enrichments = len(
                        [e for e in enrichments if any(n for n in e["endpointNames"] if n in endpoint_names)]
                    )
                    if num_enrichments > 0:
                        enrichment_msg = f"{num_enrichments} message enrichment" + ("s" if num_enrichments > 1 else "")
                        conflicts.append(enrichment_msg)

                if self.hub_resource["properties"]["routing"]["routes"]:
                    routes = self.hub_resource["properties"]["routing"]["routes"]
                    num_routes = len([r for r in routes if r["endpointNames"][0] in endpoint_names])
                    if num_routes > 0:
                        enrichment_msg = f"{num_routes} route" + ("s" if num_routes > 1 else "")
                        conflicts.append(enrichment_msg)
                if conflicts:
                    logger.warn(FORCE_DELETE_WARNING.format(" and ".join(conflicts)))

        if endpoint_name:
            # Delete endpoint by name
            endpoint_name = endpoint_name.lower()

            if not endpoint_type or EndpointType.EventHub.value == endpoint_type:
                endpoints["eventHubs"] = [e for e in endpoints["eventHubs"] if e["name"].lower() != endpoint_name]
            if not endpoint_type or EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints["serviceBusQueues"] = [e for e in endpoints["serviceBusQueues"] if e["name"].lower() != endpoint_name]
            if not endpoint_type or EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints["serviceBusTopics"] = [e for e in endpoints["serviceBusTopics"] if e["name"].lower() != endpoint_name]
            if not endpoint_type or endpoint_type == EndpointType.CosmosDBContainer.value:
                if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                    cosmos_db_endpoints = endpoints["cosmosDBSqlContainers"] or []
                    endpoints["cosmosDBSqlContainers"] = [
                        e for e in cosmos_db_endpoints if e["name"].lower() != endpoint_name
                    ]
                if self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                    cosmos_db_endpoints = endpoints["cosmosDBSqlCollections"] or []
                    endpoints["cosmosDBSqlCollections"] = [
                        e for e in cosmos_db_endpoints if e["name"].lower() != endpoint_name
                    ]
            if not endpoint_type or EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints["storageContainers"] = [e for e in endpoints["storageContainers"] if e["name"].lower() != endpoint_name]
            if not endpoint_type or EndpointType.FabricEventStream.value == endpoint_type:
                endpoints["eventStreams"] = [e for e in endpoints["eventStreams"] if e["name"].lower() != endpoint_name]
        elif endpoint_type:
            # Delete all endpoints in type
            if EndpointType.EventHub.value == endpoint_type:
                endpoints["eventHubs"] = []
            elif EndpointType.ServiceBusQueue.value == endpoint_type:
                endpoints["serviceBusQueues"] = []
            elif EndpointType.ServiceBusTopic.value == endpoint_type:
                endpoints["serviceBusTopics"] = []
            elif EndpointType.CosmosDBContainer.value == endpoint_type:
                if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                    endpoints["cosmosDBSqlContainers"] = []
                elif self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                    endpoints["cosmosDBSqlCollections"] = []
            elif EndpointType.AzureStorageContainer.value == endpoint_type:
                endpoints["storageContainers"] = []
            elif EndpointType.FabricEventStream.value == endpoint_type:
                endpoints["eventStreams"] = []
        else:
            # Delete all endpoints
            endpoints["eventHubs"] = []
            endpoints["serviceBusQueues"] = []
            endpoints["serviceBusTopics"] = []
            if self.support_cosmos == IoTHubSDKVersion.CosmosContainers.value:
                endpoints["cosmosDBSqlContainers"] = []
            if self.support_cosmos == IoTHubSDKVersion.CosmosCollections.value:
                endpoints["cosmosDBSqlCollections"] = []
            endpoints["storageContainers"] = []
            endpoints["eventStreams"] = []

        try:
            return self.discovery.client.begin_create_or_update(
                self.hub_resource["resourcegroup"],
                self.hub_resource["name"],
                self.hub_resource,
                etag=self.hub_resource["etag"]
            )
        except HttpResponseError as e:
            handle_service_exception(e)


def get_eventhub_cstring(
    cmd, namespace_name: str, eventhub_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
        "--eventhub-name {} --name {}".format(
            namespace_name, rg, eventhub_name, policy_name
        ),
        subscription=sub
    ).as_json()["primaryConnectionString"]


def get_servicebus_topic_cstring(
    cmd, namespace_name: str, topic_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
        "--topic-name {} --name {}".format(
            namespace_name, rg, topic_name, policy_name
        ),
        subscription=sub
    ).as_json()["primaryConnectionString"]


def get_servicebus_queue_cstring(
    cmd, namespace_name: str, queue_name: str, policy_name: str, rg: str, sub: str
) -> str:
    return cmd.invoke(
        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
        "--queue-name {} --name {}".format(
            namespace_name, rg, queue_name, policy_name
        ),
        subscription=sub
    ).as_json()["primaryConnectionString"]


def get_cosmos_db_cstring(
    cmd, account_name: str, rg: str, sub: str
) -> str:
    output = cmd.invoke(
        'cosmosdb keys list --resource-group {} --name {} --type connection-strings'.format(
            rg, account_name
        ),
        subscription=sub
    ).as_json()

    for cs_object in output["connectionStrings"]:
        if cs_object["description"] == "Primary SQL Connection String":
            return cs_object["connectionString"]


def get_storage_cstring(cmd, account_name: str, rg: str, sub: str) -> str:
    return cmd.invoke(
        "storage account show-connection-string -n {} -g {}".format(
            account_name, rg
        ),
        subscription=sub
    ).as_json()["connectionString"]
