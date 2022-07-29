# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
from azext_iot.iothub.common import AuthenticationType
from azext_iot.tests.iothub import (
    EP_COSMOS_PARTITION_PATH,
    STORAGE_ACCOUNT,
    IoTLiveScenarioTest,
    EP_RG,
    EP_EVENTHUB_NAMESPACE,
    EP_EVENTHUB_INSTANCE,
    EP_SERVICEBUS_NAMESPACE,
    EP_SERVICEBUS_QUEUE,
    EP_SERVICEBUS_TOPIC,
    EP_COSMOS_DATABASE,
    EP_COSMOS_COLLECTION,
    STORAGE_CONTAINER
)
from azext_iot.common._azure import _parse_connection_string, parse_cosmos_db_connection_string


class TestIoTMessagingEndpoints(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTMessagingEndpoints, self).__init__(
            test_case
        )
        self._create_user_identity()
        self.enable_hub_system_identity()
        self.ran_eventhub = False

    @pytest.fixture(scope='class', autouse=True)
    def tearDownEndpoints(self):
        yield None
        self._delete_user_identity()

        # Event hub deletes fail if not there (delete is not a no-op)
        if self.ran_eventhub:
            self._delete_eventhub()

        self._delete_cosmos_db()
        self._delete_service_bus_topic_queue()

        # Only delete storage if it was created for this test
        if hasattr(self, "storage_cstring"):
            self._delete_storage_account()

    def test_iot_storage_endpoint_lifecycle(self):
        self._create_storage_account()
        self._assign_storage_account_roles()
        endpoint_names = self.generate_device_names(3)
        endpoint_uri = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
        default_file_format = "{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}"
        max_chunk_size_constant = 1048576
        # use connection string - note how the connection string needs to have entity path and the
        # endpoint uri and path are left blank
        self.cmd(
            "iot hub messaging-endpoint create storage-container -n {} -g {} --en {} --erg {} -c {} --container {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0], EP_RG, self.storage_cstring, STORAGE_CONTAINER
            )
        )

        # use defaults
        expected_cs_endpoint = build_expected_endpoint(
            endpoint_names[0], EP_RG, self.entity_sub, connection_string=self.storage_cstring, container_name=STORAGE_CONTAINER, batch_frequency_in_seconds=300, encoding="avro", file_name_format=default_file_format, max_chunk_size_in_bytes=max_chunk_size_constant*300
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

        # Use hub identity with no defaults
        self.kwargs["file_format"] = default_file_format.replace("/", "_")
        self.cmd(
            "iot hub messaging-endpoint create storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} --identity [system] --auth-type identityBased -b {} -w {} --encoding {} --ff {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1], EP_RG, endpoint_uri, STORAGE_CONTAINER, 60, 10, "json", "{file_format}"
            )
        )

        expected_sys_endpoint = build_expected_endpoint(
            endpoint_names[1], EP_RG, self.entity_sub, container_name=STORAGE_CONTAINER, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri,
            batch_frequency_in_seconds=60, encoding="json", file_name_format=self.kwargs["file_format"], max_chunk_size_in_bytes=max_chunk_size_constant*10
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

        # Use user identity
        self.cmd(
            "iot hub messaging-endpoint create storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} --identity {} --auth-type identityBased -b {} -w {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2], EP_RG, endpoint_uri, STORAGE_CONTAINER, self.user_identity_id, 720, 500
            )
        )

        expected_user_endpoint = build_expected_endpoint(
            endpoint_names[2], EP_RG, self.entity_sub, container_name=STORAGE_CONTAINER, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri, identity=self.user_identity_id, batch_frequency_in_seconds=720, encoding="avro", file_name_format=default_file_format, max_chunk_size_in_bytes=max_chunk_size_constant*500
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_user_endpoint)

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()

        storage_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "storage-container"
            )
        ).get_output_in_json()

        assert len(storage_list) == 3
        assert endpoint_list["storageContainers"] == storage_list

        # Delete one event hub endpoint
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        )

        # ensure that only one got deleted
        storage_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "storage-container"
            )
        ).get_output_in_json()

        assert len(storage_list) == 2

        # Delete all event hub endpoints
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "storage-container"
            )
        )

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "storage-container"
            )
        ).get_output_in_json()

        assert endpoint_list == []

    def test_iot_servicebus_endpoint_lifecycle(self):
        # this test covers two endpoint types
        topic_cs, queue_cs = self._create_service_bus_topic_queue()
        endpoint_uri = f"sb://{EP_SERVICEBUS_NAMESPACE}.servicebus.windows.net"
        # create 6 names, 2 types of service bus endpoints * 3 auth types
        endpoint_names = self.generate_device_names(6)

        # create topic endpoint first - connection string
        self.cmd(
            "iot hub messaging-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0], EP_RG, topic_cs
            )
        )

        expected_cs_endpoint = build_expected_endpoint(
            endpoint_names[0], EP_RG, self.entity_sub, connection_string=topic_cs
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

        # topic - Use hub identity
        self.cmd(
            "iot hub messaging-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity [system] --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[1], EP_RG, endpoint_uri, EP_SERVICEBUS_TOPIC
            )
        )

        expected_sys_endpoint = build_expected_endpoint(
            endpoint_names[1], EP_RG, self.entity_sub, entity_path=EP_SERVICEBUS_TOPIC, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

        # topic - Use user identity
        self.cmd(
            "iot hub messaging-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity {} --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[2], EP_RG, endpoint_uri, EP_SERVICEBUS_TOPIC, self.user_identity_id
            )
        )

        expected_user_endpoint = build_expected_endpoint(
            endpoint_names[2], EP_RG, self.entity_sub, entity_path=EP_SERVICEBUS_TOPIC, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri, identity=self.user_identity_id
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_user_endpoint)

        # create queue endpoint - connection string
        self.cmd(
            "iot hub messaging-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} -c {}".format(
                self.entity_name, self.entity_rg, endpoint_names[3], EP_RG, queue_cs
            )
        )

        expected_cs_endpoint = build_expected_endpoint(
            endpoint_names[3], EP_RG, self.entity_sub, connection_string=queue_cs
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[3]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

        # queue - Use hub identity
        self.cmd(
            "iot hub messaging-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity [system] --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[4], EP_RG, endpoint_uri, EP_SERVICEBUS_QUEUE
            )
        )

        expected_sys_endpoint = build_expected_endpoint(
            endpoint_names[4], EP_RG, self.entity_sub, entity_path=EP_SERVICEBUS_QUEUE, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[4]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

        # queue - Use user identity
        self.cmd(
            "iot hub messaging-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity {} --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[5], EP_RG, endpoint_uri, EP_SERVICEBUS_QUEUE, self.user_identity_id
            )
        )

        expected_user_endpoint = build_expected_endpoint(
            endpoint_names[5], EP_RG, self.entity_sub, entity_path=EP_SERVICEBUS_QUEUE, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri, identity=self.user_identity_id
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[5]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_user_endpoint)

        # list
        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()

        topic_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-topic"
            )
        ).get_output_in_json()

        assert len(topic_list) == 3
        assert endpoint_list["serviceBusTopics"] == topic_list

        queue_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-queue"
            )
        ).get_output_in_json()

        assert len(queue_list) == 3
        assert endpoint_list["serviceBusQueues"] == queue_list

        # Delete one (topic)
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        )

        # ensure others are not deleted
        eventhub_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-topic"
            )
        ).get_output_in_json()

        assert len(eventhub_list) == 2

        queue_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-queue"
            )
        ).get_output_in_json()

        assert len(queue_list) == 3

        # delete all queue
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-queue"
            )
        )

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-queue"
            )
        ).get_output_in_json()

        assert endpoint_list == []

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-topic"
            )
        ).get_output_in_json()

        assert len(endpoint_list) == 2

        # delete all
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        )

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "servicebus-topic"
            )
        ).get_output_in_json()

        assert endpoint_list == []

    def test_iot_cosmos_endpoint_lifecycle(self):
        connection_string = self._create_cosmos_db()
        endpoint_names = self.generate_device_names(3)
        partition_template = "{iothub}-{device_id}-{DD}-{MM}-{YYYY}"
        partition_template_default = "{deviceid}-{YYYY}-{MM}"
        # use connection string - no pkn or pkt
        self.cmd(
            "iot hub messaging-endpoint create cosmosdb-collection -n {} -g {} --en {} --erg {} -c {} --cn {} --dn {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0], EP_RG, connection_string, EP_COSMOS_COLLECTION, EP_COSMOS_DATABASE
            )
        )

        parsed_cs = parse_cosmos_db_connection_string(connection_string)
        endpoint_uri = parsed_cs["AccountEndpoint"]
        expected_cs_endpoint = build_expected_endpoint(
            endpoint_names[0], EP_RG, self.entity_sub, primary_key=parsed_cs["AccountKey"], secondary_key=parsed_cs["AccountKey"], endpoint_uri=endpoint_uri, collection_name=EP_COSMOS_COLLECTION, database_name=EP_COSMOS_DATABASE
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

        # system assigned identity - pkn and default pkt
        self.cmd(
            "iot hub messaging-endpoint create cosmosdb-collection -n {} -g {} --en {} --erg {} --endpoint-uri {}  --identity [system] --auth-type identityBased --cn {} --dn {} --pkn {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1], EP_RG, endpoint_uri, EP_COSMOS_COLLECTION, EP_COSMOS_DATABASE, EP_COSMOS_PARTITION_PATH
            )
        )

        expected_sys_endpoint = build_expected_endpoint(
            endpoint_names[1], EP_RG, self.entity_sub, endpoint_uri=endpoint_uri, collection_name=EP_COSMOS_COLLECTION, database_name=EP_COSMOS_DATABASE, partition_key_name=EP_COSMOS_PARTITION_PATH, authentication_type="identityBased", partition_key_template=partition_template_default
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

        # user assigned identity - pkn and pkt
        self.kwargs["template"] = partition_template
        self.cmd(
            "iot hub messaging-endpoint create cosmosdb-collection -n {} -g {} --en {} --erg {} --endpoint-uri {}  --identity {} --auth-type identityBased --cn {} --dn {} --pkn {} --pkt {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2], EP_RG, endpoint_uri, self.user_identity_id, EP_COSMOS_COLLECTION, EP_COSMOS_DATABASE, EP_COSMOS_PARTITION_PATH, '{template}'
            )
        )

        expected_user_endpoint = build_expected_endpoint(
            endpoint_names[2], EP_RG, self.entity_sub, endpoint_uri=endpoint_uri, collection_name=EP_COSMOS_COLLECTION, database_name=EP_COSMOS_DATABASE, partition_key_name=EP_COSMOS_PARTITION_PATH, authentication_type="identityBased", partition_key_template=partition_template, identity=self.user_identity_id
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_user_endpoint)

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()

        cosmos_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "cosmosdb-collection"
            )
        ).get_output_in_json()

        assert len(cosmos_list) == 3
        assert endpoint_list["cosmosDbSqlCollections"] == cosmos_list

        # Delete one cosmos endpoint
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        )
        cosmos_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "cosmosdb-collection"
            )
        ).get_output_in_json()

        assert len(cosmos_list) == 2

        # Delete all cosmos endpoints
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "cosmosdb-collection"
            )
        )

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "cosmosdb-collection"
            )
        ).get_output_in_json()

        assert endpoint_list == []

    def test_iot_eventhub_endpoint_lifecycle(self):
        # Flag to ensure that event hub resources get deleted
        self.ran_eventhub = True
        endpoint_uri = f"sb://{EP_EVENTHUB_NAMESPACE}.servicebus.windows.net"
        eventhub_cs = self._create_eventhub()
        endpoint_names = self.generate_device_names(3)
        # use connection string - note how the connection string needs to have entity path and the
        # endpoint uri and path are left blank
        self.cmd(
            "iot hub messaging-endpoint create eventhub -n {} -g {} --en {} --erg {} -c {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0], EP_RG, eventhub_cs
            )
        )

        expected_cs_endpoint = build_expected_endpoint(
            endpoint_names[0], EP_RG, self.entity_sub, connection_string=eventhub_cs
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

        # Use hub identity
        self.cmd(
            "iot hub messaging-endpoint create eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity [system] --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[1], EP_RG, endpoint_uri, EP_EVENTHUB_INSTANCE
            )
        )

        expected_sys_endpoint = build_expected_endpoint(
            endpoint_names[1], EP_RG, self.entity_sub, entity_path=EP_EVENTHUB_INSTANCE, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[1]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

        # Use user identity
        self.cmd(
            "iot hub messaging-endpoint create eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} --identity {} --auth-type identityBased".format(
                self.entity_name, self.entity_rg, endpoint_names[2], EP_RG, endpoint_uri, EP_EVENTHUB_INSTANCE, self.user_identity_id
            )
        )

        expected_user_endpoint = build_expected_endpoint(
            endpoint_names[2], EP_RG, self.entity_sub, entity_path=EP_EVENTHUB_INSTANCE, authentication_type=AuthenticationType.IdentityBased.value, endpoint_uri=endpoint_uri, identity=self.user_identity_id
        )

        endpoint_output = self.cmd(
            "iot hub messaging-endpoint show -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[2]
            )
        ).get_output_in_json()

        assert_endpoint_properties(endpoint_output, expected_user_endpoint)

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()

        eventhub_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "eventhub"
            )
        ).get_output_in_json()

        assert len(eventhub_list) == 3
        assert endpoint_list["eventHubs"] == eventhub_list

        # Delete one event hub endpoint
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} --en {}".format(
                self.entity_name, self.entity_rg, endpoint_names[0]
            )
        )

        # ensure that only one got deleted
        eventhub_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "eventhub"
            )
        ).get_output_in_json()

        assert len(eventhub_list) == 2

        # Delete all event hub endpoints
        self.cmd(
            "iot hub messaging-endpoint delete -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "eventhub"
            )
        )

        endpoint_list = self.cmd(
            "iot hub messaging-endpoint list -n {} -g {} -t {}".format(
                self.entity_name, self.entity_rg, "eventhub"
            )
        ).get_output_in_json()

        assert endpoint_list == []


