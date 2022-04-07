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

GLOBAL_PROVISIONING_HOST = "global.azure-devices-provisioning.net"


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
    current_tags = cmd(
        f"resource show -n {name} -g {rg} --resource-type {rtype}"
    ).get_output_in_json()["tags"]

    if current_tags.get(test_tag):
        current_tags[test_tag] = int(current_tags[test_tag]) + 1
    else:
        current_tags[test_tag] = 1
    new_tags = " ".join(f"{k}={v}" for k, v in current_tags.items())

    cmd(f"resource tag -n {name} -g {rg} --resource-type {rtype} --tags {new_tags}")


class MockLogger:
    def info(self, msg):
        print(msg)

    def warn(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)
