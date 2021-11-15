# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from time import sleep
from typing import List
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests import CaptureOutputLiveScenarioTest

from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.shared import AuthenticationTypeDataplane

DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    AuthenticationTypeDataplane.login.value,
    "cstring",
]

PRIMARY_THUMBPRINT = create_self_signed_certificate(
    subject="aziotcli", valid_days=1, cert_output_dir=None
)["thumbprint"]
SECONDARY_THUMBPRINT = create_self_signed_certificate(
    subject="aziotcli", valid_days=1, cert_output_dir=None
)["thumbprint"]

DEVICE_TYPES = ["non-edge", "edge"]
PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_DEVICE_MODULE = "test-module-"
PREFIX_CONFIG = "test-config-"
PREFIX_EDGE_CONFIG = "test-edgedeploy-"
PREFIX_JOB = "test-job-"
USER_ROLE = "IoT Hub Data Contributor"
DEFAULT_CONTAINER = "devices"

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)

ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_NAME = settings.env.azext_iot_testhub if settings.env.azext_iot_testhub else "test-hub-" + generate_generic_id()
STORAGE_CONTAINER = (
    settings.env.azext_iot_teststoragecontainer if settings.env.azext_iot_teststoragecontainer else DEFAULT_CONTAINER
)
ROLE_ASSIGNMENT_REFRESH_TIME = 120


class IoTLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario
        self.entity_rg = ENTITY_RG
        self.entity_name = ENTITY_NAME
        super(IoTLiveScenarioTest, self).__init__(test_scenario)

        if not settings.env.azext_iot_testhub:
            hubs_list = self.cmd(
                '''iot hub list -g "{}"'''.format(self.entity_rg)
            ).get_output_in_json()

            target_hub = None
            for hub in hubs_list:
                if hub["name"] == self.entity_name:
                    target_hub = hub
                    break

            if not target_hub:
                if settings.env.azext_iot_teststorageaccount:
                    storage_account_connenction = self.cmd(
                        "storage account show-connection-string --name {}".format(
                            settings.env.azext_iot_teststorageaccount
                        )
                    ).get_output_in_json()

                    self.cmd(
                        "iot hub create --name {} --resource-group {} --fc {} --fcs {} --sku S1 ".format(
                            self.entity_name, self.entity_rg,
                            STORAGE_CONTAINER, storage_account_connenction["connectionString"]
                        )
                    )
                else:
                    self.cmd(
                        "iot hub create --name {} --resource-group {} --sku S1 ".format(
                            self.entity_name, self.entity_rg
                        )
                    )

                sleep(ROLE_ASSIGNMENT_REFRESH_TIME)

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

    def get_role_assignments(self, scope, role):

        role_assignments = self.cmd(
            'role assignment list --scope "{}" --role "{}"'.format(
                scope, role
            )
        ).get_output_in_json()

        return role_assignments

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot hub delete --name {} --resource-group {}".format(
                    ENTITY_NAME, ENTITY_RG
                )
            )
