# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings
from azext_iot.tests.generators import generate_generic_id
from typing import List, Tuple, Optional, Dict, Any
from knack.log import get_logger

logger = get_logger(__name__)


cli = EmbeddedCLI()


REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)

RG = settings.env.azext_iot_testrg


def generate_hub_id() -> str:
    return f"test-hub-{generate_generic_id()}"[:40]


def generate_hub_depenency_id() -> str:
    return f"testhubdep{generate_generic_id()}"[:24]


def tags_to_dict(tags: str) -> dict:
    result = {}
    split_tags = tags.split()
    for tag in split_tags:
        kvp = tag.split("=")
        result[kvp[0]] = kvp[1]
    return result


@pytest.fixture(scope="session")
def provisioned_iot_hub_session(request, provisioned_user_identity_session) -> Optional[dict]:
    print("provisioned_iot_hub_session")
    result = _iot_hub_provisioner(request, provisioned_user_identity_session)
    yield result
    if result:
        _iot_hub_removal(result["name"])


@pytest.fixture
def provisioned_iot_hub(request) -> Optional[dict]:
    result = _iot_hub_provisioner(request)
    yield result
    if result:
        _iot_hub_removal(result["name"])

def _iot_hub_provisioner(request, provisioned_user_identity):
    print("_iot_hub_provisioner")
    print(request)
    name = generate_hub_id()
    base_create_command = f"iot hub create -n {name} -g {RG} --sku S1"
    print(f"hub is {name} in {RG}")

    hub_marker = request.node.get_closest_marker("hub_infrastructure")
    import pdb; pdb.set_trace()
    desired_location = None
    desired_tags = None
    desired_sys_identity = True
    desired_user_identity = True
    desired_assign_data_user_role = None

    if hub_marker:
        print("found the marker")
        desired_location = hub_marker.kwargs.get("location")
        desired_tags = hub_marker.kwargs.get("tags")
        desired_sys_identity = hub_marker.kwargs.get("sys_identity")
        desired_user_identity = hub_marker.kwargs.get("user_identity")

    if desired_sys_identity:
        base_create_command += " --mi-system-assigned"
    if desired_user_identity and provisioned_user_identity:
        user_identity_id = provisioned_user_identity["id"]
        base_create_command += f" --mi-user-assigned {user_identity_id}"
    if desired_tags:
        base_create_command = base_create_command + f" --tags {desired_tags}"
    if desired_location:
        base_create_command = base_create_command + f" -l {desired_location}"
    print(base_create_command)
    # import pdb; pdb.set_trace()

    result = cli.invoke(base_create_command).as_json()
    print(result)
    print(result["properties"]["state"])
    if result["properties"]["state"].lower() != "active":
        print("sleeping")
        sleep(10)
    return result


def _iot_hub_removal(name):
    print("_iot_hub_removal")
    delete_result = cli.invoke(f"iot hub delete -n {name} -g {RG}")
    if not delete_result.success():
        logger.error(f"Failed to delete iot hub resource {name}.")

@pytest.fixture(scope="session")
def provisioned_user_identity_session(request) -> Optional[dict]:
    print("provisioned_user_identity_session")
    result = _user_identity_provisioner(request)
    yield result
    if result:
        _user_identity_removal(result["name"])


@pytest.fixture
def provisioned_user_identity(request) -> Optional[dict]:
    print("provisioned_user_identity")
    result = _user_identity_provisioner(request)
    yield result
    if result:
        _user_identity_removal(result["name"])

def _user_identity_provisioner(request):
    print("_user_identity_provisioner")
    print( request.node.get_closest_marker("hub_infrastructure"))
    import pdb; pdb.set_trace()
    name = generate_hub_depenency_id()
    return cli.invoke(
        f"identity create -n {name} -g {RG}"
    ).as_json()

def _get_role_assignments(scope, role):
    return cli.invoke(
        f'role assignment list --scope "{scope}" --role "{role}"'
    ).as_json()


def _user_identity_removal(name):
    delete_result = cli.invoke(f"identity delete -n {name} -g {RG}")
    if not delete_result.success():
        logger.error(f"Failed to delete user identity resource {name}.")

def _assign_rbac_role(assignee: str, scope: str, role: str, max_tries: int = 10):
    print("_assign_rbac_role")
    print(assignee, scope, role)
    tries = 0
    while tries < max_tries:
        role_assignments = _get_role_assignments(scope, role)
        role_assignment_principal_ids = [assignment["principalId"] for assignment in role_assignments]
        if assignee in role_assignment_principal_ids:
            break
        # else assign role to scope and check again
        cli.invoke(
            'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                assignee, role, scope
            )
        )
        sleep(10)
        tries += 1

# @pytest.fixture(scope="session")
# def provisioned_storage_session(request) -> Optional[dict]:
#     result = _storage_provisioner(request)
#     yield result
#     if result:
#         _storage_removal(result)


# @pytest.fixture
# def provisioned_storage(request) -> Optional[dict]:
#     result = _storage_provisioner(request)
#     yield result
#     if result:
#         _storage_removal(result["name"])


