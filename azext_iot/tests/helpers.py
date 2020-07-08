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


class MockLogger:
    def info(self, msg):
        print(msg)

    def warn(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)
