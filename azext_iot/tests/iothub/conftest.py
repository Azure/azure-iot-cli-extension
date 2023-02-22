# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from typing import Optional, List
import os

import pytest
from knack.log import get_logger

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.helpers import assign_role_assignment, get_closest_marker, get_agent_public_ip
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL

logger = get_logger(__name__)
MAX_RBAC_ASSIGNMENT_TRIES = 10
USER_ROLE = "IoT Hub Data Contributor"
cli = EmbeddedCLI()
settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
RG = settings.env.azext_iot_testrg
HUB_NAME = settings.env.azext_iot_testhub
STORAGE_ACCOUNT = settings.env.azext_iot_teststorageaccount
STORAGE_CONTAINER = settings.env.azext_iot_teststoragecontainer


def generate_hub_id() -> str:
    return f"aziotclitest-hub-{generate_generic_id()}"[:35]


def generate_hub_depenency_id() -> str:
    return f"aziotclitest{generate_generic_id()}"[:24]


# def _assign_rbac_role(assignee: str, scope: str, role: str, max_tries: int = MAX_RBAC_ASSIGNMENT_TRIES):
#     tries = 0
#     while tries < max_tries:
#         role_assignments = _get_role_assignments(scope, role)
#         role_assignment_principal_ids = [assignment.get("principalId") for assignment in role_assignments]
#         role_assignment_principal_names = [assignment.get("principalName") for assignment in role_assignments]
#         if assignee in role_assignment_principal_ids + role_assignment_principal_names:
#             break
#         # else assign role to scope and check again
#         cli.invoke(
#             'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
#                 assignee, role, scope
#             )
#         )
#         sleep(10)
#         tries += 1

#     if tries == max_tries:
#         raise Exception(
#             "Reached max ({}) number of tries to assign role {} to scope {} for assignee {}. Please "
#             "re-run the test later or with more max number of tries.".format(
#                 max_tries, role, scope, assignee
#             )
#         )


def assign_iot_hub_dataplane_rbac_role(hub_results):
    """Add IoT Hub Data Contributor role to current user"""
    for hub in hub_results:
        # Only add dataplane roles to the hubs that were not created mid test
        if hub.get("hub"):
            target_hub_id = hub["hub"]["id"]
            account = cli.invoke("account show").as_json()
            user = account["user"]

            if user["name"] is None:
                raise Exception("User not found")

            assign_role_assignment(
                assignee=user["name"],
                scope=target_hub_id,
                role=USER_ROLE,
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )


@pytest.fixture()
def fixture_provision_existing_hub_certificate(request):
    if HUB_NAME:
        # Make sure root certificate is Baltimore(Default)
        authority = cli.invoke(
            f"iot hub certificate root-authority show -n {HUB_NAME} -g {RG}"
        ).as_json()

        if authority["enableRootCertificateV2"]:
            # Transition to Baltimore (initial transition)
            cli.invoke(
                f"""iot hub certificate root-authority set -n {HUB_NAME}
                -g {RG} --cav v1 --yes""",
            )
    yield


@pytest.fixture()
def fixture_provision_existing_hub_device_config(request):
    # Clean up existing devices and configurations
    if settings.env.azext_iot_testhub:
        device_list = []
        device_list.extend(d["deviceId"] for d in cli.invoke(
            f"iot hub device-twin list -n {HUB_NAME} -g {RG}"
        ).as_json())

        config_list = []
        config_list.extend(c["id"] for c in cli.invoke(
            f"iot edge deployment list -n {HUB_NAME} -g {RG}"
        ).as_json())

        config_list.extend(c["id"] for c in cli.invoke(
            f"iot hub configuration list -n {HUB_NAME} -g {RG}"
        ).as_json())

        _clean_up(device_ids=device_list, config_ids=config_list)
    yield


@pytest.fixture()
def fixture_provision_existing_hub_role(request):
    if settings.env.azext_iot_testhub:
        # Assign Data Contributor role
        account = cli.invoke("account show").as_json()
        user = account["user"]

        target_hub = cli.invoke(
            "iot hub show -n {} -g {}".format(HUB_NAME, RG)
        ).as_json()

        assign_role_assignment(
            assignee=user["name"],
            scope=target_hub,
            role=USER_ROLE,
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )
    yield


@pytest.fixture()
def fixture_provision_existing_hub_storage(request):
    # Add storage account to hub
    storage_cstring = cli.invoke(
        "storage account show-connection-string -n {} -g {}".format(
            STORAGE_ACCOUNT, RG
        )
    ).as_json()["connectionString"]
    if settings.env.azext_iot_testhub:
        # Check if hub instance has valid storage endpoint
        hubstate = cli.invoke(
            "iot hub show -n {}".format(
                HUB_NAME
            )).as_json()
        storage_cs = hubstate["properties"]["storageEndpoints"]["$default"]["connectionString"]

        # Link storage conatiner to the hub instance if hub don't have one
        if storage_cs is None or storage_cs == "":
            cli.invoke(
                "iot hub update -n {} --fc {} --fcs {}".format(
                    HUB_NAME, STORAGE_CONTAINER, storage_cstring
                ))
    yield


