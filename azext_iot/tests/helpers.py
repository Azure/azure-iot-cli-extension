# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os

from inspect import getsourcefile
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
        cmd(f"resource tag -n {name} -g {rg} --resource-type {rtype} --tags {new_tags}")


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


class MockLogger:
    def info(self, msg):
        print(msg)

    def warn(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)
