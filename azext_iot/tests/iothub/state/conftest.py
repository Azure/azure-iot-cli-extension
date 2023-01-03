# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from time import sleep
import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.iothub.common import EndpointType
from azext_iot.tests.helpers import get_closest_marker
from azext_iot.tests.iothub import generate_hub_depenency_id, generate_hub_id
from azext_iot.tests.settings import DynamoSettings
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.certops import create_self_signed_certificate
from typing import Optional
from knack.log import get_logger

logger = get_logger(__name__)
MAX_RBAC_ASSIGNMENT_TRIES = 10
USER_ROLE = "IoT Hub Data Contributor"
cli = EmbeddedCLI()
REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)
RG = settings.env.azext_iot_testrg


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


# IoT Hub with control plane
@pytest.fixture(scope="module")
def setup_hub_controlplane_states(
    request, provisioned_iothubs, provisioned_event_hub, provisioned_service_bus
) -> Optional[dict]:
    """
    Set up so that first hub will have all permissions, endpoints, etc and the other one(s) have correct
    permissions.
    """
    hub_name = provisioned_iothubs[0]["name"]
    hub_rg = provisioned_iothubs[0]["rg"]
    eventhub_name = provisioned_event_hub["eventhub"]["name"]
    eventhub_endpoint_uri = "sb:" + provisioned_event_hub["namespace"]["serviceBusEndpoint"].split(":")[1]
    servicebus_queue = provisioned_service_bus["queue"]["name"]
    servicebus_topic = provisioned_service_bus["topic"]["name"]
    servicebus_endpoint_uri = "sb:" + provisioned_service_bus["namespace"]["serviceBusEndpoint"].split(":")[1]

    provisioned_storage = provisioned_iothubs[0]["storage"]
    storage_cstring = provisioned_storage["connectionString"]
    storage_container = provisioned_storage["container"]["name"]

    use_system_endpoints = get_closest_marker(request).kwargs.get("system_endpoints", True)

    # add endpoints - prob use dict of scope to role + for loop
    hub_principal_ids = [hub_obj["hub"]["identity"]["principalId"] for hub_obj in provisioned_iothubs]
    user_identities = list(provisioned_iothubs[0]["hub"]["identity"]["userAssignedIdentities"].values())
    user_principal_id = user_identities[0]["principalId"]
    user_id = list(provisioned_iothubs[0]["hub"]["identity"]["userAssignedIdentities"].keys())[0]
    sub_id = provisioned_iothubs[0]["hub"]["subscriptionid"]

    # mapping of scope to role
    scope_dict = {
        provisioned_storage["storage"]["id"]: "Storage Blob Data Contributor",
        provisioned_event_hub["eventhub"]["id"]: "Azure Event Hubs Data Sender",
        provisioned_service_bus["queue"]["id"]: "Azure Service Bus Data Sender",
        provisioned_service_bus["topic"]["id"]: "Azure Service Bus Data Sender"
    }
    for scope, role in scope_dict.items():
        _assign_rbac_role(assignee=user_principal_id, scope=scope, role=role)
        if use_system_endpoints:
            for hub_principal_id in hub_principal_ids:
                _assign_rbac_role(assignee=hub_principal_id, scope=scope, role=role)
    sleep(30)

    suffix = "systemid" if use_system_endpoints else "userid"
    user_identity_parameter = "" if use_system_endpoints else f"--identity {user_id}"
    cli.invoke(
        f"iot hub routing-endpoint create -n eventhub-{suffix} -r {hub_rg} -g {hub_rg} -s {sub_id}"
        f" -t {EndpointType.EventHub.value} --hub-name {hub_name} --endpoint-uri {eventhub_endpoint_uri}"
        f" --entity-path {eventhub_name} --auth-type identityBased {user_identity_parameter}"
    )

    cli.invoke(
        f"iot hub routing-endpoint create -n queue-{suffix} -r {hub_rg} -g {hub_rg} -s {sub_id}"
        f" -t {EndpointType.ServiceBusQueue.value} --hub-name {hub_name} --endpoint-uri "
        f"{servicebus_endpoint_uri} --entity-path {servicebus_queue} --auth-type identityBased "
        f"{user_identity_parameter}"
    )

    cli.invoke(
        f"iot hub routing-endpoint create -n topic-userid -r {hub_rg} -g {hub_rg} -t {EndpointType.ServiceBusTopic.value} "
        f"--hub-name {hub_name} -s {sub_id} --endpoint-uri {servicebus_endpoint_uri} --entity-path {servicebus_topic} "
        f"--auth-type identityBased --identity {user_id}"
    )

    cli.invoke(
        f"iot hub routing-endpoint create -n storagecontainer-key -r {hub_rg} -g {hub_rg} -t "
        f"{EndpointType.AzureStorageContainer.value} --hub-name {hub_name} -c {storage_cstring} -s {sub_id} "
        f"--container {storage_container}  -b 350 -w 250 --encoding json")

    # add routes - prob change one to be custom endpoint
    cli.invoke(
        f"iot hub route create --endpoint events --hub-name {hub_name} -g {hub_rg}"
        f" --name {generate_generic_id()} --source devicelifecycleevents --condition false --enabled true"
    )
    cli.invoke(
        f"iot hub route create --endpoint events --hub-name {hub_name} -g {hub_rg}"
        f" --name {generate_generic_id()} --source twinchangeevents --condition true --enabled false"
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

    # add ip filter rule
    cli.invoke(
        f"resource update --name {hub_name} -g {hub_rg} --resource-type "
        "\"Microsoft.Devices/IotHubs\" --set properties.networkRuleSets='{}'"
    )
    cli.invoke(
        f"resource update --name {hub_name} -g {hub_rg} --resource-type Microsoft.Devices/IotHubs "
        "--add properties.networkRuleSets.ipRules '{\"action\":\"Allow\",\"filterName\":\"Trusted\",\"ipMask\":\"192.168.0.1\"}'"
    )
    yield provisioned_iothubs


# Iot Hub
@pytest.fixture(scope="module")
def provisioned_iothubs(
    request, provisioned_user_identity, provisioned_storage
) -> Optional[dict]:
    result = _iot_hubs_provisioner(request, provisioned_user_identity, provisioned_storage)
    _assign_dataplane_rbac_role(result)
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
        desired_sys_identity = hub_marker.kwargs.get("sys_identity")
        desired_user_identity = hub_marker.kwargs.get("user_identity")
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


def _assign_dataplane_rbac_role(hub_results):
    for hub in hub_results:
        target_hub_id = hub["hub"]["id"]
        account = cli.invoke("account show").as_json()
        user = account["user"]

        if user["name"] is None:
            raise Exception("User not found")

        tries = 0
        while tries < MAX_RBAC_ASSIGNMENT_TRIES:
            role_assignments = _get_role_assignments(target_hub_id, USER_ROLE)
            role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
            if user["name"] in role_assignment_principal_names:
                break
            # else assign IoT Hub Data Contributor role to current user and check again
            cli.invoke(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    user["name"], USER_ROLE, target_hub_id
                )
            )
            sleep(10)
            tries += 1

        if tries == MAX_RBAC_ASSIGNMENT_TRIES:
            raise Exception(
                "Reached max ({}) number of tries to assign RBAC role. Please re-run the test later "
                "or with more max number of tries.".format(MAX_RBAC_ASSIGNMENT_TRIES)
            )


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


# User Identity
@pytest.fixture(scope="module")
def provisioned_user_identity(request) -> Optional[dict]:
    hub_marker = get_closest_marker(request)
    result = None
    if hub_marker and hub_marker.kwargs.get("storage"):
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


# Storage Account
@pytest.fixture(scope="module")
def provisioned_storage(request) -> Optional[dict]:
    hub_marker = get_closest_marker(request)
    result = None
    if hub_marker and hub_marker.kwargs.get("storage"):
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


# Event Hub
@pytest.fixture(scope="module")
def provisioned_event_hub() -> Optional[list]:
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


# Service Bus
@pytest.fixture(scope="module")
def provisioned_service_bus() -> Optional[list]:
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
