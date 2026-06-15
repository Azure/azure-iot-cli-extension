# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from collections import defaultdict

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.iothub.providers.message_endpoint import MessageEndpoint
from azext_iot.iothub.common import EndpointType, AuthenticationType, IoTHubSDKVersion

logging.disable(logging.CRITICAL)

hub_name = "test-hub"
hub_rg = "test-rg"

me_path = "azext_iot.iothub.providers.message_endpoint"
path_find_resource = "azext_iot.iothub.providers.discovery.IotHubDiscovery.find_resource"
generic_response = {"result": "ok"}


def _build_hub(cosmos_version=IoTHubSDKVersion.CosmosContainers.value):
    endpoints = {
        "eventHubs": [],
        "serviceBusQueues": [],
        "serviceBusTopics": [],
        "storageContainers": [],
    }
    if cosmos_version == IoTHubSDKVersion.CosmosContainers.value:
        endpoints["cosmosDBSqlContainers"] = []
    elif cosmos_version == IoTHubSDKVersion.CosmosCollections.value:
        endpoints["cosmosDBSqlCollections"] = []
    return {
        "name": hub_name,
        "etag": "test-etag",
        "resourcegroup": hub_rg,
        "subscriptionid": "test-sub",
        "properties": {"routing": {"endpoints": endpoints, "routes": [], "enrichments": []}},
    }


@pytest.fixture()
def provider(mocker):
    """Return a factory that builds a MessageEndpoint with a mocked hub + client."""
    mocker.patch(f"{me_path}.EmbeddedCLI", autospec=True)
    # Patch connection-string getters to avoid real CLI invocation.
    mocker.patch(f"{me_path}.get_eventhub_cstring", return_value="eh-cstring")
    mocker.patch(f"{me_path}.get_servicebus_queue_cstring", return_value="sbq-cstring")
    mocker.patch(f"{me_path}.get_servicebus_topic_cstring", return_value="sbt-cstring")
    mocker.patch(f"{me_path}.get_storage_cstring", return_value="storage-cstring")
    mocker.patch(
        f"{me_path}.get_cosmos_db_cstring",
        return_value="AccountEndpoint=https://x/;AccountKey=key;",
    )
    mocker.patch(
        f"{me_path}.parse_cosmos_db_connection_string",
        return_value={"AccountKey": "key", "AccountEndpoint": "https://x/"},
    )

    def _make(cosmos_version=IoTHubSDKVersion.CosmosContainers.value, hub=None):
        hub = hub or _build_hub(cosmos_version)
        find_resource = mocker.patch(path_find_resource, autospec=True)

        def initialize(self, *args):
            self.client = mocker.MagicMock()
            self.client.begin_create_or_update.return_value = generic_response
            return hub

        find_resource.side_effect = initialize
        cmd = mocker.MagicMock()
        p = MessageEndpoint(cmd=cmd, hub_name=hub_name, rg=hub_rg)
        return p, hub

    return _make


