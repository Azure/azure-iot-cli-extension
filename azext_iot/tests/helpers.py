# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from inspect import getsourcefile
from time import sleep
from azure.iot.device import ProvisioningDeviceClient, IoTHubDeviceClient

from azext_iot.common.utility import read_file_content
from azext_iot.tests.settings import DynamoSettings

GLOBAL_PROVISIONING_HOST = "global.azure-devices-provisioning.net"
TAG_ENV_VAR = [
    "definition_id",
    "job_display_name",
    "job_id",
    "use_tags"
]

CERT_ENDING = "-cert.pem"
KEY_ENDING = "-key.pem"

settings = DynamoSettings(opt_env_set=TAG_ENV_VAR)
# Make sure that TEST_PIPELINE_ID is only populated if correct variables are present
TEST_PIPELINE_ID = "{} {} {}".format(
    settings.env.definition_id,
    settings.env.job_display_name,
    settings.env.job_id
).strip()
USE_TAGS = str(settings.env.use_tags).lower() == "true"


def load_json(filename):
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))
    return json.loads(read_file_content(filename))


def dps_connect_device(device_id: str, credentials: dict) -> IoTHubDeviceClient:
    id_scope = credentials["idScope"]
    key = credentials["symmetricKey"]["primaryKey"]

    provisioning_device_client = ProvisioningDeviceClient.create_from_symmetric_key(
        provisioning_host=GLOBAL_PROVISIONING_HOST,
        registration_id=device_id,
        id_scope=id_scope,
        symmetric_key=key,
    )

    registration_result = provisioning_device_client.register()
    if registration_result.status == "assigned":
        device_client = IoTHubDeviceClient.create_from_symmetric_key(
            symmetric_key=key,
            hostname=registration_result.registration_state.assigned_hub,
            device_id=registration_result.registration_state.device_id,
        )
        device_client.connect()
        return device_client


def add_test_tag(cmd, name: str, rg: str, rtype: str, test_tag: str):
    if USE_TAGS:
        current_tags = cmd(
            f"resource show -n {name} -g {rg} --resource-type {rtype}"
        ).get_output_in_json()["tags"]

        if current_tags.get(test_tag):
            current_tags[test_tag] = int(current_tags[test_tag]) + 1
        else:
            current_tags[test_tag] = 1

        if TEST_PIPELINE_ID:
            current_tags["pipeline_id"] = f"'{TEST_PIPELINE_ID}'"

        new_tags = " ".join(f"{k}={v}" for k, v in current_tags.items())
        cmd(f"resource tag -n {name} -g {rg} --resource-type {rtype} --tags {new_tags} -i")


def create_storage_account(
    cmd,
    account_name: str,
    container_name: str,
    rg: str,
    resource_name: str,
    create_account: bool = True,
) -> str:
    """
    Create a storage account (if needed) and container and return storage connection string.
    """
    if create_account:
        storage_list = cmd(
            'storage account list -g "{}"'.format(rg)
        ).get_output_in_json()

        target_storage = None
        for storage in storage_list:
            if storage["name"] == account_name:
                target_storage = storage
                break

        if not target_storage:
            cmd(
                "storage account create -n {} -g {} --tags iot_resource={}".format(
                    account_name, rg, resource_name
                )
            )

    storage_cstring = cmd(
        "storage account show-connection-string -n {} -g {}".format(
            account_name, rg
        )
    ).get_output_in_json()["connectionString"]

    # Will not do anything if container exists.
    cmd(
        "storage container create -n {} --connection-string '{}'".format(
            container_name, storage_cstring
        ),
    )

    return storage_cstring


def create_event_hub(
    cmd,
    namespace_name: str,
    eventhub_name: str,
    policy_name: str,
    rg: str,
    resource_name: str,
    create_namespace: bool = True,
    create_eventhub: bool = True,
    create_policy: bool = True,
) -> str:
    """
    Create an event hub namespace, instance, and policy (if needed) and return the connection string for the policy.
    """
    if create_namespace:
        cmd(
            "eventhubs namespace create --name {} --resource-group {} --tags iotresource={}".format(
                namespace_name, rg, resource_name
            )
        )

    if create_eventhub:
        cmd(
            "eventhubs eventhub create --namespace-name {} --resource-group {} --name {}".format(
                namespace_name, rg, eventhub_name
            )
        )

    if create_policy:
        cmd(
            "eventhubs eventhub authorization-rule create --namespace-name {} --resource-group {} "
            "--eventhub-name {} --name {} --rights Send".format(
                namespace_name, rg, eventhub_name, policy_name
            )
        )

    # Return a connection string, even if it was not created.
    return cmd(
        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
        "--eventhub-name {} --name {}".format(
            namespace_name, rg, eventhub_name, policy_name
        )
    ).get_output_in_json()["primaryConnectionString"]


