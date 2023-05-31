# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import pytest
import responses
import re
import azext_iot.iothub.commands_message_endpoint as subject
from azure.cli.core.azclierror import (
    FileOperationError,
    BadRequestError,
    MutuallyExclusiveArgumentError,
    ResourceNotFoundError
)
from azext_iot.iothub.common import EndpointType, AuthenticationType
import azext_iot.iothub.providers.helpers.state_strings as constants
from azext_iot.tests.generators import generate_names

from azure.mgmt.iothub.models import ManagedIdentity
from azext_iot.tests.conftest import generate_cs

hub_name = "hubname"
hub_rg = "hubrg"
endpoint_name = generate_names()
resource_not_found_error = "Resource not found."
generic_response = {generate_names(): generate_names()}


path_find_resource = "azext_iot.iothub.providers.discovery.IotHubDiscovery.find_resource"
arg_check_path = "azext_iot.iothub.providers.message_endpoint.MessageEndpoint._connection_string_retrieval_args_check"
get_eventhub_cstring_path = "azext_iot.iothub.providers.message_endpoint.get_eventhub_cstring"
get_servicebus_topic_cstring_path = "azext_iot.iothub.providers.message_endpoint.get_servicebus_topic_cstring"
get_servicebus_queue_cstring_path = "azext_iot.iothub.providers.message_endpoint.get_servicebus_queue_cstring"
get_cosmos_db_cstring_path = "azext_iot.iothub.providers.message_endpoint.get_cosmos_db_cstring"
get_storage_cstring_path = "azext_iot.iothub.providers.message_endpoint.get_storage_cstring"

@pytest.fixture()
def fixture_update_endpoint_ops(mocker):
    # Fetch connection string
    arg_check = mocker.patch(arg_check_path)
    mocker.patch(get_eventhub_cstring_path, return_value="get_eventhub_cstring")
    mocker.patch(get_servicebus_topic_cstring_path, return_value="get_servicebus_topic_cstring")
    mocker.patch(get_servicebus_queue_cstring_path, return_value="get_servicebus_queue_cstring")
    mocker.patch(get_cosmos_db_cstring_path, return_value="get_cosmos_db_cstring")
    mocker.patch(get_storage_cstring_path, return_value="get_storage_cstring")

    # Hub Resource
    find_resource = mocker.patch(path_find_resource, autospec=True)

    def create_mock_endpoint(endpoint_type):
        endpoint = mocker.Mock()
        endpoint.name = endpoint_name
        endpoint.type = endpoint_type
        return endpoint

    hub_mock = mocker.MagicMock()
    hub_mock.properties.routing.endpoints.event_hubs = [create_mock_endpoint(endpoint_type="event_hubs")]
    hub_mock.properties.routing.endpoints.service_bus_queues = [create_mock_endpoint(endpoint_type="service_bus_queues")]
    hub_mock.properties.routing.endpoints.service_bus_topics = [create_mock_endpoint(endpoint_type="service_bus_topics")]
    hub_mock.properties.routing.endpoints.storage_containers = [create_mock_endpoint(endpoint_type="storage_containers")]
    hub_mock.properties.routing.endpoints.cosmos_db_sql_collections = [
        create_mock_endpoint(endpoint_type="cosmos_db_sql_collections")
    ]

    def initialize_mock_client(self, *args):
        self.client = mocker.MagicMock()
        self.client.begin_create_or_update.return_value = generic_response
        return hub_mock

    find_resource.side_effect = initialize_mock_client

    yield find_resource, arg_check