class TestCreate:
    def test_create_event_hub_fetch_cstring(self, provider):
        p, hub = provider()
        result = p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            endpoint_account_name="acct",
            entity_path="path",
            endpoint_policy_name="pol",
        )
        assert result == generic_response
        eh = hub["properties"]["routing"]["endpoints"]["eventHubs"]
        assert eh[0]["connectionString"] == "eh-cstring"

    def test_create_event_hub_with_entity_path(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            connection_string="cs",
            entity_path="a~b",
        )
        eh = hub["properties"]["routing"]["endpoints"]["eventHubs"]
        assert eh[0]["entityPath"] == "a/b"

    def test_create_service_bus_queue(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.ServiceBusQueue.value,
            endpoint_account_name="acct",
            entity_path="path",
            endpoint_policy_name="pol",
        )
        assert hub["properties"]["routing"]["endpoints"]["serviceBusQueues"][0]["connectionString"] == "sbq-cstring"

    def test_create_service_bus_topic(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.ServiceBusTopic.value,
            connection_string="cs",
            entity_path="path",
        )
        assert hub["properties"]["routing"]["endpoints"]["serviceBusTopics"][0]["entityPath"] == "path"

    def test_create_service_bus_topic_fetch_cstring(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.ServiceBusTopic.value,
            endpoint_account_name="acct",
            entity_path="path",
            endpoint_policy_name="pol",
        )
        assert hub["properties"]["routing"]["endpoints"]["serviceBusTopics"][0]["connectionString"] == "sbt-cstring"

    def test_create_cosmos_single_primary_key(self, provider):
        p, hub = provider()
        # Provide only primary key + endpoint_uri (no cstring fetch) -> secondary derived from primary.
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            endpoint_uri="https://x/",
            primary_key="pk",
            container_name="cont",
            database_name="db",
        )
        cont = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]
        assert cont["primaryKey"] == "pk"
        assert cont["secondaryKey"] == "pk"

    def test_create_cosmos_single_secondary_key(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            endpoint_uri="https://x/",
            secondary_key="sk",
            container_name="cont",
            database_name="db",
        )
        cont = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]
        assert cont["primaryKey"] == "sk"
        assert cont["secondaryKey"] == "sk"

    def test_create_cosmos_container_list_none(self, provider):
        p, hub = provider()
        # Service returned None for the container list -> provider re-initializes it.
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"] = None
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            container_name="cont",
            database_name="db",
        )
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]["containerName"] == "cont"

    def test_create_cosmos_collection_list_none(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"] = None
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            container_name="cont",
            database_name="db",
        )
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"][0]["collectionName"] == "cont"

    def test_create_cosmos_container_fetch_cstring(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            endpoint_account_name="acct",
            container_name="cont",
            database_name="db",
            partition_key_name="pk",
        )
        cont = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]
        assert cont[0]["containerName"] == "cont"
        assert cont[0]["primaryKey"] == "key"

    def test_create_cosmos_collection(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            container_name="cont",
            database_name="db",
        )
        coll = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"]
        assert coll[0]["collectionName"] == "cont"

    def test_create_cosmos_missing_key(self, provider, mocker):
        p, _ = provider()
        # Fetched connection string is None -> no keys derivable.
        mocker.patch(f"{me_path}.get_cosmos_db_cstring", return_value=None)
        with pytest.raises(RequiredArgumentMissingError):
            p.create(
                endpoint_name="ep1",
                endpoint_type=EndpointType.CosmosDBContainer.value,
                endpoint_account_name="acct",
                endpoint_uri="https://x/",
                container_name="cont",
                database_name="db",
            )

    def test_create_cosmos_identity_missing_uri(self, provider):
        p, _ = provider()
        with pytest.raises(RequiredArgumentMissingError):
            p.create(
                endpoint_name="ep1",
                endpoint_type=EndpointType.CosmosDBContainer.value,
                container_name="cont",
                database_name="db",
                identity="[system]",
            )

    def test_create_storage_container(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.AzureStorageContainer.value,
            connection_string="cs",
            container_name="cont",
            encoding="JSON",
        )
        sc = hub["properties"]["routing"]["endpoints"]["storageContainers"]
        assert sc[0]["containerName"] == "cont"
        assert sc[0]["encoding"] == "json"

    def test_create_storage_fetch_cstring(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.AzureStorageContainer.value,
            endpoint_account_name="acct",
            container_name="cont",
        )
        sc = hub["properties"]["routing"]["endpoints"]["storageContainers"][0]
        assert sc["connectionString"] == "storage-cstring"

    def test_create_storage_missing_container(self, provider):
        p, _ = provider()
        with pytest.raises(RequiredArgumentMissingError):
            p.create(
                endpoint_name="ep1",
                endpoint_type=EndpointType.AzureStorageContainer.value,
                connection_string="cs",
            )

    def test_create_identity_user_assigned(self, provider):
        p, hub = provider()
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            identity="myidentity",
        )
        eh = hub["properties"]["routing"]["endpoints"]["eventHubs"]
        assert eh[0]["identity"]["userAssignedIdentity"] == "myidentity"
        assert eh[0]["authenticationType"] == AuthenticationType.IdentityBased.value

    def test_create_mutually_exclusive(self, provider):
        p, _ = provider()
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.create(
                endpoint_name="ep1",
                endpoint_type=EndpointType.EventHub.value,
                connection_string="cs",
                identity="myidentity",
            )

    def test_create_error(self, provider, mocker):
        p, _ = provider()
        handler = mocker.patch(f"{me_path}.handle_service_exception")
        p.discovery.client.begin_create_or_update.side_effect = HttpResponseError("boom")
        p.create(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            connection_string="cs",
        )
        handler.assert_called_once()


