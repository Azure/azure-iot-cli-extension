# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import Optional
import pytest
from azext_iot.common.utility import ensure_iothub_sdk_min_version
from azext_iot.iothub.common import AuthenticationType
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common._azure import _parse_connection_string, parse_cosmos_db_connection_string


cli = EmbeddedCLI()
pytestmark = pytest.mark.hub_infrastructure(
    sys_identity=True,
    user_identity=True,
    desired_tags="test=message_endpoint")


def generate_ep_names(count=1):
    names = [
        "ep" + generate_generic_id()[:10]
        for i in range(count)
    ]
    return names


def test_iot_eventhub_endpoint_lifecycle(provisioned_event_hub_with_identity_module):
    iot_hub_obj, event_hub_obj = provisioned_event_hub_with_identity_module

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]
    eventhub_instance = event_hub_obj["eventhub"]["name"]
    endpoint_uri = "sb:" + event_hub_obj["namespace"]["serviceBusEndpoint"].split(":")[1]
    eventhub_cs = event_hub_obj["connectionString"]
    endpoint_names = generate_ep_names(3)
    # use connection string - note how the connection string needs to have entity path and the
    # endpoint uri and path are left blank
    cli.invoke(
        "iot hub message-endpoint create eventhub -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, eventhub_cs
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[0], iot_rg, iot_sub, connection_string=eventhub_cs
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # Use hub identity
    cli.invoke(
        "iot hub message-endpoint create eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} "
        "--identity [system]".format(
            iot_hub, iot_rg, endpoint_names[1], iot_rg, endpoint_uri, eventhub_instance
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        entity_path=eventhub_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    )

    assert_endpoint_properties(endpoint_output.as_json(), expected_sys_endpoint)

    # Use user identity
    cli.invoke(
        "iot hub message-endpoint create eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} "
        "--identity {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            endpoint_uri,
            eventhub_instance,
            user_id
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg,
        iot_sub,
        entity_path=eventhub_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    )

    assert_endpoint_properties(endpoint_output.as_json(), expected_user_endpoint)

    # List

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {}".format(
            iot_hub, iot_rg
        )
    ).as_json()

    eventhub_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "eventhub"
        )
    ).as_json()

    assert len(eventhub_list) == 3
    assert endpoint_list["eventHubs"] == eventhub_list

    # Delete one event hub endpoint
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -y".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    )

    # ensure that only one got deleted
    eventhub_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "eventhub"
        )
    ).as_json()

    assert len(eventhub_list) == 2

    # Delete all event hub endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -t {} -y".format(
            iot_hub, iot_rg, "eventhub"
        )
    )

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "eventhub"
        )
    ).as_json()

    assert endpoint_list == []


def test_iot_servicebus_endpoint_lifecycle(provisioned_service_bus_with_identity_module):
    # this test covers two endpoint types
    iot_hub_obj, servicebus_obj = provisioned_service_bus_with_identity_module
    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]

    queue_instance = servicebus_obj["queue"]["name"]
    topic_instance = servicebus_obj["topic"]["name"]
    endpoint_uri = "sb:" + servicebus_obj["namespace"]["serviceBusEndpoint"].split(":")[1]
    queue_cs = servicebus_obj["queueConnectionString"]
    topic_cs = servicebus_obj["topicConnectionString"]
    # create 6 names, 2 types of service bus endpoints * 3 auth types
    endpoint_names = generate_ep_names(6)

    # create topic endpoint first - connection string
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, topic_cs
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[0], iot_rg, iot_sub, connection_string=topic_cs
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # topic - Use hub identity
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity [system]".format(
            iot_hub, iot_rg, endpoint_names[1], iot_rg, endpoint_uri, topic_instance
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg, iot_sub,
        entity_path=topic_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # topic - Use user identity
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            endpoint_uri,
            topic_instance,
            user_id
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg,
        iot_sub,
        entity_path=topic_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    # create queue endpoint - connection string
    cli.invoke(
        "iot hub message-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[3], iot_rg, queue_cs
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[3], iot_rg, iot_sub, connection_string=queue_cs
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[3]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # queue - Use hub identity
    cli.invoke(
        "iot hub message-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity [system]".format(
            iot_hub, iot_rg, endpoint_names[4], iot_rg, endpoint_uri, queue_instance
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[4],
        iot_rg,
        iot_sub,
        entity_path=queue_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[4]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # queue - Use user identity
    cli.invoke(
        "iot hub message-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[5],
            iot_rg,
            endpoint_uri,
            queue_instance,
            user_id
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[5],
        iot_rg,
        iot_sub,
        entity_path=queue_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[5]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    # list
    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {}".format(
            iot_hub, iot_rg
        )
    ).as_json()

    topic_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-topic"
        )
    ).as_json()

    assert len(topic_list) == 3
    assert endpoint_list["serviceBusTopics"] == topic_list

    queue_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-queue"
        )
    ).as_json()

    assert len(queue_list) == 3
    assert endpoint_list["serviceBusQueues"] == queue_list

    # Delete mismatch name and type
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -t {} -y".format(
            iot_hub, iot_rg, endpoint_names[0], "servicebus-queue"
        )
    )

    # ensure others are not deleted
    eventhub_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-topic"
        )
    ).as_json()

    assert len(eventhub_list) == 3

    queue_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-queue"
        )
    ).as_json()

    assert len(queue_list) == 3

    # Delete one (topic)
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -y".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    )

    # ensure others are not deleted
    eventhub_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-topic"
        )
    ).as_json()

    assert len(eventhub_list) == 2

    queue_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-queue"
        )
    ).as_json()

    assert len(queue_list) == 3

    # delete all queue
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -t {} -y".format(
            iot_hub, iot_rg, "servicebus-queue"
        )
    )

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-queue"
        )
    ).as_json()

    assert endpoint_list == []

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-topic"
        )
    ).as_json()

    assert len(endpoint_list) == 2

    # delete all
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y".format(
            iot_hub, iot_rg
        )
    )

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "servicebus-topic"
        )
    ).as_json()

    assert endpoint_list == []