def create_service_bus_topic(
    cmd,
    namespace_name: str,
    topic_name: str,
    policy_name: str,
    rg: str,
    resource_name: str,
    create_namespace: bool = True,
    create_topic: bool = True,
    create_policy: bool = True,
) -> str:
    """
    Create a service bus namespace, topic, and policy (if needed) and return the connection string for the policy.
    """
    if create_namespace:
        cmd(
            "servicebus namespace create --name {} --resource-group {} --tags iotresource={}".format(
                namespace_name, rg, resource_name
            )
        )

    if create_topic:
        cmd(
            "servicebus topic create --namespace-name {} --resource-group {} --name {}".format(
                namespace_name, rg, topic_name
            )
        )

    if create_policy:
        cmd(
            "servicebus topic authorization-rule create --namespace-name {} --resource-group {} "
            "--topic-name {} --name {} --rights Send".format(
                namespace_name, rg, topic_name, policy_name
            )
        )

    # Return a connection string, even if it was not created.
    topic_cs = cmd(
        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
        "--topic-name {} --name {}".format(
            namespace_name, rg, topic_name, policy_name
        )
    ).get_output_in_json()["primaryConnectionString"]

    return topic_cs


def create_service_bus_queue(
    cmd,
    namespace_name: str,
    queue_name: str,
    policy_name: str,
    rg: str,
    resource_name: str,
    create_namespace: bool = True,
    create_queue: bool = True,
    create_policy: bool = True,
) -> str:
    """
    Create a service bus namespace, queue, and policy (if needed) and return the connection string for the policy.
    """
    if create_namespace:
        cmd(
            "servicebus namespace create --name {} --resource-group {} --tags iotresource={}".format(
                namespace_name, rg, resource_name
            )
        )

    if create_queue:
        cmd(
            "servicebus queue create --namespace-name {} --resource-group {} --name {}".format(
                namespace_name, rg, queue_name
            )
        )

    if create_policy:
        cmd(
            "servicebus queue authorization-rule create --namespace-name {} --resource-group {} "
            "--queue-name {} --name {} --rights Send".format(
                namespace_name, rg, queue_name, policy_name
            )
        )

    # Return a connection string, even if it was not created
    queue_cs = cmd(
        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
        "--queue-name {} --name {}".format(
            namespace_name, rg, queue_name, policy_name
        )
    ).get_output_in_json()["primaryConnectionString"]

    return queue_cs


def create_cosmos_db(
    cmd,
    account_name: str,
    database_name: str,
    collection_name: str,
    partition_key_path: str,
    rg: str,
    resource_name: str,
    create_account: bool = True,
    create_database: bool = True,
    create_collection: bool = True,
) -> str:
    """
    Create a cosmos db account, database, and collection (if needed) and return the cosmosdb connection string.
    """

    if create_account:
        cmd(
            'cosmosdb create --resource-group {} --name {} --tags iot_resource={}'.format(
                rg, account_name, resource_name
            )
        )

    if create_database:
        cmd(
            'cosmosdb sql database create --resource-group {} --account-name {} --name {}'.format(
                rg, account_name, database_name
            )
        )

    if create_collection:
        cmd(
            'cosmosdb sql container create --resource-group {} --account-name {} --database-name {} --name {} -p {}'.format(
                rg, account_name, database_name, collection_name, partition_key_path
            )
        )

    output = cmd(
        'cosmosdb keys list --resource-group {} --name {} --type connection-strings'.format(rg, account_name)
    ).get_output_in_json()

    for cs_object in output["connectionStrings"]:
        if cs_object["description"] == "Primary SQL Connection String":
            return cs_object["connectionString"]


def create_managed_identity(cmd, name: str, rg: str):
    return cmd(
        f"identity create -n {name} -g {rg}"
    ).get_output_in_json()


def get_role_assignments(cmd, scope, role):
    return cmd(
        'role assignment list --scope "{}" --role "{}"'.format(
            scope, role
        )
    ).get_output_in_json()


def assign_rbac_role(cmd, assignee: str, scope: str, role: str, max_tries: int = 10):
    """
    Assign a given role for a given assignee and scope. Will check for assignment completion.
    """
    tries = 0
    while tries < max_tries:
        role_assignments = get_role_assignments(cmd, scope, role)
        role_assignment_principal_ids = [assignment["principalId"] for assignment in role_assignments]
        if assignee in role_assignment_principal_ids:
            break
        # else assign role to scope and check again
        cmd(
            'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                assignee, role, scope
            )
        )
        sleep(10)
        tries += 1


def assign_cosmos_db_role(cmd, principal_id: str, role: str, cosmos_db_account: str, rg: str):
    cmd(
        "cosmosdb sql role assignment create -a {} -g {} --scope '/' -n '{}' -p {}".format(
            cosmos_db_account, rg, role, principal_id
        )
    )


class MockLogger:
    def info(self, msg):
        print(msg)

    def warn(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)
