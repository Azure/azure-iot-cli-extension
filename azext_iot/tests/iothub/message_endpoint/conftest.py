# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.helpers import get_closest_marker
from azext_iot.tests.iothub import generate_hub_depenency_id, generate_hub_id
from azext_iot.tests.settings import DynamoSettings
from typing import Optional
from knack.log import get_logger

logger = get_logger(__name__)
cli = EmbeddedCLI()
REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)
RG = settings.env.azext_iot_testrg


# IoT Hub fixtures
@pytest.fixture(scope="module")
def provisioned_iot_hub_module(request, provisioned_user_identity_module) -> Optional[dict]:
    result = _iot_hub_provisioner(request, provisioned_user_identity_module)
    yield result
    if result:
        _iot_hub_removal(result["name"])


@pytest.fixture(scope="module")
def provisioned_only_iot_hub_module(request) -> Optional[dict]:
    result = _iot_hub_provisioner(request)
    yield result
    if result:
        _iot_hub_removal(result["name"])


def _iot_hub_provisioner(request, provisioned_user_identity=None):
    name = generate_hub_id()
    base_create_command = f"iot hub create -n {name} -g {RG} --sku S1"

    hub_marker = get_closest_marker(request)
    desired_location = None
    desired_tags = None
    desired_sys_identity = False
    desired_user_identity = False

    if hub_marker:
        desired_location = hub_marker.kwargs.get("location")
        desired_tags = hub_marker.kwargs.get("desired_tags")
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

    return cli.invoke(base_create_command).as_json()


def _iot_hub_removal(name):
    delete_result = cli.invoke(f"iot hub delete -n {name} -g {RG}")
    if not delete_result.success():
        logger.error(f"Failed to delete iot hub resource {name}.")


# User Assigned Identity fixtures (UAI)
@pytest.fixture(scope="module")
def provisioned_user_identity_module() -> Optional[dict]:
    result = _user_identity_provisioner()
    yield result
    if result:
        _user_identity_removal(result["name"])


def _user_identity_provisioner():
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