def test_iot_storage_endpoint_lifecycle(provisioned_storage_with_identity_module):
    iot_hub_obj, storage_obj = provisioned_storage_with_identity_module

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]

    endpoint_names = generate_ep_names(3)
    storage_cs = storage_obj["connectionString"]
    endpoint_uri = storage_obj["storage"]["primaryEndpoints"]["blob"]
    container_name = storage_obj["container"]["name"]
    default_file_format = "{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}"
    # use connection string - note how the connection string needs to have entity path and the
    # endpoint uri and path are left blank
    cli.invoke(
        "iot hub message-endpoint create storage-container -n {} -g {} --en {} --erg {} -c {} --container {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, storage_cs, container_name
        )
    )

    # use defaults
    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[0],
        iot_rg,
        iot_sub,
        connection_string=storage_cs,
        container_name=container_name,
        batch_frequency_in_seconds=300,
        encoding="avro",
        file_name_format=default_file_format,
        max_chunk_size_in_bytes=300
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # Use hub identity with no defaults
    custom_file_format = default_file_format.replace("/", "_")
    cli.invoke(
        "iot hub message-endpoint create storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} "
        "--identity [system] -b {} -w {} --encoding {} --ff {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[1],
            iot_rg, endpoint_uri,
            container_name,
            60,
            10,
            "json",
            custom_file_format
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        container_name=container_name,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        batch_frequency_in_seconds=60,
        encoding="json",
        file_name_format=custom_file_format,
        max_chunk_size_in_bytes=10
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # Use user identity
    cli.invoke(
        "iot hub message-endpoint create storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} "
        "--identity {} -b {} -w {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            endpoint_uri,
            container_name,
            user_id,
            720,
            500
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg,
        iot_sub,
        container_name=container_name,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id,
        batch_frequency_in_seconds=720,
        encoding="avro",
        file_name_format=default_file_format,
        max_chunk_size_in_bytes=500
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {}".format(
            iot_hub, iot_rg
        )
    ).as_json()

    storage_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "storage-container"
        )
    ).as_json()

    assert len(storage_list) == 3
    assert endpoint_list["storageContainers"] == storage_list

    # Delete one event hub endpoint
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -y".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    )

    # ensure that only one got deleted
    storage_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "storage-container"
        )
    ).as_json()

    assert len(storage_list) == 2

    # Delete all event hub endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -t {} -y".format(
            iot_hub, iot_rg, "storage-container"
        )
    )

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "storage-container"
        )
    ).as_json()

    assert endpoint_list == []


