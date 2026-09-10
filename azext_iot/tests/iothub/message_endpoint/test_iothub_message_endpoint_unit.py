# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import logging
from collections import defaultdict
import azext_iot.iothub.commands_message_endpoint as subject
from azure.cli.core.azclierror import (
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError
)
from azext_iot.iothub.common import BYTES_PER_MEGABYTE, AuthenticationType
from azext_iot.tests.generators import generate_names


logging.disable(logging.CRITICAL)

hub_name = "hubname"
hub_rg = "hubrg"
endpoint_name = generate_names()
resource_not_found_error = "Resource not found."
generic_response = {generate_names(): generate_names()}


iot_hub_providers_path = "azext_iot.iothub.providers"
path_find_resource = f"{iot_hub_providers_path}.discovery.IotHubDiscovery.find_resource"
parse_cosmos_db_cstring_path = f"{iot_hub_providers_path}.message_endpoint.parse_cosmos_db_connection_string"
get_storage_cstring_path = f"{iot_hub_providers_path}.message_endpoint.get_storage_cstring"


@pytest.fixture()
def fixture_update_endpoint_ops(mocker):
    # Parse connection string
    mocker.patch(parse_cosmos_db_cstring_path, return_value={
        "AccountKey": "get_cosmos_db_account_key",
        "AccountEndpoint": "get_cosmos_db_account_endpoint"
    })

    # Hub Resource
    find_resource = mocker.patch(path_find_resource, autospec=True)

    def create_mock_endpoint():
        return defaultdict(lambda: None, name=endpoint_name, authenticationType="keyBased")

    hub_mock = {
        "name": "test-hub",
        "etag": "test-etag",
        "resourcegroup": "test-rg",
        "subscriptionid": "test-sub",
        "properties": {
            "routing": {
                "endpoints": {
                    "eventHubs": [create_mock_endpoint()],
                    "serviceBusQueues": [create_mock_endpoint()],
                    "serviceBusTopics": [create_mock_endpoint()],
                    "storageContainers": [create_mock_endpoint()],
                    "cosmosDBSqlContainers": [create_mock_endpoint()],
                    "eventStreams": [defaultdict(lambda: None, name=endpoint_name, authenticationType="identityBased")],
                },
                "routes": [],
                "enrichments": [],
            }
        }
    }

    def initialize_mock_client(self, *args):
        self.client = mocker.MagicMock()
        self.client.begin_create_or_update.return_value = generic_response
        return hub_mock

    find_resource.side_effect = initialize_mock_client

    yield find_resource


@pytest.fixture()
def fixture_update_endpoint_backwards_comp_ops(mocker):
    # Parse connection string
    mocker.patch(parse_cosmos_db_cstring_path, return_value={
        "AccountKey": "get_cosmos_db_account_key",
        "AccountEndpoint": "get_cosmos_db_account_endpoint"
    })

    # Hub Resource
    find_resource = mocker.patch(path_find_resource, autospec=True)

    def create_mock_endpoint():
        return defaultdict(lambda: None, name=endpoint_name, authenticationType="keyBased")

    hub_mock = {
        "name": "test-hub",
        "etag": "test-etag",
        "resourcegroup": "test-rg",
        "subscriptionid": "test-sub",
        "properties": {
            "routing": {
                "endpoints": {
                    "eventHubs": [create_mock_endpoint()],
                    "serviceBusQueues": [create_mock_endpoint()],
                    "serviceBusTopics": [create_mock_endpoint()],
                    "storageContainers": [create_mock_endpoint()],
                    "cosmosDBSqlCollections": [create_mock_endpoint()],
                },
                "routes": [],
                "enrichments": [],
            }
        }
    }

    def initialize_mock_client(self, *args):
        self.client = mocker.MagicMock()
        self.client.begin_create_or_update.return_value = generic_response
        return hub_mock

    find_resource.side_effect = initialize_mock_client

    yield find_resource