# IoT Hub fixtures
@pytest.fixture(scope="module")
def setup_hub_controlplane_states(
    request,
    provisioned_iot_hubs_with_storage_user_module,
    provisioned_event_hub_module,
    provisioned_service_bus_module,
    provisioned_cosmos_db_module
) -> dict:
    """
    For Iot Hub State
    Set up so that first hub will have all permissions, endpoints, etc and the other one(s) have correct
    permissions.
    """
    hub_name = provisioned_iot_hubs_with_storage_user_module[0]["name"]
    hub_rg = provisioned_iot_hubs_with_storage_user_module[0]["rg"]

    eventhub_name = provisioned_event_hub_module["eventhub"]["name"]
    eventhub_endpoint_uri = "sb:" + provisioned_event_hub_module["namespace"]["serviceBusEndpoint"].split(":")[1]

    servicebus_queue = provisioned_service_bus_module["queue"]["name"]
    servicebus_topic = provisioned_service_bus_module["topic"]["name"]
    servicebus_endpoint_uri = "sb:" + provisioned_service_bus_module["namespace"]["serviceBusEndpoint"].split(":")[1]

    provisioned_storage = provisioned_iot_hubs_with_storage_user_module[0]["storage"]
    storage_cstring = provisioned_storage["connectionString"]
    storage_container = provisioned_storage["container"]["name"]

    cosmosdb_container_name = provisioned_cosmos_db_module["container"]["name"]
    cosmosdb_database_name = provisioned_cosmos_db_module["database"]["name"]
    cosmosdb_cstring = provisioned_cosmos_db_module["connectionString"]

    use_system_endpoints = get_closest_marker(request).kwargs.get("system_endpoints", True)

    # add endpoints
    hub_principal_ids = [
        hub_obj["hub"]["identity"]["principalId"] for hub_obj in provisioned_iot_hubs_with_storage_user_module
    ]
    user_identities = list(
        provisioned_iot_hubs_with_storage_user_module[0]["hub"]["identity"]["userAssignedIdentities"].values()
    )
    user_principal_id = user_identities[0]["principalId"]
    user_id = list(
        provisioned_iot_hubs_with_storage_user_module[0]["hub"]["identity"]["userAssignedIdentities"].keys()
    )[0]

    # mapping of scope to role
    scope_dict = {
        provisioned_storage["storage"]["id"]: "Storage Blob Data Contributor",
        provisioned_event_hub_module["eventhub"]["id"]: "Azure Event Hubs Data Sender",
        provisioned_service_bus_module["queue"]["id"]: "Azure Service Bus Data Sender",
        provisioned_service_bus_module["topic"]["id"]: "Azure Service Bus Data Sender"
    }
    for scope, role in scope_dict.items():
        assign_role_assignment(
            assignee=user_principal_id,
            scope=scope,
            role=role,
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )
        if use_system_endpoints:
            for hub_principal_id in hub_principal_ids:
                assign_role_assignment(
                    assignee=hub_principal_id,
                    scope=scope,
                    role=role,
                    max_tries=MAX_RBAC_ASSIGNMENT_TRIES
                )
    sleep(30)

    suffix = "systemid" if use_system_endpoints else "userid"
    user_identity_parameter = "[system]" if use_system_endpoints else user_id
    cli.invoke(
        f"iot hub message-endpoint create eventhub --en eventhub-{suffix} -g {hub_rg} -n {hub_name} --endpoint-uri "
        f"{eventhub_endpoint_uri} --entity-path {eventhub_name} --identity {user_identity_parameter}"
    )

    cli.invoke(
        f"iot hub message-endpoint create servicebus-queue --en queue-{suffix} -g {hub_rg} -n {hub_name} "
        f"--endpoint-uri {servicebus_endpoint_uri} --entity-path {servicebus_queue} --identity {user_identity_parameter}"
    )

    cli.invoke(
        f"iot hub message-endpoint create servicebus-topic --en topic-userid -g {hub_rg} -n {hub_name} --endpoint-uri "
        f"{servicebus_endpoint_uri} --entity-path {servicebus_topic} --identity {user_id}"
    )

    cli.invoke(
        f"iot hub message-endpoint create storage-container --en storagecontainer-key -g {hub_rg} -n {hub_name} -c "
        f"{storage_cstring} --container {storage_container}  -b 350 -w 250 --encoding json")

    cli.invoke(
        f"iot hub message-endpoint create cosmosdb-container --en cosmosdb-key -g {hub_rg} -n {hub_name} --container "
        f"{cosmosdb_container_name} --db {cosmosdb_database_name} -c {cosmosdb_cstring}"
    )

    # add routes - prob change one to be custom endpoint
    cli.invoke(
        f"iot hub message-route create --endpoint events -n {hub_name} -g {hub_rg}"
        f" --rn {generate_generic_id()} --source devicelifecycleevents --condition false --enabled true"
    )
    cli.invoke(
        f"iot hub message-route create --endpoint events -n {hub_name} -g {hub_rg}"
        f" --rn {generate_generic_id()} --source twinchangeevents --condition true --enabled false"
    )

    # add certificate
    cert = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["certificate"]
    cert_file = "testCert" + generate_generic_id() + ".cer"
    with open(cert_file, 'w', encoding='utf-8') as f:
        f.write(cert)

    cli.invoke(
        f"iot hub certificate create --hub-name {hub_name} --name cert1 --path {cert_file} -g {hub_rg} -v True"
    )

    if os.path.isfile(cert_file):
        os.remove(cert_file)

    # add ip filter rule - make sure to add public ip address so dataplane isn't screwed up
    public_ip = get_agent_public_ip()
    cli.invoke(
        f"resource update --name {hub_name} -g {hub_rg} --resource-type "
        "\"Microsoft.Devices/IotHubs\" --set properties.networkRuleSets='{}'"
    )
    cli.invoke(
        f"resource update --name {hub_name} -g {hub_rg} --resource-type Microsoft.Devices/IotHubs "
        "--add properties.networkRuleSets.ipRules '{\"action\":\"Allow\",\"filterName\":\"Trusted\",\"ipMask\":\""
        f"{public_ip}"
        "\"}'"
    )
    yield provisioned_iot_hubs_with_storage_user_module