def build_expected_endpoint(
    name, resource_group, subscription_id, authentication_type=None, endpoint_uri=None, identity=None, connection_string=None, entity_path=None, container_name=None, encoding=None, file_name_format=None, batch_frequency_in_seconds=None, max_chunk_size_in_bytes=None, database_name=None, collection_name=None, partition_key_name=None, partition_key_template=None, primary_key=None, secondary_key=None
):
    expected = {
        "name": name,
        "resourceGroup": resource_group,
        "subscriptionId": subscription_id
    }

    if authentication_type:
        expected["authenticationType"] = authentication_type
    if endpoint_uri:
        expected["endpointUri"] = endpoint_uri
    if identity:
        expected["identity"] = {"userAssignedIdentity": identity}
    if connection_string:
        expected["connectionString"] = connection_string
    if entity_path:
        expected["entityPath"] = entity_path
    if container_name:
        expected["containerName"] = container_name
    if encoding:
        expected["encoding"] = encoding
    if file_name_format:
        expected["fileNameFormat"] = file_name_format
    if batch_frequency_in_seconds:
        expected["batchFrequencyInSeconds"] = batch_frequency_in_seconds
    if max_chunk_size_in_bytes:
        expected["maxChunkSizeInBytes"] = max_chunk_size_in_bytes
    if database_name:
        expected["databaseName"] = database_name
    if collection_name:
        expected["collectionName"] = collection_name
    if partition_key_name:
        expected["partitionKeyName"] = partition_key_name
    if partition_key_template:
        expected["partitionKeyTemplate"] = partition_key_template
    if primary_key:
        expected["primaryKey"] = primary_key
    if secondary_key:
        expected["secondaryKey"] = secondary_key

    return expected