class TestMessageEndpointUpdate:
    @pytest.mark.parametrize(
        "req",
        [
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": None,
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": "update",
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": generate_names(),
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
        fixture_find_resource, fixture_arg_check = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        eventhubs = hub_resource.properties.routing.endpoints.event_hubs
        assert len(eventhubs) == 1
        eventhub = eventhubs[0]

        assert eventhub.name == endpoint_name
        assert eventhub.type == "event_hubs"
        mock = mocker.Mock

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert eventhub.resource_group == req.get("endpoint_resource_group")
        else:
            assert isinstance(eventhub.resource_group, mock)

        if req.get("endpoint_subscription_id"):
            assert eventhub.subscription_id == req.get("endpoint_subscription_id")
        else:
            assert isinstance(eventhub.subscription_id, mock)

        # Authentication props
        if req.get("identity"):
            assert eventhub.authentication_type == AuthenticationType.IdentityBased.value
            assert eventhub.connection_string is None
            identity = req.get("identity")
            if identity == "[system]":
                assert eventhub.identity is None
            else:
                assert isinstance(eventhub.identity, ManagedIdentity)
                assert eventhub.identity.user_assigned_identity == identity
                assert fixture_arg_check.call_count == 0
        elif req.get("connection_string"):
            assert eventhub.authentication_type == AuthenticationType.KeyBased.value
            assert eventhub.identity is None
            assert eventhub.entity_path is None
            connection_string = req.get("connection_string")
            if connection_string == "update":
                eventhub.connection_string = "get_eventhub_cstring"
                args_check = fixture_arg_check.call_args[1]
                assert args_check["endpoint_account_name"] == req.get("endpoint_account_name")
                assert args_check["entity_path"] == req.get("entity_path")
                assert args_check["endpoint_policy_name"] == req.get("endpoint_policy_name")
            else:
                eventhub.connection_string = connection_string
        else:
            assert isinstance(eventhub.authentication_type, mock)

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert eventhub.entity_path == req.get("entity_path")
            else:
                assert isinstance(eventhub.entity_path, mock)

            if req.get("endpoint_uri"):
                assert eventhub.endpoint_uri == req.get("endpoint_uri")
            else:
                assert isinstance(eventhub.endpoint_uri, mock)

    def test_message_endpoint_update_event_hub_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError):
            subject.message_endpoint_update_event_hub(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )

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
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": None,
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": "update",
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": generate_names(),
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
        fixture_find_resource, fixture_arg_check = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        eventhubs = hub_resource.properties.routing.endpoints.service_bus_queues
        assert len(eventhubs) == 1
        eventhub = eventhubs[0]

        assert eventhub.name == endpoint_name
        assert eventhub.type == "service_bus_queues"
        mock = mocker.Mock

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert eventhub.resource_group == req.get("endpoint_resource_group")
        else:
            assert isinstance(eventhub.resource_group, mock)

        if req.get("endpoint_subscription_id"):
            assert eventhub.subscription_id == req.get("endpoint_subscription_id")
        else:
            assert isinstance(eventhub.subscription_id, mock)

        # Authentication props
        if req.get("identity"):
            assert eventhub.authentication_type == AuthenticationType.IdentityBased.value
            assert eventhub.connection_string is None
            identity = req.get("identity")
            if identity == "[system]":
                assert eventhub.identity is None
            else:
                assert isinstance(eventhub.identity, ManagedIdentity)
                assert eventhub.identity.user_assigned_identity == identity
                assert fixture_arg_check.call_count == 0
        elif req.get("connection_string"):
            assert eventhub.authentication_type == AuthenticationType.KeyBased.value
            assert eventhub.identity is None
            assert eventhub.entity_path is None
            connection_string = req.get("connection_string")
            if connection_string == "update":
                eventhub.connection_string = "get_eventhub_cstring"
                args_check = fixture_arg_check.call_args[1]
                assert args_check["endpoint_account_name"] == req.get("endpoint_account_name")
                assert args_check["entity_path"] == req.get("entity_path")
                assert args_check["endpoint_policy_name"] == req.get("endpoint_policy_name")
            else:
                eventhub.connection_string = connection_string
        else:
            assert isinstance(eventhub.authentication_type, mock)

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert eventhub.entity_path == req.get("entity_path")
            else:
                assert isinstance(eventhub.entity_path, mock)

            if req.get("endpoint_uri"):
                assert eventhub.endpoint_uri == req.get("endpoint_uri")
            else:
                assert isinstance(eventhub.endpoint_uri, mock)

    def test_message_endpoint_update_service_bus_queue_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError):
            subject.message_endpoint_update_service_bus_queue(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )

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
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": None,
                "connection_string": generate_names(),
                "endpoint_uri": None,
                "entity_path": None,
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": "update",
                "endpoint_uri": generate_names(),
                "entity_path": generate_names(),
                "identity": None,
                "resource_group_name": generate_names(),
            },
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": None,
                "endpoint_policy_name": generate_names(),
                "connection_string": None,
                "endpoint_uri": generate_names(),
                "entity_path": None,
                "identity": generate_names(),
                "resource_group_name": None,
            },
            {
                "endpoint_account_name": generate_names(),
                "endpoint_resource_group": generate_names(),
                "endpoint_subscription_id": generate_names(),
                "endpoint_policy_name": generate_names(),
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
        fixture_find_resource, fixture_arg_check = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        eventhubs = hub_resource.properties.routing.endpoints.service_bus_topics
        assert len(eventhubs) == 1
        eventhub = eventhubs[0]

        assert eventhub.name == endpoint_name
        assert eventhub.type == "service_bus_topics"
        mock = mocker.Mock

        # if a prop is not set, it will be a Mock object
        # Props that will always be set
        if req.get("endpoint_resource_group"):
            assert eventhub.resource_group == req.get("endpoint_resource_group")
        else:
            assert isinstance(eventhub.resource_group, mock)

        if req.get("endpoint_subscription_id"):
            assert eventhub.subscription_id == req.get("endpoint_subscription_id")
        else:
            assert isinstance(eventhub.subscription_id, mock)

        # Authentication props
        if req.get("identity"):
            assert eventhub.authentication_type == AuthenticationType.IdentityBased.value
            assert eventhub.connection_string is None
            identity = req.get("identity")
            if identity == "[system]":
                assert eventhub.identity is None
            else:
                assert isinstance(eventhub.identity, ManagedIdentity)
                assert eventhub.identity.user_assigned_identity == identity
                assert fixture_arg_check.call_count == 0
        elif req.get("connection_string"):
            assert eventhub.authentication_type == AuthenticationType.KeyBased.value
            assert eventhub.identity is None
            assert eventhub.entity_path is None
            connection_string = req.get("connection_string")
            if connection_string == "update":
                eventhub.connection_string = "get_eventhub_cstring"
                args_check = fixture_arg_check.call_args[1]
                assert args_check["endpoint_account_name"] == req.get("endpoint_account_name")
                assert args_check["entity_path"] == req.get("entity_path")
                assert args_check["endpoint_policy_name"] == req.get("endpoint_policy_name")
            else:
                eventhub.connection_string = connection_string
        else:
            assert isinstance(eventhub.authentication_type, mock)

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert eventhub.entity_path == req.get("entity_path")
            else:
                assert isinstance(eventhub.entity_path, mock)

            if req.get("endpoint_uri"):
                assert eventhub.endpoint_uri == req.get("endpoint_uri")
            else:
                assert isinstance(eventhub.endpoint_uri, mock)

    def test_message_endpoint_update_service_bus_topic_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError):
            subject.message_endpoint_update_service_bus_topic(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )

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
            {
                "endpoint_account_name": None,
                "endpoint_resource_group": None,
                "endpoint_subscription_id": None,
                "endpoint_policy_name": None,
                "connection_string": None,
                "endpoint_uri": None,
                "entity_path": None,
                "container_name": None,
                "encoding": None,
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
        fixture_find_resource, fixture_arg_check = fixture_update_endpoint_ops

        assert result == generic_response
        resource_group = fixture_find_resource.call_args[0][2]
        assert req.get("resource_group_name") == resource_group
        hub_resource = fixture_find_resource.call_args[0][0].client.begin_create_or_update.call_args[0][2]
        eventhubs = hub_resource.properties.routing.endpoints.storage_containers
        assert len(eventhubs) == 1
        eventhub = eventhubs[0]

        assert eventhub.name == endpoint_name
        assert eventhub.type == "storage_containers"
        mock = mocker.Mock

        # if a prop is not set, it will be a Mock object
        # Props that will always be set if present
        if req.get("endpoint_resource_group"):
            assert eventhub.resource_group == req.get("endpoint_resource_group")
        else:
            assert isinstance(eventhub.resource_group, mock)

        if req.get("endpoint_subscription_id"):
            assert eventhub.subscription_id == req.get("endpoint_subscription_id")
        else:
            assert isinstance(eventhub.subscription_id, mock)

        # Authentication props
        if req.get("identity"):
            assert eventhub.authentication_type == AuthenticationType.IdentityBased.value
            assert eventhub.connection_string is None
            identity = req.get("identity")
            if identity == "[system]":
                assert eventhub.identity is None
            else:
                assert isinstance(eventhub.identity, ManagedIdentity)
                assert eventhub.identity.user_assigned_identity == identity
                assert fixture_arg_check.call_count == 0
        elif req.get("connection_string"):
            assert eventhub.authentication_type == AuthenticationType.KeyBased.value
            assert eventhub.identity is None
            assert eventhub.entity_path is None
            connection_string = req.get("connection_string")
            if connection_string == "update":
                eventhub.connection_string = "get_eventhub_cstring"
                args_check = fixture_arg_check.call_args[1]
                assert args_check["endpoint_account_name"] == req.get("endpoint_account_name")
                assert args_check["entity_path"] == req.get("entity_path")
                assert args_check["endpoint_policy_name"] == req.get("endpoint_policy_name")
            else:
                eventhub.connection_string = connection_string
        else:
            assert isinstance(eventhub.authentication_type, mock)

        # props that are conditional
        if not req.get("connection_string"):
            if req.get("entity_path"):
                assert eventhub.entity_path == req.get("entity_path")
            else:
                assert isinstance(eventhub.entity_path, mock)

            if req.get("endpoint_uri"):
                assert eventhub.endpoint_uri == req.get("endpoint_uri")
            else:
                assert isinstance(eventhub.endpoint_uri, mock)

    def test_message_endpoint_update_storage_container_error(self, fixture_cmd, fixture_update_endpoint_ops):
        # Cannot do both types of Authentication
        with pytest.raises(MutuallyExclusiveArgumentError):
            subject.message_endpoint_update_storage_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=endpoint_name,
                connection_string="fake_cstring",
                identity="[system]"
            )

        # not found
        with pytest.raises(ResourceNotFoundError):
            subject.message_endpoint_update_storage_container(
                cmd=fixture_cmd,
                hub_name=hub_name,
                endpoint_name=generate_names(),
            )