class TestMessageEndpointUpdate:
    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": "[system]",
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
        ]
    )
    def test_message_endpoint_update_event_hub(self, mocker, fixture_cmd, fixture_update_endpoint_ops, req):
        result = subject.message_endpoint_update_event_hub(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["eventHubs"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["connectionString"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif req.get("connection_string"):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            assert endpoint["connectionString"] == req.get("connection_string")
        else:
            assert endpoint["authenticationType"] == "keyBased"

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert endpoint["entityPath"] == req.get("entity_path")
            else:
                assert endpoint["entityPath"] is None

            if req.get("endpoint_uri"):
                assert endpoint["endpointUri"] == req.get("endpoint_uri")
            else:
                assert endpoint["endpointUri"] is None

    def test_message_endpoint_update_event_hub_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_event_hub(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" not in error_msg

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_event_hub(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )

    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": "[system]",
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
        ]
    )
    def test_message_endpoint_update_service_bus_queue(self, mocker, fixture_cmd, fixture_update_endpoint_ops, req):
        result = subject.message_endpoint_update_service_bus_queue(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["serviceBusQueues"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["connectionString"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif req.get("connection_string"):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            assert endpoint["connectionString"] == req.get("connection_string")
        else:
            assert endpoint["authenticationType"] == "keyBased"

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert endpoint["entityPath"] == req.get("entity_path")
            else:
                assert endpoint["entityPath"] is None

            if req.get("endpoint_uri"):
                assert endpoint["endpointUri"] == req.get("endpoint_uri")
            else:
                assert endpoint["endpointUri"] is None

    def test_message_endpoint_update_service_bus_queue_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_service_bus_queue(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" not in error_msg

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_service_bus_queue(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )

    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": "[system]",
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
        ]
    )
    def test_message_endpoint_update_service_bus_topic(self, mocker, fixture_cmd, fixture_update_endpoint_ops, req):
        result = subject.message_endpoint_update_service_bus_topic(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["serviceBusTopics"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["connectionString"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif req.get("connection_string"):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            assert endpoint["connectionString"] == req.get("connection_string")
        else:
            assert endpoint["authenticationType"] == "keyBased"

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert endpoint["entityPath"] == req.get("entity_path")
            else:
                assert endpoint["entityPath"] is None

            if req.get("endpoint_uri"):
                assert endpoint["endpointUri"] == req.get("endpoint_uri")
            else:
                assert endpoint["endpointUri"] is None

    def test_message_endpoint_update_service_bus_topic_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_service_bus_topic(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" not in error_msg

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_service_bus_topic(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )

    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "batch_frequency": 1,
                "chunk_size_window": 100,
                "file_name_format": generate_names(),
                "identity": "[system]",
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "batch_frequency": None,
                "chunk_size_window": 30,
                "file_name_format": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "connection_string": None,
                "endpoint_uri": None,
                "batch_frequency": None,
                "chunk_size_window": None,
                "file_name_format": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "connection_string": generate_names(),
                "endpoint_uri": generate_names(),
                "batch_frequency": None,
                "chunk_size_window": None,
                "file_name_format": None,
                "identity": None,
                "resource_group_name": None,
            },
        ]
    )
    def test_message_endpoint_update_storage_container(self, mocker, fixture_cmd, fixture_update_endpoint_ops, req):
        result = subject.message_endpoint_update_storage_container(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["storageContainers"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set if present
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        if req.get("file_name_format"):
            assert endpoint["fileNameFormat"] == req.get("file_name_format")
        else:
            assert endpoint["fileNameFormat"] is None

        if req.get("batch_frequency"):
            assert endpoint["batchFrequencyInSeconds"] == req.get("batch_frequency")
        else:
            assert endpoint["batchFrequencyInSeconds"] is None

        if req.get("chunk_size_window"):
            assert endpoint["maxChunkSizeInBytes"] == (req.get("chunk_size_window") * BYTES_PER_MEGABYTE)
        else:
            assert endpoint["maxChunkSizeInBytes"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["connectionString"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif req.get("connection_string"):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            assert endpoint["connectionString"] == req.get("connection_string")
        else:
            assert endpoint["authenticationType"] == "keyBased"

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert endpoint["entityPath"] == req.get("entity_path")
            else:
                assert endpoint["entityPath"] is None

            if req.get("endpoint_uri"):
                assert endpoint["endpointUri"] == req.get("endpoint_uri")
            else:
                assert endpoint["endpointUri"] is None

    def test_message_endpoint_update_storage_container_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_storage_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" not in error_msg

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_storage_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )

    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "database_name": generate_names(),
                "connection_string": generate_names(),
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": generate_names(),
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": generate_names(),
                "partition_key_name": generate_names(),
                "partition_key_template": generate_names(),
                "identity": generate_names(),
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": "[system]",
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": generate_names(),
                "primary_key": None,
                "secondary_key": generate_names(),
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": generate_names(),
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": generate_names(),
                "primary_key": generate_names(),
                "secondary_key": generate_names(),
                "endpoint_uri": None,
                "partition_key_name": generate_names(),
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": generate_names(),
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
        ]
    )
    def test_message_endpoint_update_cosmos_db_sql_container(self, mocker, fixture_cmd, fixture_update_endpoint_ops, req):
        result = subject.message_endpoint_update_cosmos_db_container(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        # TODO: @vilit fix once service fixes their naming
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set if present
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        if req.get("database_name"):
            assert endpoint["databaseName"] == req.get("database_name").lower()
        else:
            assert endpoint["databaseName"] is None

        if req.get("partition_key_name"):
            partition_key_name = req.get("partition_key_name")
            if partition_key_name == "":
                assert endpoint["partitionKeyName"] is None
            else:
                endpoint["partitionKeyName"] == partition_key_name
        else:
            assert endpoint["partitionKeyName"] is None

        if req.get("partition_key_template"):
            partition_key_template = req.get("partition_key_template")
            if partition_key_template == "":
                assert endpoint["partitionKeyTemplate"] is None
            else:
                endpoint["partitionKeyTemplate"] == partition_key_template
        else:
            assert endpoint["partitionKeyTemplate"] is None

        # Connection strings dont exist
        assert endpoint["connectionString"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["primaryKey"] is None
            assert endpoint["secondaryKey"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif any([req.get("connection_string"), req.get("primary_key"), req.get("secondary_key")]):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            connection_string = req.get("connection_string")
            primary_key = req.get("primary_key")
            secondary_key = req.get("secondary_key")
            endpoint_uri = req.get("endpoint_uri")

            if primary_key:
                assert endpoint["primaryKey"] == primary_key
            if secondary_key:
                assert endpoint["secondaryKey"] == secondary_key
            if not primary_key and not secondary_key and connection_string:
                assert endpoint["primaryKey"] == endpoint["secondaryKey"] == "get_cosmos_db_account_key"

            if endpoint_uri:
                assert endpoint["endpointUri"] == endpoint_uri
            elif connection_string:
                assert endpoint["endpointUri"] == "get_cosmos_db_account_endpoint"
        else:
            assert endpoint["authenticationType"] == "keyBased"

    def test_message_endpoint_update_cosmos_db_sql_container_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_cosmos_db_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" in error_msg

        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_cosmos_db_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                primary_key="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" in error_msg

        with pytest.raises(MutuallyExclusiveArgumentError) as e:
            subject.message_endpoint_update_cosmos_db_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                secondary_key="fake_cstring",
                identity="[system]"
            )
        error_msg = e.value.error_msg
        assert "--connection-string" in error_msg
        assert "--identity" in error_msg
        assert "--primary-key and/or --secondary-key" in error_msg

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_cosmos_db_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )

    @pytest.mark.parametrize(
        "req",
        [
            {},
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "database_name": generate_names(),
                "connection_string": generate_names(),
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": generate_names(),
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": generate_names(),
                "partition_key_name": generate_names(),
                "partition_key_template": generate_names(),
                "identity": generate_names(),
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": "[system]",
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": generate_names(),
                "primary_key": None,
                "secondary_key": generate_names(),
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": generate_names(),
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "database_name": None,
                "connection_string": generate_names(),
                "primary_key": generate_names(),
                "secondary_key": generate_names(),
                "endpoint_uri": None,
                "partition_key_name": generate_names(),
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "database_name": generate_names(),
                "connection_string": None,
                "primary_key": None,
                "secondary_key": None,
                "endpoint_uri": None,
                "partition_key_name": None,
                "partition_key_template": None,
                "identity": None,
                "resource_group_name": None,
            },
        ]
    )
    def test_message_endpoint_update_cosmos_db_sql_collections(
        self, mocker, fixture_cmd, fixture_update_endpoint_backwards_comp_ops, req
    ):
        result = subject.message_endpoint_update_cosmos_db_container(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            **req
        )
        fixture_find_resource = fixture_update_endpoint_backwards_comp_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        # TODO: @vilit fix once service fixes their naming
        endpoints = hub_resource["properties"]["routing"]["endpoints"]["cosmosDBSqlCollections"]
        assert len(endpoints) == 1
        endpoint = endpoints[0]

        assert endpoint["name"] == endpoint_name

        # if a prop is not set, it will be a Mock object
        # Props that will always be set if present
        if req.get("endpoint_resource_group"):
            assert endpoint["resourceGroup"] == req.get("endpoint_resource_group")
        else:
            assert endpoint["resourceGroup"] is None

        if req.get("endpoint_subscription_id"):
            assert endpoint["subscriptionId"] == req.get("endpoint_subscription_id")
        else:
            assert endpoint["subscriptionId"] is None

        if req.get("database_name"):
            assert endpoint["databaseName"] == req.get("database_name").lower()
        else:
            assert endpoint["databaseName"] is None

        if req.get("partition_key_name"):
            partition_key_name = req.get("partition_key_name")
            if partition_key_name == "":
                assert endpoint["partitionKeyName"] is None
            else:
                endpoint["partitionKeyName"] == partition_key_name
        else:
            assert endpoint["partitionKeyName"] is None

        if req.get("partition_key_template"):
            partition_key_template = req.get("partition_key_template")
            if partition_key_template == "":
                assert endpoint["partitionKeyTemplate"] is None
            else:
                endpoint["partitionKeyTemplate"] == partition_key_template
        else:
            assert endpoint["partitionKeyTemplate"] is None

        # Connection strings dont exist
        assert endpoint["connectionString"] is None

        # Authentication props
        if req.get("identity"):
            assert endpoint["authenticationType"] == AuthenticationType.IdentityBased.value
            assert endpoint["primaryKey"] is None
            assert endpoint["secondaryKey"] is None
            identity = req.get("identity")
            if identity == "[system]":
                assert endpoint["identity"] is None
            else:
                assert isinstance(endpoint["identity"], dict)
                assert endpoint["identity"]["userAssignedIdentity"] == identity
        elif any([req.get("connection_string"), req.get("primary_key"), req.get("secondary_key")]):
            assert endpoint["authenticationType"] == AuthenticationType.KeyBased.value
            assert endpoint["identity"] is None
            assert endpoint["entityPath"] is None
            connection_string = req.get("connection_string")
            primary_key = req.get("primary_key")
            secondary_key = req.get("secondary_key")
            endpoint_uri = req.get("endpoint_uri")

            if primary_key:
                assert endpoint["primaryKey"] == primary_key
            if secondary_key:
                assert endpoint["secondaryKey"] == secondary_key
            if not primary_key and not secondary_key and connection_string:
                assert endpoint["primaryKey"] == endpoint["secondaryKey"] == "get_cosmos_db_account_key"

            if endpoint_uri:
                assert endpoint["endpointUri"] == endpoint_uri
            elif connection_string:
                assert endpoint["endpointUri"] == "get_cosmos_db_account_endpoint"
        else:
            assert endpoint["authenticationType"] == "keyBased"


class TestFabricEventStreamCreate:
    uami_id = "/subscriptions/0000/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami1"

    @pytest.mark.parametrize(
        "identity",
        [
            "[system]",
            uami_id,
        ]
    )
    def test_create_fabric_eventstream_happy_path(self, fixture_cmd, fixture_update_endpoint_ops, identity):
        es_endpoint_name = "es-" + generate_names()
        result = subject.message_endpoint_create_fabric_eventstream(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=es_endpoint_name,
            endpoint_uri="sb://test-ns.servicebus.windows.net",
            entity_path="es-entity",
            identity=identity,
            workspace_id="ws-id-1",
            eventstream_id="es-id-1",
            source_id="src-id-1",
            resource_group_name=hub_rg,
        )
        assert result == generic_response

    def test_create_fabric_eventstream_minimum_args(self, fixture_cmd, fixture_update_endpoint_ops):
        result = subject.message_endpoint_create_fabric_eventstream(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name="es-" + generate_names(),
            endpoint_uri="sb://test-ns.servicebus.windows.net",
            entity_path="es-entity",
            identity="[system]",
            workspace_id="ws-id-1",
            eventstream_id="es-id-1",
            source_id="src-id-1",
        )
        assert result == generic_response

    def test_create_fabric_eventstream_missing_workspace_id_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path="es-entity",
                identity="[system]",
                workspace_id=None,
                eventstream_id="es-id-1",
                source_id="src-id-1",
            )

    def test_create_fabric_eventstream_missing_eventstream_id_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path="es-entity",
                identity="[system]",
                workspace_id="ws-id-1",
                eventstream_id=None,
                source_id="src-id-1",
            )

    def test_create_fabric_eventstream_missing_source_id_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path="es-entity",
                identity="[system]",
                workspace_id="ws-id-1",
                eventstream_id="es-id-1",
                source_id=None,
            )

    def test_create_fabric_eventstream_missing_identity_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path="es-entity",
                identity=None,
                workspace_id="ws-id-1",
                eventstream_id="es-id-1",
                source_id="src-id-1",
            )

    def test_create_fabric_eventstream_missing_endpoint_uri_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri=None,
                entity_path="es-entity",
                identity="[system]",
                workspace_id="ws-id-1",
                eventstream_id="es-id-1",
                source_id="src-id-1",
            )

    def test_create_fabric_eventstream_missing_entity_path_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(RequiredArgumentMissingError):
            subject.message_endpoint_create_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="es-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path=None,
                identity="[system]",
                workspace_id="ws-id-1",
                eventstream_id="es-id-1",
                source_id="src-id-1",
            )

    def test_create_fabric_eventstream_works_on_hub_without_eventstreams_key(
        self, fixture_cmd, fixture_update_endpoint_backwards_comp_ops
    ):
        result = subject.message_endpoint_create_fabric_eventstream(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name="es-" + generate_names(),
            endpoint_uri="sb://test-ns.servicebus.windows.net",
            entity_path="es-entity",
            identity="[system]",
            workspace_id="ws-id-1",
            eventstream_id="es-id-1",
            source_id="src-id-1",
        )
        assert result == generic_response