# Storage Account fixtures
@pytest.fixture(scope="module")
def provisioned_storage_with_identity_module(request, provisioned_iot_hub_module, provisioned_storage_module):
    role = "Storage Blob Data Contributor"
    scope = provisioned_storage_module["storage"]["id"]
    hub_principal_id = provisioned_iot_hub_module["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_module["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    _assign_rbac_role(assignee=hub_principal_id, scope=scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=scope, role=role)
    yield provisioned_iot_hub_module, provisioned_storage_module


@pytest.fixture(scope="module")
def provisioned_storage_module() -> Optional[dict]:
    result = _storage_provisioner()
    yield result
    if result:
        _storage_removal(result["storage"]["name"])


def _storage_get_cstring(account_name):
    return cli.invoke(
        "storage account show-connection-string -n {} -g {}".format(
            account_name, RG
        )
    ).as_json()["connectionString"]


def _storage_provisioner():
    """
    Create a storage account (if needed) and container and return storage connection string.
    """
    account_name = generate_hub_depenency_id()
    container_name = generate_hub_depenency_id()

    storage_list = cli.invoke(
        'storage account list -g "{}"'.format(RG)
    ).as_json()

    target_storage = None
    for storage in storage_list:
        if storage["name"] == account_name:
            target_storage = storage
            break

    if not target_storage:
        target_storage = cli.invoke(
            "storage account create -n {} -g {}".format(
                account_name, RG
            )
        ).as_json()

    storage_cstring = _storage_get_cstring(account_name)

    # Will not do anything if container exists.
    cli.invoke(
        "storage container create -n {} --connection-string '{}'".format(
            container_name, storage_cstring
        ),
    )
    target_container = cli.invoke(
        "storage container show -n {} --connection-string '{}'".format(
            container_name, storage_cstring
        ),
    ).as_json()

    return {
        "storage": target_storage,
        "container": target_container,
        "connectionString": storage_cstring
    }


def _storage_removal(account_name: str):
    delete_result = cli.invoke(f"storage account delete -g {RG} -n {account_name} -y")
    if not delete_result.success():
        logger.error(f"Failed to delete storage account resource {account_name}.")


# Event Hub fixtures
@pytest.fixture(scope="module")
def provisioned_event_hub_with_identity_module(provisioned_iot_hub_module, provisioned_event_hub_module):
    role = "Azure Event Hubs Data Sender"
    scope = provisioned_event_hub_module["eventhub"]["id"]
    hub_principal_id = provisioned_iot_hub_module["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_module["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    _assign_rbac_role(assignee=hub_principal_id, scope=scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=scope, role=role)
    yield provisioned_iot_hub_module, provisioned_event_hub_module


@pytest.fixture(scope="module")
def provisioned_event_hub_module() -> Optional[list]:
    result = _event_hub_provisioner()
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


def _event_hub_provisioner():
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    namespace_name = generate_hub_depenency_id()
    eventhub_name = generate_hub_depenency_id()
    policy_name = generate_hub_depenency_id()
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


# Service Bus fixtures
@pytest.fixture(scope="module")
def provisioned_service_bus_with_identity_module(provisioned_iot_hub_module, provisioned_service_bus_module):
    role = "Azure Service Bus Data Sender"
    queue_scope = provisioned_service_bus_module["queue"]["id"]
    topic_scope = provisioned_service_bus_module["topic"]["id"]
    hub_principal_id = provisioned_iot_hub_module["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_module["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    _assign_rbac_role(assignee=hub_principal_id, scope=queue_scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=queue_scope, role=role)
    _assign_rbac_role(assignee=hub_principal_id, scope=topic_scope, role=role)
    _assign_rbac_role(assignee=user_id, scope=topic_scope, role=role)
    yield provisioned_iot_hub_module, provisioned_service_bus_module


@pytest.fixture(scope="module")
def provisioned_service_bus_module() -> Optional[list]:
    result = _service_bus_provisioner()
    yield result
    if result:
        _service_bus_removal(result["namespace"]["name"])


def _service_bus_topic_get_cstring(namespace_name, topic_name, policy_name):
    return cli.invoke(
        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
        "--topic-name {} --name {}".format(
            namespace_name, RG, topic_name, policy_name
        )
    ).as_json()["primaryConnectionString"]


def _service_bus_queue_get_cstring(namespace_name, queue_name, policy_name):
    return cli.invoke(
        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
        "--queue-name {} --name {}".format(
            namespace_name, RG, queue_name, policy_name
        )
    ).as_json()["primaryConnectionString"]


def _service_bus_provisioner():
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    namespace_name = generate_hub_depenency_id()
    queue_name = generate_hub_depenency_id()
    topic_name = generate_hub_depenency_id()
    policy_name = generate_hub_depenency_id()
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


# Cosmos Db fixtures
@pytest.fixture(scope="module")
def provisioned_cosmosdb_with_identity_module(provisioned_iot_hub_module, provisioned_cosmos_db_module):
    role = "Cosmos DB Built-in Data Reader"
    cosmosdb_rg = provisioned_cosmos_db_module["cosmosdb"]["resourceGroup"]
    cosmosdb_account = provisioned_cosmos_db_module["cosmosdb"]["name"]
    hub_principal_id = provisioned_iot_hub_module["identity"]["principalId"]
    user_identities = list(provisioned_iot_hub_module["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    assign_cosmos_db_role(principal_id=hub_principal_id, cosmos_db_account=cosmosdb_account, role=role, rg=cosmosdb_rg)
    assign_cosmos_db_role(principal_id=user_id, cosmos_db_account=cosmosdb_account, role=role, rg=cosmosdb_rg)
    yield provisioned_iot_hub_module, provisioned_cosmos_db_module


def assign_cosmos_db_role(principal_id: str, role: str, cosmos_db_account: str, rg: str):
    cli.invoke(
        "cosmosdb sql role assignment create -a {} -g {} --scope '/' -n '{}' -p {}".format(
            cosmos_db_account, rg, role, principal_id
        )
    )


@pytest.fixture(scope="module")
def provisioned_cosmos_db_module() -> Optional[list]:
    result = _cosmos_db_provisioner()
    yield result
    if result:
        _cosmos_db_removal(result["cosmosdb"]["name"])


def _cosmos_db_get_cstring(account_name):
    output = cli.invoke(
        'cosmosdb keys list --resource-group {} --name {} --type connection-strings'.format(RG, account_name)
    ).as_json()

    for cs_object in output["connectionStrings"]:
        if cs_object["description"] == "Primary SQL Connection String":
            return cs_object["connectionString"]


def _cosmos_db_provisioner():
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    account_name = generate_hub_depenency_id()
    database_name = generate_hub_depenency_id()
    collection_name = generate_hub_depenency_id()
    partition_key_path = "/test"
    location = "eastus"
    cosmos_obj = cli.invoke(
        "cosmosdb create --name {} --resource-group {} --locations regionName={} failoverPriority=0".format(
            account_name, RG, location
        )
    ).as_json()

    database_obj = cli.invoke(
        "cosmosdb sql database create --account-name {} --resource-group {} --name {}".format(
            account_name, RG, database_name
        )
    ).as_json()

    container_obj = cli.invoke(
        "cosmosdb sql container create --account-name {} --resource-group {} --database-name {} --name {} -p {}".format(
            account_name, RG, database_name, collection_name, partition_key_path
        )
    ).as_json()
    return {
        "cosmosdb": cosmos_obj,
        "database": database_obj,
        "container": container_obj,
        "connectionString": _cosmos_db_get_cstring(account_name)
    }


def _cosmos_db_removal(account_name: str):
    delete_result = cli.invoke(f"cosmosdb delete -g {RG} -n {account_name} -y")
    if not delete_result.success():
        logger.error(f"Failed to delete Cosmos DB resource {account_name}.")