# def _storage_get_cstring(account_name):
#     return cli.invoke(
#         "storage account show-connection-string -n {} -g {}".format(
#             account_name, RG
#         )
#     ).as_json()["connectionString"]


# def _storage_provisioner(resource_name):
#     """
#     Create a storage account (if needed) and container and return storage connection string.
#     """
#     account_name = generate_hub_depenency_id()
#     container_name = generate_hub_depenency_id()

#     storage_list = cli.invoke(
#         'storage account list -g "{}"'.format(RG)
#     ).as_json()

#     target_storage = None
#     for storage in storage_list:
#         if storage["name"] == account_name:
#             target_storage = storage
#             break

#     if not target_storage:
#         target_storage = cli.invoke(
#             "storage account create -n {} -g {} --tags iot_resource={}".format(
#                 account_name, RG, resource_name
#             )
#         ).as_json()

#     storage_cstring = _storage_get_cstring(account_name)

#     # Will not do anything if container exists.
#     cli.invoke(
#         "storage container create -n {} --connection-string '{}'".format(
#             container_name, storage_cstring
#         ),
#     )

#     return target_storage


# def _storage_removal(account_name: str):
#     delete_result = cli.invoke(f"storage account delete -g {RG} -n {account_name} -y")
#     if not delete_result.success():
#         logger.error(f"Failed to delete storage account resource {account_name}.")