class TestConnectionStringArgsCheck:
    def test_missing_args_messaging(self, provider):
        p, _ = provider()
        with pytest.raises(ArgumentUsageError):
            p._connection_string_retrieval_args_check(endpoint_type=EndpointType.EventHub.value)

    def test_missing_args_storage(self, provider):
        p, _ = provider()
        with pytest.raises(ArgumentUsageError):
            p._connection_string_retrieval_args_check(
                endpoint_type=EndpointType.AzureStorageContainer.value
            )


class TestShowListDelete:
    def _seed(self, hub):
        eps = hub["properties"]["routing"]["endpoints"]
        eps["eventHubs"].append(defaultdict(lambda: None, name="eh1"))
        eps["serviceBusQueues"].append(defaultdict(lambda: None, name="sbq1"))
        eps["serviceBusTopics"].append(defaultdict(lambda: None, name="sbt1"))
        eps["storageContainers"].append(defaultdict(lambda: None, name="sc1"))
        eps["cosmosDBSqlContainers"].append(defaultdict(lambda: None, name="cdb1"))

    def test_show(self, provider):
        p, hub = provider()
        self._seed(hub)
        assert p.show("EH1")["name"] == "eh1"

    def test_show_not_found(self, provider):
        p, hub = provider()
        self._seed(hub)
        with pytest.raises(ResourceNotFoundError):
            p.show("missing")

    def test_show_by_type_not_found(self, provider):
        p, hub = provider()
        self._seed(hub)
        with pytest.raises(ResourceNotFoundError):
            p._show_by_type(endpoint_name="missing", endpoint_type=EndpointType.EventHub.value)

    def test_list_all(self, provider):
        p, hub = provider()
        self._seed(hub)
        result = p.list()
        assert "eventHubs" in result

    def test_list_by_type(self, provider):
        p, hub = provider()
        self._seed(hub)
        assert p.list(endpoint_type=EndpointType.EventHub.value)[0]["name"] == "eh1"
        assert p.list(endpoint_type=EndpointType.ServiceBusQueue.value)[0]["name"] == "sbq1"
        assert p.list(endpoint_type=EndpointType.ServiceBusTopic.value)[0]["name"] == "sbt1"
        assert p.list(endpoint_type=EndpointType.AzureStorageContainer.value)[0]["name"] == "sc1"
        assert p.list(endpoint_type=EndpointType.CosmosDBContainer.value)[0]["name"] == "cdb1"

    def test_list_cosmos_collections(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"].append(
            defaultdict(lambda: None, name="coll1")
        )
        assert p.list(endpoint_type=EndpointType.CosmosDBContainer.value)[0]["name"] == "coll1"

    def test_delete_by_name(self, provider):
        p, hub = provider()
        self._seed(hub)
        result = p.delete(endpoint_name="eh1")
        assert result == generic_response
        assert hub["properties"]["routing"]["endpoints"]["eventHubs"] == []

    def test_delete_by_type(self, provider):
        p, hub = provider()
        self._seed(hub)
        p.delete(endpoint_type=EndpointType.ServiceBusQueue.value)
        assert hub["properties"]["routing"]["endpoints"]["serviceBusQueues"] == []

    @pytest.mark.parametrize(
        "endpoint_type, key",
        [
            (EndpointType.EventHub.value, "eventHubs"),
            (EndpointType.ServiceBusTopic.value, "serviceBusTopics"),
            (EndpointType.CosmosDBContainer.value, "cosmosDBSqlContainers"),
            (EndpointType.AzureStorageContainer.value, "storageContainers"),
        ],
    )
    def test_delete_all_in_type(self, provider, endpoint_type, key):
        p, hub = provider()
        self._seed(hub)
        p.delete(endpoint_type=endpoint_type)
        assert hub["properties"]["routing"]["endpoints"][key] == []

    def test_delete_all(self, provider):
        p, hub = provider()
        self._seed(hub)
        p.delete()
        eps = hub["properties"]["routing"]["endpoints"]
        assert eps["eventHubs"] == []
        assert eps["storageContainers"] == []
        assert eps["cosmosDBSqlContainers"] == []

    def test_delete_cosmos_no_support(self, provider):
        p, _ = provider(cosmos_version=IoTHubSDKVersion.NoCosmos.value)
        with pytest.raises(InvalidArgumentValueError):
            p.delete(endpoint_type=EndpointType.CosmosDBContainer.value)

    def test_delete_with_routes_warning(self, provider):
        p, hub = provider()
        self._seed(hub)
        hub["properties"]["routing"]["routes"] = [
            {"name": "r1", "endpointNames": ["eh1"]}
        ]
        hub["properties"]["routing"]["enrichments"] = [
            {"key": "k", "endpointNames": ["eh1"]}
        ]
        # Without force -> warns but still deletes.
        p.delete(endpoint_name="eh1")
        assert hub["properties"]["routing"]["endpoints"]["eventHubs"] == []

    def test_delete_with_routes_force(self, provider):
        p, hub = provider()
        self._seed(hub)
        hub["properties"]["routing"]["routes"] = [
            {"name": "r1", "endpointNames": ["eh1"]}
        ]
        hub["properties"]["routing"]["enrichments"] = [
            {"key": "k", "endpointNames": ["eh1"]}
        ]
        p.delete(endpoint_name="eh1", force=True)
        assert hub["properties"]["routing"]["routes"] == []
        assert hub["properties"]["routing"]["enrichments"] == []

    def test_delete_error(self, provider, mocker):
        p, hub = provider()
        self._seed(hub)
        handler = mocker.patch(f"{me_path}.handle_service_exception")
        p.discovery.client.begin_create_or_update.side_effect = HttpResponseError("boom")
        p.delete()
        handler.assert_called_once()

    def test_delete_all_with_routes_warning(self, provider):
        p, hub = provider()
        self._seed(hub)
        # endpoint_name is None -> collect all names; routes/enrichments present -> warn path.
        hub["properties"]["routing"]["routes"] = [{"name": "r1", "endpointNames": ["eh1"]}]
        hub["properties"]["routing"]["enrichments"] = [{"key": "k", "endpointNames": ["sbq1"]}]
        p.delete()
        assert hub["properties"]["routing"]["endpoints"]["eventHubs"] == []

    def test_delete_name_not_found_with_routes(self, provider):
        p, hub = provider()
        self._seed(hub)
        # show() raises ResourceNotFoundError for a missing endpoint -> swallowed, nothing removed.
        hub["properties"]["routing"]["routes"] = [{"name": "r1", "endpointNames": ["eh1"]}]
        p.delete(endpoint_name="missing")
        assert hub["properties"]["routing"]["routes"][0]["name"] == "r1"

    def test_delete_collections_all_with_routes_warning(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        eps = hub["properties"]["routing"]["endpoints"]
        eps["cosmosDBSqlCollections"].append(defaultdict(lambda: None, name="coll1"))
        hub["properties"]["routing"]["routes"] = [{"name": "r1", "endpointNames": ["coll1"]}]
        hub["properties"]["routing"]["enrichments"] = [{"key": "k", "endpointNames": ["coll1"]}]
        p.delete()
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"] == []

    def test_delete_collections_force_removes_routes(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        eps = hub["properties"]["routing"]["endpoints"]
        eps["cosmosDBSqlCollections"].append(defaultdict(lambda: None, name="coll1"))
        hub["properties"]["routing"]["routes"] = [{"name": "r1", "endpointNames": ["coll1"]}]
        hub["properties"]["routing"]["enrichments"] = [{"key": "k", "endpointNames": ["coll1"]}]
        p.delete(endpoint_type=EndpointType.CosmosDBContainer.value, force=True)
        assert hub["properties"]["routing"]["routes"] == []
        assert hub["properties"]["routing"]["enrichments"] == []
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"] == []

    def test_delete_collections_by_name(self, provider):
        p, hub = provider(cosmos_version=IoTHubSDKVersion.CosmosCollections.value)
        eps = hub["properties"]["routing"]["endpoints"]
        eps["cosmosDBSqlCollections"].append(defaultdict(lambda: None, name="coll1"))
        p.delete(endpoint_name="coll1", endpoint_type=EndpointType.CosmosDBContainer.value)
        assert hub["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"] == []


class TestUpdate:
    def _seed_endpoint(self, hub, key, **extra):
        ep = defaultdict(lambda: None, name="ep1", authenticationType="keyBased")
        ep.update(extra)
        hub["properties"]["routing"]["endpoints"][key].append(ep)

    def test_update_event_hub_identity(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "eventHubs", connectionString="cs", entityPath="path")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            identity="myidentity",
        )
        ep = hub["properties"]["routing"]["endpoints"]["eventHubs"][0]
        assert ep["authenticationType"] == AuthenticationType.IdentityBased.value
        assert ep["connectionString"] is None

    def test_update_event_hub_system_identity(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "eventHubs")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            identity="[system]",
        )
        ep = hub["properties"]["routing"]["endpoints"]["eventHubs"][0]
        assert ep["identity"] is None

    def test_update_event_hub_connection_string(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "eventHubs", identity={"userAssignedIdentity": "x"}, entityPath="path")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.EventHub.value,
            connection_string="newcs",
        )
        ep = hub["properties"]["routing"]["endpoints"]["eventHubs"][0]
        assert ep["connectionString"] == "newcs"
        assert ep["identity"] is None

    def test_update_mutually_exclusive(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "eventHubs")
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.update(
                endpoint_name="ep1",
                endpoint_type=EndpointType.EventHub.value,
                connection_string="cs",
                identity="myidentity",
            )

    def test_update_storage(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "storageContainers")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.AzureStorageContainer.value,
            file_name_format="{iothub}",
            batch_frequency=100,
            chunk_size_window=10,
            endpoint_resource_group="rg2",
            endpoint_subscription_id="sub2",
            endpoint_uri="https://x/",
        )
        ep = hub["properties"]["routing"]["endpoints"]["storageContainers"][0]
        assert ep["fileNameFormat"] == "{iothub}"
        assert ep["batchFrequencyInSeconds"] == 100

    def test_update_cosmos_connection_string(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "cosmosDBSqlContainers")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            connection_string="cs",
            database_name="db",
            partition_key_name="pk",
            partition_key_template="tpl",
        )
        ep = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]
        assert ep["primaryKey"] == "key"
        assert ep["databaseName"] == "db"

    def test_update_cosmos_identity(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "cosmosDBSqlContainers", primaryKey="pk", secondaryKey="sk")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            identity="myidentity",
        )
        ep = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]
        assert ep["primaryKey"] is None
        assert ep["secondaryKey"] is None

    def test_update_cosmos_keys(self, provider):
        p, hub = provider()
        self._seed_endpoint(hub, "cosmosDBSqlContainers")
        p.update(
            endpoint_name="ep1",
            endpoint_type=EndpointType.CosmosDBContainer.value,
            primary_key="pk",
            secondary_key="sk",
        )
        ep = hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"][0]
        assert ep["primaryKey"] == "pk"
        assert ep["secondaryKey"] == "sk"