@pytest.fixture(scope="module")
def provisioned_iot_hubs_with_storage_user_module(
    request, provisioned_user_identity_module, provisioned_storage_module
) -> dict:
    result = _iot_hubs_provisioner(
        request, provisioned_user_identity_module, provisioned_storage_module
    )
    yield result
    if result:
        _iot_hubs_removal(result)


@pytest.fixture(scope="module")
def provisioned_iot_hubs_with_user_module(request, provisioned_user_identity_module) -> dict:
    result = _iot_hubs_provisioner(request, provisioned_user_identity_module)
    yield result
    if result:
        _iot_hubs_removal(result)


@pytest.fixture(scope="module")
def provisioned_only_iot_hubs_module(request) -> dict:
    result = _iot_hubs_provisioner(request)
    yield result
    if result:
        _iot_hubs_removal(result)


def _iot_hubs_provisioner(request, provisioned_user_identity=None, provisioned_storage=None):
    hub_marker = get_closest_marker(request)
    desired_location = None
    desired_tags = None
    desired_sys_identity = False
    desired_user_identity = False
    desired_storage = None
    desired_count = 1

    if hub_marker:
        desired_location = hub_marker.kwargs.get("location")
        desired_tags = hub_marker.kwargs.get("desired_tags")
        desired_sys_identity = hub_marker.kwargs.get("sys_identity", False)
        desired_user_identity = hub_marker.kwargs.get("user_identity", False)
        desired_storage = hub_marker.kwargs.get("storage")
        desired_count = hub_marker.kwargs.get("count", 1)

    hub_results = []
    for _ in range(desired_count):
        name = generate_hub_id()
        base_create_command = f"iot hub create -n {name} -g {RG} --sku S1"
        if desired_sys_identity:
            base_create_command += " --mi-system-assigned"
        if desired_user_identity and provisioned_user_identity:
            user_identity_id = provisioned_user_identity["id"]
            base_create_command += f" --mi-user-assigned {user_identity_id}"
        if desired_tags:
            base_create_command += f" --tags {desired_tags}"
        if desired_location:
            base_create_command += f" -l {desired_location}"
        if desired_storage and provisioned_storage:
            storage_cstring = provisioned_storage["connectionString"]
            base_create_command += f" --fcs {storage_cstring} --fc fileupload"

        hub_obj = cli.invoke(base_create_command).as_json()
        hub_results.append({
            "hub": hub_obj,
            "name": name,
            "rg": RG,
            "connectionString": _get_hub_connection_string(name, RG),
            "storage": provisioned_storage
        })
    return hub_results


def _get_hub_connection_string(name, rg, policy="iothubowner"):
    return cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            name, rg, policy
        )
    ).as_json()["connectionString"]


def _iot_hubs_removal(hub_result):
    for hub in hub_result:
        name = hub["name"]
        delete_result = cli.invoke(f"iot hub delete -n {name} -g {RG}")
        if not delete_result.success():
            logger.error(f"Failed to delete iot hub resource {name}.")


