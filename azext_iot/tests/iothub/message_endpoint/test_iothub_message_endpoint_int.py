# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
import pytest
from azure.cli.core.azclierror import BadRequestError
from azext_iot.common.utility import ensure_iothub_sdk_min_version
from azext_iot.iothub.common import AuthenticationType, RouteSourceType
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
    iot_hub_objs, event_hub_obj = provisioned_event_hub_with_identity_module
    iot_hub_obj = iot_hub_objs[0]["hub"]

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]
    eventhub_instance = event_hub_obj["eventhub"]["name"]
    endpoint_uri = "sb:" + event_hub_obj["namespace"]["serviceBusEndpoint"].split(":")[1]
    eventhub_cs = event_hub_obj["connectionString"]
    endpoint_names = generate_ep_names(3)
    # Ensure there are no endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y -f".format(
            iot_hub, iot_rg
        )
    )

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

    # Update
    # Keybased -> System
    cli.invoke(
        "iot hub message-endpoint update eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} "
        "--identity [system]".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, endpoint_uri, eventhub_instance
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[0],
        iot_rg,
        iot_sub,
        entity_path=eventhub_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # System -> User
    cli.invoke(
        "iot hub message-endpoint update eventhub -n {} -g {} --en {} --erg {} --endpoint-uri {} --entity-path {} "
        "--identity {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[1],
            iot_rg,
            endpoint_uri,
            eventhub_instance,
            user_id
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        entity_path=eventhub_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    )

    assert_endpoint_properties(endpoint_output.as_json(), expected_user_endpoint)

    # User -> Keybased
    cli.invoke(
        "iot hub message-endpoint update eventhub -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[2], iot_rg, eventhub_cs
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[2], iot_rg, iot_sub, connection_string=eventhub_cs
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    )

    assert_endpoint_properties(endpoint_output.as_json(), expected_cs_endpoint)

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
    iot_hub_objs, servicebus_obj = provisioned_service_bus_with_identity_module
    iot_hub_obj = iot_hub_objs[0]["hub"]

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]
    # Ensure there are no endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y -f".format(
            iot_hub, iot_rg
        )
    )

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

    # Update
    # Keybased -> User Queue
    cli.invoke(
        "iot hub message-endpoint update servicebus-queue -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[3],
            iot_rg,
            endpoint_uri,
            queue_instance,
            user_id
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[3],
        iot_rg,
        iot_sub,
        entity_path=queue_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[3]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    # User -> System Topic
    cli.invoke(
        "iot hub message-endpoint update servicebus-topic -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--entity-path {} --identity [system]".format(
            iot_hub, iot_rg, endpoint_names[2], iot_rg, endpoint_uri, topic_instance
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg, iot_sub,
        entity_path=topic_instance,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_sys_endpoint)

    # System -> Keybased Topic
    cli.invoke(
        "iot hub message-endpoint update servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[1], iot_rg, topic_cs
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[1], iot_rg, iot_sub, connection_string=topic_cs
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

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
    iot_hub_objs, storage_obj = provisioned_storage_with_identity_module
    iot_hub_obj = iot_hub_objs[0]["hub"]

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]
    # Ensure there are no endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y -f".format(
            iot_hub, iot_rg
        )
    )

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

    # List
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

    # Update
    # Keybased -> System, change all optional props
    cli.invoke(
        "iot hub message-endpoint update storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} "
        "--identity [system] -b {} -w {} --ff {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[0],
            iot_rg,
            endpoint_uri,
            container_name,
            100,
            50,
            custom_file_format
        )
    )

    # use defaults
    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[0],
        iot_rg,
        iot_sub,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        container_name=container_name,
        batch_frequency_in_seconds=100,
        encoding="avro",
        file_name_format=custom_file_format,
        max_chunk_size_in_bytes=50
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # System -> User, change some optional props
    custom_file_format = default_file_format.replace("/", "_")
    cli.invoke(
        "iot hub message-endpoint update storage-container -n {} -g {} --en {} --erg {} --endpoint-uri {} --container {} "
        "--identity {} -b {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[1],
            iot_rg, endpoint_uri,
            container_name,
            user_id,
            70,
        )
    )

    expected_sys_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        container_name=container_name,
        authentication_type=AuthenticationType.IdentityBased.value,
        endpoint_uri=endpoint_uri,
        identity=user_id,
        batch_frequency_in_seconds=70,
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

    # User -> Keybased, change no optional props
    cli.invoke(
        "iot hub message-endpoint update storage-container -n {} -g {} --en {} --erg {} --container {} "
        "-c {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            container_name,
            storage_cs,
        )
    )

    expected_user_endpoint = build_expected_endpoint(
        endpoint_names[2],
        iot_rg,
        iot_sub,
        connection_string=storage_cs,
        container_name=container_name,
        authentication_type=AuthenticationType.KeyBased.value,
        endpoint_uri=None,
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
    iot_hub_objs, cosmosdb_obj = provisioned_cosmosdb_with_identity_module
    iot_hub_obj = iot_hub_objs[0]["hub"]

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    iot_sub = iot_hub_obj["subscriptionid"]
    user_id = list(iot_hub_obj["identity"]["userAssignedIdentities"].keys())[0]
    # Ensure there are no endpoints
    cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y -f".format(
            iot_hub, iot_rg
        )
    )

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

    # List
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
    assert endpoint_list["cosmosDbSqlCollections"] == cosmos_list

    # Update
    # Keybased -> User, add pkn + pkt
    cli.invoke(
        "iot hub message-endpoint update cosmosdb-container -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--identity {} --container {} --db {} --pkn {} --pkt {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[0],
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
        endpoint_names[0],
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
            iot_hub, iot_rg, endpoint_names[0]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

    # System -> Keybased, keep
    cli.invoke(
        "iot hub message-endpoint update cosmosdb-container -n {} -g {} --en {} --erg {} -c {} --container {} "
        "--db {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[1],
            iot_rg,
            cosmos_cstring,
            container,
            database
        )
    )

    expected_cs_endpoint = build_expected_endpoint(
        endpoint_names[1],
        iot_rg,
        iot_sub,
        primary_key=parsed_cs["AccountKey"],
        secondary_key=parsed_cs["AccountKey"],
        endpoint_uri=endpoint_uri,
        container_name=container,
        database_name=database,
        partition_key_name=partition_path,
        partition_key_template=partition_template_default
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[1]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_cs_endpoint)

    # User -> System, remove pkn, pkt
    cli.invoke(
        "iot hub message-endpoint update cosmosdb-container -n {} -g {} --en {} --erg {} --endpoint-uri {} "
        "--identity [system] --container {} --db {} --pkn {} --pkt {}".format(
            iot_hub,
            iot_rg,
            endpoint_names[2],
            iot_rg,
            endpoint_uri,
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
        partition_key_name=None,
        authentication_type=AuthenticationType.IdentityBased.value,
        partition_key_template=None,
    )

    endpoint_output = cli.invoke(
        "iot hub message-endpoint show -n {} -g {} --en {}".format(
            iot_hub, iot_rg, endpoint_names[2]
        )
    ).as_json()

    assert_endpoint_properties(endpoint_output, expected_user_endpoint)

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


def test_iot_endpoint_force_delete(provisioned_service_bus_with_identity_module):
    # this test covers two endpoint types
    iot_hub_objs, servicebus_obj = provisioned_service_bus_with_identity_module
    iot_hub_obj = iot_hub_objs[0]["hub"]

    iot_hub = iot_hub_obj["name"]
    iot_rg = iot_hub_obj["resourcegroup"]
    queue_cs = servicebus_obj["queueConnectionString"]
    topic_cs = servicebus_obj["topicConnectionString"]
    built_in_endpoint = "events"

    # Create 2 topic, 2 queue endpoints
    endpoint_names = generate_ep_names(3)

    # Route names, one for each endpoint + built in
    route_names = generate_ep_names(4)

    # Enrichment keys, one for each endpoint + built in
    enrichment_keys = generate_ep_names(4)

    # Create route and message enrichment for builtin endpoint
    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[-1], built_in_endpoint, RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, built_in_endpoint, enrichment_keys[-1], generate_generic_id()
        )
    )

    # create topic endpoint first - connection string, add route and message enrichment
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, topic_cs
        )
    )

    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[0], endpoint_names[0], RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, endpoint_names[0], enrichment_keys[0], generate_generic_id()
        )
    )

    # try delete with name without force
    with pytest.raises(BadRequestError):
        cli.invoke(
            "iot hub message-endpoint delete -n {} -g {} --en {} -y".format(
                iot_hub, iot_rg, endpoint_names[0],
            ),
            capture_stderr=True
        )

    # delete with name force
    delete_result = cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} --en {} -y -f".format(
            iot_hub, iot_rg, endpoint_names[0],
        )
    )
    assert delete_result.success()

    # ensure built in is not deleted
    route_list = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(route_list) == 1
    assert route_list[0]["name"] == route_names[-1]

    enrichment_list = cli.invoke(
        "iot hub message-enrichment list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(enrichment_list) == 1
    assert enrichment_list[0]["key"] == enrichment_keys[-1]

    # Recreate topic endpoint
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, topic_cs
        )
    )

    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[0], endpoint_names[0], RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, endpoint_names[0], enrichment_keys[0], generate_generic_id()
        )
    )

    # Create queue endpoint
    cli.invoke(
        "iot hub message-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[1], iot_rg, queue_cs
        )
    )

    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[1], endpoint_names[1], RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, endpoint_names[1], enrichment_keys[1], generate_generic_id()
        )
    )

    # delete by endpoint type without force
    with pytest.raises(BadRequestError):
        cli.invoke(
            "iot hub message-endpoint delete -n {} -g {} -t {} -y".format(
                iot_hub, iot_rg, "servicebus-topic",
            ),
            capture_stderr=True
        )

    # delete by endpoint type with force
    delete_result = cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -t {} -y -f".format(
            iot_hub, iot_rg, "servicebus-topic",
        )
    )
    assert delete_result.success()

    # ensure only servicebus topic route and message enrichment are deleted
    route_list = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(route_list) == 2
    route_list_names = [r["name"] for r in route_list]
    assert route_names[-1] in route_list_names
    assert route_names[1] in route_list_names

    enrichment_list = cli.invoke(
        "iot hub message-enrichment list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(enrichment_list) == 2
    enrichment_list_names = [r["key"] for r in enrichment_list]
    assert enrichment_keys[-1] in enrichment_list_names
    assert enrichment_keys[1] in enrichment_list_names

    # Recreate topic endpoint
    cli.invoke(
        "iot hub message-endpoint create servicebus-topic -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[0], iot_rg, topic_cs
        )
    )

    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[0], endpoint_names[0], RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, endpoint_names[0], enrichment_keys[0], generate_generic_id()
        )
    )

    # Create secondary queue endpoint
    cli.invoke(
        "iot hub message-endpoint create servicebus-queue -n {} -g {} --en {} --erg {} -c {}".format(
            iot_hub, iot_rg, endpoint_names[2], iot_rg, queue_cs
        )
    )

    cli.invoke(
        "iot hub message-route create -n {} -g {} --rn {} --en {} -t {}".format(
            iot_hub, iot_rg, route_names[2], endpoint_names[2], RouteSourceType.DeviceMessages.value
        )
    )

    cli.invoke(
        "iot hub message-enrichment create -n {} -g {} -e {} -k {} -v {}".format(
            iot_hub, iot_rg, endpoint_names[2], enrichment_keys[2], generate_generic_id()
        )
    )

    # delete all endpoints without force

    with pytest.raises(BadRequestError):
        cli.invoke(
            "iot hub message-endpoint delete -n {} -g {} -y".format(
                iot_hub, iot_rg,
            ),
            capture_stderr=True
        )

    # delete all endpoints with force
    delete_result = cli.invoke(
        "iot hub message-endpoint delete -n {} -g {} -y -f".format(
            iot_hub, iot_rg,
        )
    )
    assert delete_result.success()

    # ensure built in is not deleted
    route_list = cli.invoke(
        "iot hub message-route list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(route_list) == 1
    assert route_list[0]["name"] == route_names[-1]

    enrichment_list = cli.invoke(
        "iot hub message-enrichment list -n {} -g {}".format(
            iot_hub, iot_rg,
        )
    ).as_json()

    assert len(enrichment_list) == 1
    assert enrichment_list[0]["key"] == enrichment_keys[-1]


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
    # assert result["id"] # TODO @vilit should cosmos db endpoint return this as None
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
