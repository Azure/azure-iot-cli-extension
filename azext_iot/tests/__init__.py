# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
import io
import os

from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from azure.cli.testsdk import LiveScenarioTest
from contextlib import contextmanager
from typing import List

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_DEVICE_MODULE = "test-module-"
PREFIX_CONFIG = "test-config-"
PREFIX_EDGE_CONFIG = "test-edgedeploy-"
PREFIX_JOB = "test-job-"


@contextmanager
def capture_output():
    class stream_buffer_tee(object):
        def __init__(self):
            self.stdout = sys.stdout
            self.buffer = io.StringIO()

        def write(self, message):
            self.stdout.write(message)
            self.buffer.write(message)

        def flush(self):
            self.stdout.flush()
            self.buffer.flush()

        def get_output(self):
            return self.buffer.getvalue()

        def close(self):
            self.buffer.close()

    _stdout = sys.stdout
    buffer_tee = stream_buffer_tee()
    sys.stdout = buffer_tee
    try:
        yield buffer_tee
    finally:
        sys.stdout = _stdout
        buffer_tee.close()


class CaptureOutputLiveScenarioTest(LiveScenarioTest):
    def __init__(self, test_scenario):
        super(CaptureOutputLiveScenarioTest, self).__init__(test_scenario)

    # TODO: @digimaun - Maybe put a helper like this in the shared lib, when you create it?
    def command_execute_assert(self, command, asserts):
        from . import capture_output

        with capture_output() as buffer:
            self.cmd(command, checks=None)
            output = buffer.get_output()

        for a in asserts:
            assert a in output

        return output


class IoTLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario, entity_name, entity_rg):
        assert test_scenario
        assert entity_name
        assert entity_rg

        self.entity_name = entity_name
        self.entity_rg = entity_rg

        super(IoTLiveScenarioTest, self).__init__(test_scenario)

        self.cmd(
            "iot hub create --name {} --resource-group {} --sku S1".format(
                entity_name, entity_rg
            )
        )

        self.region = self.get_region()
        self.connection_string = self.get_hub_cstring()

    def clean_up(self, device_ids: List[str] = None, config_ids: List[str] = None):
        if device_ids:
            device = device_ids.pop()
            self.cmd(
                "iot hub device-identity delete -d {} --login {}".format(
                    device, self.connection_string
                ),
                checks=self.is_empty(),
            )

            for device in device_ids:
                self.cmd(
                    "iot hub device-identity delete -d {} -n {} -g {}".format(
                        device, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )

        if config_ids:
            config = config_ids.pop()
            self.cmd(
                "iot hub configuration delete -c {} --login {}".format(
                    config, self.connection_string
                ),
                checks=self.is_empty(),
            )

            for config in config_ids:
                self.cmd(
                    "iot hub configuration delete -c {} -n {} -g {}".format(
                        config, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )
            
            self.cmd(
            "iot hub delete --name {} --resource-group {}".format(
                entity_name, entity_rg
                )
            )

    def generate_device_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_DEVICE if not edge else PREFIX_EDGE_DEVICE, length=32
            )
            for i in range(count)
        ]
        return names

    def generate_module_names(self, count=1):
        return [
            self.create_random_name(prefix=PREFIX_DEVICE_MODULE, length=32)
            for i in range(count)
        ]

    def generate_config_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_CONFIG if not edge else PREFIX_EDGE_CONFIG, length=32
            )
            for i in range(count)
        ]
        return names

    def generate_job_names(self, count=1):
        return [
            self.create_random_name(prefix=PREFIX_JOB, length=32) for i in range(count)
        ]

    def tearDown(self):
        device_list = []
        device_list.extend(d["deviceId"] for d in self.cmd(
            f"iot hub device-identity list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        config_list = []
        config_list.extend(c["id"] for c in self.cmd(
            f"iot edge deployment list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        config_list.extend(c["id"] for c in self.cmd(
            f"iot hub configuration list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json())

        self.clean_up(device_ids=device_list, config_ids=config_list)

    def get_region(self):
        result = self.cmd(
            "iot hub show -n {}".format(self.entity_name)
        ).get_output_in_json()
        locations_set = result["properties"]["locations"]
        for loc in locations_set:
            if loc["role"] == "primary":
                return loc["location"]

    def get_hub_cstring(self, policy="iothubowner"):
        return self.cmd(
            "iot hub connection-string show -n {} -g {} --policy-name {}".format(
                self.entity_name, self.entity_rg, policy
            )
        ).get_output_in_json()["connectionString"]

    def set_cmd_auth_type(self, command: str, auth_type: str) -> str:
        if auth_type not in DATAPLANE_AUTH_TYPES:
            raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

        # cstring takes precedence
        if auth_type == "cstring":
            return f"{command} --login {self.connection_string}"

        return f"{command} --auth-type {auth_type}"


def disable_telemetry(test_function):
    def wrapper(*args, **kwargs):
        print("Disabling Telemetry.")
        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        test_function(*args, **kwargs)

    return wrapper