# User Assigned Identity fixtures (UAI)
@pytest.fixture(scope="module")
def provisioned_user_identity_module() -> dict:
    result = _user_identity_provisioner()
    yield result
    if result:
        _user_identity_removal(result["name"])


def _user_identity_provisioner():
    name = generate_hub_depenency_id()
    return cli.invoke(
        f"identity create -n {name} -g {RG}"
    ).as_json()


# def _get_role_assignments(scope, role):
#     return cli.invoke(
#         f'role assignment list --scope "{scope}" --role "{role}"'
#     ).as_json()


def _user_identity_removal(name):
    delete_result = cli.invoke(f"identity delete -n {name} -g {RG}")
    if not delete_result.success():
        logger.error(f"Failed to delete user identity resource {name}.")


# Storage Account fixtures
@pytest.fixture(scope="module")
def provisioned_storage_with_identity_module(
    request, provisioned_iot_hubs_with_user_module, provisioned_storage_module
):
    role = "Storage Blob Data Contributor"
    scope = provisioned_storage_module["storage"]["id"]
    hub_principal_id = provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["principalId"]
    user_identities = list(provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    assign_role_assignment(
        assignee=hub_principal_id,
        scope=scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    assign_role_assignment(
        assignee=user_id,
        scope=scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    yield provisioned_iot_hubs_with_user_module, provisioned_storage_module


@pytest.fixture(scope="module")
def provisioned_storage_module() -> dict:
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
def provisioned_event_hub_with_identity_module(
    provisioned_iot_hubs_with_user_module, provisioned_event_hub_module
):
    role = "Azure Event Hubs Data Sender"
    scope = provisioned_event_hub_module["eventhub"]["id"]
    hub_principal_id = provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["principalId"]
    user_identities = list(provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    assign_role_assignment(
        assignee=hub_principal_id,
        scope=scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    assign_role_assignment(
        assignee=user_id,
        scope=scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    yield provisioned_iot_hubs_with_user_module, provisioned_event_hub_module


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
def provisioned_service_bus_with_identity_module(
    provisioned_iot_hubs_with_user_module, provisioned_service_bus_module
):
    role = "Azure Service Bus Data Sender"
    queue_scope = provisioned_service_bus_module["queue"]["id"]
    topic_scope = provisioned_service_bus_module["topic"]["id"]
    hub_principal_id = provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["principalId"]
    user_identities = list(provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    assign_role_assignment(
        assignee=hub_principal_id,
        scope=queue_scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    assign_role_assignment(
        assignee=user_id,
        scope=queue_scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    assign_role_assignment(
        assignee=hub_principal_id,
        scope=topic_scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    assign_role_assignment(
        assignee=user_id,
        scope=topic_scope,
        role=role,
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )
    yield provisioned_iot_hubs_with_user_module, provisioned_service_bus_module


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
def provisioned_cosmosdb_with_identity_module(
    provisioned_iot_hubs_with_user_module, provisioned_cosmos_db_module
):
    role = "Cosmos DB Built-in Data Reader"
    cosmosdb_rg = provisioned_cosmos_db_module["cosmosdb"]["resourceGroup"]
    cosmosdb_account = provisioned_cosmos_db_module["cosmosdb"]["name"]
    hub_principal_id = provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["principalId"]
    user_identities = list(provisioned_iot_hubs_with_user_module[0]["hub"]["identity"]["userAssignedIdentities"].values())
    user_id = user_identities[0]["principalId"]
    assign_cosmos_db_role(principal_id=hub_principal_id, cosmos_db_account=cosmosdb_account, role=role, rg=cosmosdb_rg)
    assign_cosmos_db_role(principal_id=user_id, cosmos_db_account=cosmosdb_account, role=role, rg=cosmosdb_rg)
    yield provisioned_iot_hubs_with_user_module, provisioned_cosmos_db_module


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


def _clean_up(device_ids: List[str] = None, config_ids: List[str] = None):
    connection_string = cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            HUB_NAME, RG, "iothubowner"
        )
    ).as_json()["connectionString"]
    if device_ids:
        device = device_ids.pop()
        cli.invoke(
            "iot hub device-identity delete -d {} --login {}".format(
                device, connection_string
            )
        )

        for device in device_ids:
            cli.invoke(
                "iot hub device-identity delete -d {} -n {} -g {}".format(
                    device, HUB_NAME, RG
                )
            )

    if config_ids:
        config = config_ids.pop()
        cli.invoke(
            "iot hub configuration delete -c {} --login {}".format(
                config, connection_string
            )
        )

        for config in config_ids:
            cli.invoke(
                "iot hub configuration delete -c {} -n {} -g {}".format(
                    config, HUB_NAME, RG
                )
            )