@pytest.fixture(scope="session")
def provisioned_event_hub_with_identity_session(request, provisioned_iot_hub_session, provisioned_event_hub_session):
    print()
    print("provisioned_event_hub_with_identity_session")
    print( request.node.get_closest_marker("hub_infrastructure"))
    # import pdb; pdb.set_trace()
    role = "Azure Event Hubs Data Sender"
    scope = provisioned_event_hub_session["eventhub"]["id"]
    hub_principal_id = provisioned_iot_hub_session["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_session["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    print("adding roles")
    _assign_rbac_role(assignee=hub_principal_id, scope=scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=scope, role=role)
    yield provisioned_iot_hub_session, provisioned_event_hub_session



@pytest.fixture(scope="session")
def provisioned_event_hub_session(request) -> Optional[list]:
    print("provisioned_event_hub_session")
    result = _event_hub_provisioner(request)
    yield result
    if result:
        _event_hub_removal(result["namespace"]["name"])


@pytest.fixture
def provisioned_event_hub(request) -> Optional[list]:
    result = _event_hub_provisioner(request)
    yield result
    if result:
        _event_hub_removal(result["namespace"]["name"])


def _event_hub_get_cstring(namespace_name, eventhub_name, policy_name):
    return cli.invoke(
        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
        "--eventhub-name {} --name {}".format(
            namespace_name, RG, eventhub_name, policy_name
        )
    ).as_json()["primaryConnectionString"]


def _event_hub_provisioner(request):
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    namespace_name = generate_hub_depenency_id()
    eventhub_name = generate_hub_depenency_id()
    policy_name = generate_hub_depenency_id()
    print("_event_hub_provisioner stuff")
    print( request.node.get_closest_marker("hub_infrastructure"))
    print(namespace_name, eventhub_name, policy_name)
    namespace_obj = cli.invoke(
        "eventhubs namespace create --name {} --resource-group {}".format(
            namespace_name, RG
        )
    ).as_json()

    eventhub_obj = cli.invoke(
        "eventhubs eventhub create --namespace-name {} --resource-group {} --name {}".format(
            namespace_name, RG, eventhub_name
        )
    ).as_json()

    policy_obj = cli.invoke(
        "eventhubs eventhub authorization-rule create --namespace-name {} --resource-group {} "
        "--eventhub-name {} --name {} --rights Send".format(
            namespace_name, RG, eventhub_name, policy_name
        )
    ).as_json()
    return {
        "namespace": namespace_obj,
        "eventhub": eventhub_obj,
        "policy": policy_obj,
        "connectionString": _event_hub_get_cstring(namespace_name, eventhub_name, policy_name)
    }


def _event_hub_removal(account_name: str):
    delete_result = cli.invoke(f"eventhubs namespace delete -g {RG} -n {account_name}")
    if not delete_result.success():
        logger.error(f"Failed to delete eventhubs namespace resource {account_name}.")


@pytest.fixture(scope="session")
def provisioned_service_bus_with_identity_session(request, provisioned_iot_hub_session, provisioned_service_bus_session):
    print()
    print("provisioned_service_bus_with_identity_session")
    print( request.node.get_closest_marker("hub_infrastructure"))
    # import pdb; pdb.set_trace()
    role = "Azure Service Bus Data Sender"
    queue_scope = provisioned_service_bus_session["queue"]["id"]
    topic_scope = provisioned_service_bus_session["topic"]["id"]
    hub_principal_id = provisioned_iot_hub_session["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_session["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    print("adding roles")
    _assign_rbac_role(assignee=hub_principal_id, scope=queue_scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=queue_scope, role=role)
    _assign_rbac_role(assignee=hub_principal_id, scope=topic_scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=topic_scope, role=role)
    # sleep(30)
    yield provisioned_iot_hub_session, provisioned_service_bus_session


@pytest.fixture(scope="session")
def provisioned_service_bus_session(request) -> Optional[list]:
    result = _service_bus_provisioner(request)
    yield result
    if result:
        _service_bus_removal(result["namespace"]["name"])


@pytest.fixture
def provisioned_service_bus(request) -> Optional[list]:
    result = _service_bus_provisioner(request)
    yield result
    if result:
        _service_bus_removal(result["namespace"]["name"])


def _service_bus_topic_get_cstring(namespace_name, eventhub_name, policy_name):
    return cli.invoke(
        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
        "--topic-name {} --name {}".format(
            namespace_name, RG, eventhub_name, policy_name
        )
    ).as_json()["primaryConnectionString"]


def _service_bus_queue_get_cstring(namespace_name, eventhub_name, policy_name):
    return cli.invoke(
        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
        "--queue-name {} --name {}".format(
            namespace_name, RG, eventhub_name, policy_name
        )
    ).as_json()["primaryConnectionString"]


def _service_bus_provisioner(request):
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    namespace_name = generate_hub_depenency_id()
    queue_name = generate_hub_depenency_id()
    topic_name = generate_hub_depenency_id()
    policy_name = generate_hub_depenency_id()
    print("service bus stuff")
    print("_service_bus_provisioner")

    print( request.node.get_closest_marker("hub_infrastructure"))
    namespace_obj = cli.invoke(
        "servicebus namespace create --name {} --resource-group {}".format(
            namespace_name, RG
        )
    ).as_json()

    queue_obj = cli.invoke(
        "servicebus queue create --namespace-name {} --resource-group {} --name {}".format(
            namespace_name, RG, queue_name
        )
    ).as_json()

    queue_policy = cli.invoke(
        "servicebus queue authorization-rule create --namespace-name {} --resource-group {} "
        "--queue-name {} --name {} --rights Send".format(
            namespace_name, RG, queue_name, policy_name
        )
    ).as_json()

    topic_obj = cli.invoke(
        "servicebus topic create --namespace-name {} --resource-group {} --name {}".format(
            namespace_name, RG, topic_name
        )
    ).as_json()

    topic_policy = cli.invoke(
        "servicebus topic authorization-rule create --namespace-name {} --resource-group {} "
        "--topic-name {} --name {} --rights Send".format(
            namespace_name, RG, topic_name, policy_name
        )
    ).as_json()

    return {
        "namespace": namespace_obj,
        "queue": queue_obj,
        "queuePolicy": queue_policy,
        "queueConnectionString": _service_bus_queue_get_cstring(namespace_name, queue_name, policy_name),
        "topic": topic_obj,
        "topicPolicy": topic_policy,
        "topicConnectionString": _service_bus_topic_get_cstring(namespace_name, topic_name, policy_name),
    }

def _service_bus_removal(account_name: str):
    delete_result = cli.invoke(f"servicebus namespace delete -g {RG} -n {account_name}")
    if not delete_result.success():
        logger.error(f"Failed to delete servicebus namespace resource {account_name}.")



# @pytest.fixture(scope="session")
# def provisioned_cosmos_db_session(request) -> Optional[list]:
#     result = _cosmos_db_provisioner(request)
#     yield result
#     if result:
#         _cosmos_db_removal(result[0])

# @pytest.fixture
# def provisioned_cosmos_db(request) -> Optional[list]:
#     result = _cosmos_db_provisioner(request)
#     yield result
#     if result:
#         _cosmos_db_removal(result[0])


# def _cosmos_db_get_cstring(account_name, database_name, collection_name):
#     return cli.invoke(
#         "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
#         "--eventhub-name {} --name {}".format(
#             account_name, RG, database_name, collection_name
#         )
#     ).as_json()["primaryConnectionString"]


# def _cosmos_db_provisioner(resource_name):
#     """
#     Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
#     """
#     account_name = generate_hub_depenency_id()
#     database_name = generate_hub_depenency_id()
#     collection_name = generate_hub_depenency_id()
#     partition_key_path = "/test"
#     cli.invoke(
#         "cosmosdb create --name {} --resource-group {} --tags iotresource={}".format(
#             account_name, RG, resource_name
#         )
#     )

#     cli.invoke(
#         "cosmosdb sql database create --namespace-name {} --resource-group {} --name {}".format(
#             account_name, RG, database_name
#         )
#     )

#     cli.invoke(
#         "cosmosdb sql container create --resource-group {} --account-name {} --database-name {} --name {} -p {}".format(
#             account_name, RG, database_name, collection_name, partition_key_path
#         )
#     )
#     return account_name, database_name, collection_name

# def _cosmos_db_removal(account_name: str):
#     delete_result = cli.invoke(f"eventhubs namespace delete -g {RG} -n {account_name} -y")
#     if not delete_result.success():
#         logger.error(f"Failed to delete eventhubs namespace resource {account_name}.")