def assert_endpoint_properties(result: dict, expected: dict):
    # Props that will always be populated
    assert result["name"] == expected["name"]
    assert result["resourceGroup"] == expected["resourceGroup"]
    assert result["subscriptionId"] == expected["subscriptionId"]
    assert result["id"]

    # Properties that may or may not be populated. Shared between all.
    if "authenticationType" in expected:
        assert result["authenticationType"] == expected["authenticationType"]
    if "endpointUri" in expected:
        assert result["endpointUri"] == expected["endpointUri"]
    if "identity" in expected:
        assert result["identity"]["userAssignedIdentity"] == expected["identity"]["userAssignedIdentity"]

    # Shared between all except Cosmos DB
    if "connectionString" in expected:
        result_cs_props = _parse_connection_string(result["connectionString"])
        expected_cs_props = _parse_connection_string(result["connectionString"])

        # keys will be masked - only check for existence in the result
        if expected_cs_props.get("SharedAccessKey"):
            # Service Bus and Event Hub
            expected_cs_props.pop("SharedAccessKey")
            assert "SharedAccessKey" in result_cs_props
        elif expected_cs_props.get("AccountKey"):
            # Storage Account
            expected_cs_props.pop("AccountKey")
            assert "AccountKey" in result_cs_props

        for prop in expected_cs_props:
            assert expected_cs_props[prop] == result_cs_props[prop]

    # Shared between Event Hub and Service Bus
    if "entityPath" in expected:
        assert result["entityPath"] == expected["entityPath"]

    # Storage Account only
    if "containerName" in expected:
        assert result["containerName"] == expected["containerName"]
    if "encoding" in expected:
        assert result["encoding"] == expected["encoding"]
    if "fileNameFormat" in expected:
        assert result["fileNameFormat"] == expected["fileNameFormat"]
    if "batchFrequencyInSeconds" in expected:
        assert result["batchFrequencyInSeconds"] == expected["batchFrequencyInSeconds"]
    if "maxChunkSizeInBytes" in expected:
        assert result["maxChunkSizeInBytes"] == expected["maxChunkSizeInBytes"]

    # Cosmos DB only
    if "databaseName" in expected:
        assert result["databaseName"] == expected["databaseName"]
    if "collectionName" in expected:
        assert result["collectionName"] == expected["collectionName"]
    if "partitionKeyName" in expected:
        assert result["partitionKeyName"] == expected["partitionKeyName"]
    if "partitionKeyTemplate" in expected:
        assert result["partitionKeyTemplate"] == expected["partitionKeyTemplate"]
    # keys will be masked
    if "primaryKey" in expected:
        assert result["primaryKey"]
    if "secondaryKey" in expected:
        assert result["secondaryKey"]