class TestCstringHelpers:
    def test_get_eventhub_cstring(self, mocker):
        import azext_iot.iothub.providers.message_endpoint as me

        cli = mocker.MagicMock()
        cli.invoke.return_value.as_json.return_value = {"primaryConnectionString": "X"}
        assert me.get_eventhub_cstring(cli, "ns", "eh", "pol", "rg", "sub") == "X"

    def test_get_servicebus_topic_cstring(self, mocker):
        import azext_iot.iothub.providers.message_endpoint as me

        cli = mocker.MagicMock()
        cli.invoke.return_value.as_json.return_value = {"primaryConnectionString": "X"}
        assert me.get_servicebus_topic_cstring(cli, "ns", "t", "pol", "rg", "sub") == "X"

    def test_get_servicebus_queue_cstring(self, mocker):
        import azext_iot.iothub.providers.message_endpoint as me

        cli = mocker.MagicMock()
        cli.invoke.return_value.as_json.return_value = {"primaryConnectionString": "X"}
        assert me.get_servicebus_queue_cstring(cli, "ns", "q", "pol", "rg", "sub") == "X"

    def test_get_cosmos_db_cstring(self, mocker):
        import azext_iot.iothub.providers.message_endpoint as me

        cli = mocker.MagicMock()
        cli.invoke.return_value.as_json.return_value = {
            "connectionStrings": [
                {"description": "Primary SQL Connection String", "connectionString": "X"}
            ]
        }
        assert me.get_cosmos_db_cstring(cli, "acct", "rg", "sub") == "X"

    def test_get_storage_cstring(self, mocker):
        import azext_iot.iothub.providers.message_endpoint as me

        cli = mocker.MagicMock()
        cli.invoke.return_value.as_json.return_value = {"connectionString": "X"}
        assert me.get_storage_cstring(cli, "acct", "rg", "sub") == "X"