@pytest.mark.skipif(not ensure_iothub_sdk_min_version("2.3.0"), reason="Cosmos Db Endpoints requires azure-mgmt-iothub>=2.3.0.")
def test_iot_cosmos_endpoint_lifecycle(provisioned_cosmosdb_with_identity_module):
    iot_hub_obj, cosmosdb_obj = provisioned_cosmosdb_with_identity_module

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]

    cosmos_cstring = cosmosdb_obj["connectionString"]
    database = cosmosdb_obj["database"]["name"]
    container = cosmosdb_obj["container"]["name"]
    endpoint_names = generate_ep_names(3)
    partition_template = "{iothub}-{device_id}-{DD}-{MM}-{YYYY}"
    partition_template_default = "{deviceid}-{YYYY}-{MM}"
    partition_path = "example"
    # use connection string - no pkn or pkt
    cli.invoke(
        "iot hub message-endpoint create cosmosdb-container -n {} -g {} --en {} --erg {} -c {} --container {} "
        "--db {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[0],
            iot_rg,
            cosmos_cstring,
            container,
            database
        )
    )

    parsed_cs = parse_cosmos_db_connection_string(cosmos_cstring)
    endpoint_uri = parsed_cs["AccountEndpoint"]
    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[0],
        iot_rg,
        iot_sub,
        primary_key=parsed_cs["AccountKey"],
        secondary_key=parsed_cs["AccountKey"],
        endpoint_uri=endpoint_uri,
        container_name=container,
        database_name=database
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # system assigned identity - pkn and default pkt
    cli.invoke(
        "iot hub message-endpoint create cosmosdb-container -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--identity [system] --container {} --db {} --pkn {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[1],
            iot_rg,
            endpoint_uri,
            container,
            database,
            partition_path
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        endpoint_uri=endpoint_uri,
        container_name=container,
        database_name=database,
        partition_key_name=partition_path,
        authentication_type=AuthenticationType.IdentityBased.value,
        partition_key_template=partition_template_default
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # user assigned identity - pkn and pkt
    cli.invoke(
        "iot hub message-endpoint create cosmosdb-container -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--identity {} --container {} --db {} --pkn {} --pkt {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            endpoint_uri,
            user_id,
            container,
            database,
            partition_path,
            partition_template
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg,
        iot_sub,
        endpoint_uri=endpoint_uri,
        container_name=container,
        database_name=database,
        partition_key_name=partition_path,
        authentication_type=AuthenticationType.IdentityBased.value,
        partition_key_template=partition_template,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {}".format(
            iot_hub, iot_rg
        )
    ).as_json()

    cosmos_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "cosmosdb-container"
        )
    ).as_json()

    assert len(cosmos_list) == 3
    assert endpoint_list["cosmosDbSqlcontainers"] == cosmos_list

    # Delete one cosmos endpoint
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -y".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    )
    cosmos_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "cosmosdb-container"
        )
    ).as_json()

    assert len(cosmos_list) == 2

    # Delete all cosmos endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -t {} -y".format(
            iot_hub, iot_rg, "cosmosdb-container"
        )
    )

    endpoint_list = cli.invoke(
        "iot hub message-endpoint list -n {} -g {} -t {}".format(
            iot_hub, iot_rg, "cosmosdb-container"
        )
    ).as_json()

    assert endpoint_list == []


def build_expected_endpoint(
    name: str,
    resource_group: str,
    subscription_id: str,
    authentication_type: str = AuthenticationType.KeyBased.value,
    endpoint_uri: Optional[str] = None,
    identity: Optional[str] = None,
    connection_string: Optional[str] = None,
    entity_path: Optional[str] = None,
    container_name: Optional[str] = None,
    encoding: Optional[str] = None,
    file_name_format: Optional[str] = None,
    batch_frequency_in_seconds: Optional[int] = None,
    max_chunk_size_in_bytes: Optional[int] = None,
    database_name: Optional[str] = None,
    partition_key_name: Optional[str] = None,
    partition_key_template: Optional[str] = None,
    primary_key: Optional[str] = None,
    secondary_key: Optional[str] = None
):
    expected = {
        "name": name,
        "resourceGroup": resource_group,
        "subscriptionId": subscription_id,
        "authenticationType": authentication_type
    }

    if endpoint_uri:
        expected["endpointUri"] = endpoint_uri
    if identity:
        expected["identity"] = {"userAssignedIdentity": identity}
    if connection_string:
        expected["connectionString"] = connection_string
    if entity_path:
        expected["entityPath"] = entity_path
    if container_name and not database_name:
        # storage container
        expected["containerName"] = container_name
    if encoding:
        expected["encoding"] = encoding
    if file_name_format:
        expected["fileNameFormat"] = file_name_format
    if batch_frequency_in_seconds:
        expected["batchFrequencyInSeconds"] = batch_frequency_in_seconds
    if max_chunk_size_in_bytes:
        max_chunk_size_constant = 1048576
        expected["maxChunkSizeInBytes"] = max_chunk_size_in_bytes * max_chunk_size_constant
    if database_name:
        expected["databaseName"] = database_name
    if container_name and database_name:
        # cosmosdb container
        expected["collectionName"] = container_name
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
    assert result["authenticationType"] == expected["authenticationType"]

    # Properties that may or may not be populated. Shared between all.
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