class TestFabricEventStreamUpdate:
    def test_update_fabric_eventstream_happy_path(self, fixture_cmd, fixture_update_endpoint_ops):
        result = subject.message_endpoint_update_fabric_eventstream(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            endpoint_uri="sb://new-ns.servicebus.windows.net",
            entity_path="new-entity",
            identity="[system]",
            workspace_id="updated-ws-id",
            eventstream_id="updated-es-id",
            source_id="updated-src-id",
            resource_group_name=hub_rg,
        )
        assert result == generic_response

    def test_update_fabric_eventstream_identity_only(self, fixture_cmd, fixture_update_endpoint_ops):
        # Should be allowed to swap from SAMI to UAMI without touching URI/entity-path.
        uami = TestFabricEventStreamCreate.uami_id
        result = subject.message_endpoint_update_fabric_eventstream(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            identity=uami,
        )
        assert result == generic_response

    def test_create_fabric_eventstream_provider_requires_fabric_ids(self, fixture_cmd, fixture_update_endpoint_ops):
        from azext_iot.iothub.providers.message_endpoint import MessageEndpoint
        from azext_iot.iothub.common import EndpointType
        provider = MessageEndpoint(cmd=fixture_cmd, hub_name=hub_name, rg=hub_rg)
        for missing in ("workspace_id", "eventstream_id", "source_id"):
            kwargs = {
                "endpoint_name": "es-" + generate_names(),
                "endpoint_type": EndpointType.FabricEventStream.value,
                "endpoint_uri": "sb://test-ns.servicebus.windows.net",
                "entity_path": "entity",
                "identity": "[system]",
                "workspace_id": "ws-id",
                "eventstream_id": "es-id",
                "source_id": "src-id",
            }
            kwargs[missing] = None
            with pytest.raises(RequiredArgumentMissingError):
                provider.create(**kwargs)

    def test_update_fabric_eventstream_nonexistent_errors(self, fixture_cmd, fixture_update_endpoint_ops):
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_fabric_eventstream(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name="nonexistent-" + generate_names(),
                endpoint_uri="sb://test-ns.servicebus.windows.net",
                entity_path="entity",
                identity="[system]",
            )


class TestFabricEventStreamShowListDelete:
    def test_list_includes_fabric_eventstream(self, fixture_cmd, fixture_update_endpoint_ops):
        # Default list (no type filter) returns the endpoints dict, which now includes eventStreams.
        result = subject.message_endpoint_list(
            cmd=fixture_cmd,
            hub_name=hub_name,
            resource_group_name=hub_rg,
        )
        assert "eventStreams" in result
        assert len(result["eventStreams"]) >= 1

    def test_list_by_type_fabric_eventstream(self, fixture_cmd, fixture_update_endpoint_ops):
        from azext_iot.iothub.common import EndpointType
        result = subject.message_endpoint_list(
            cmd=fixture_cmd,
            hub_name=hub_name,
            endpoint_type=EndpointType.FabricEventStream.value,
            resource_group_name=hub_rg,
        )
        assert isinstance(result, list)
