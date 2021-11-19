# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import os

from azext_iot.tests.settings import (
    DynamoSettings,
    ENV_SET_TEST_IOTHUB_REQUIRED,
    ENV_SET_TEST_IOTHUB_OPTIONAL,
    ENV_SET_TEST_IOTDPS_OPTIONAL,
)
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.shared import AuthenticationTypeDataplane

DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    # AuthenticationTypeDataplane.login.value,
    "cstring",
]

CERT_NAME = "aziotcli"
CERT_PATH = "aziotcli-cert.pem"
WEBHOOK_URL = "https://www.test.test"
API_VERSION = "2019-03-31"

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_INDIVIDUAL_ENROLLMENT = "test-enrollment-"
PREFIX_GROUP_ENROLLMENT = "test-groupenroll-"

# Test Environment Variables
settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED,
    opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL + ENV_SET_TEST_IOTDPS_OPTIONAL
)
ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_DPS_NAME = settings.env.azext_iot_testdps if settings.env.azext_iot_testdps else "test-dps-" + generate_generic_id()
ENTITY_HUB_NAME = settings.env.azext_iot_testhub if settings.env.azext_iot_testhub else "test-hub-" + generate_generic_id()


class IoTDPSLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario
        self.entity_rg = ENTITY_RG
        self.entity_dps_name = ENTITY_DPS_NAME
        self.entity_hub_name = ENTITY_HUB_NAME
        super(IoTDPSLiveScenarioTest, self).__init__(test_scenario)

        # Create resources if needed
        if not settings.env.azext_iot_testdps:
            self.create_dps()
        if not settings.env.azext_iot_testhub:
            self.create_hub()

        # Prep the DPS for testing
        self._ensure_dps_hub_link()
        self._cleanup_enrollments()
        self.dps_cstring = self.get_dps_cstring()

        # Create the test certificate
        output_dir = os.getcwd()
        create_self_signed_certificate(
            subject=CERT_NAME, valid_days=1, cert_output_dir=output_dir, cert_only=True
        )

        # Kwargs
        base_enrollment_props = {
            "count": None,
            "metadata": None,
            "version": None,
        }
        self.kwargs["generic_dict"] = {
            **base_enrollment_props,
            "key": "value",
        }
        self.kwargs["twin_array_dict"] = {
            **base_enrollment_props,
            "values": [{"key1": "value1"}, {"key2": "value2"}],
        }

        # Other variables for DPS testing
        self.hub_host_name = "{}.azure-devices.net".format(ENTITY_HUB_NAME)

    def create_dps(self):
        """Create a device provisioning service for testing purposes."""
        dps_list = self.cmd(
            '''iot dps list -g "{}"'''.format(self.entity_rg)
        ).get_output_in_json()

        # Check if the generated name is already used
        target_dps = None
        for dps in dps_list:
            if dps["name"] == self.entity_dps_name:
                target_dps = dps
                break

        # Create the min version dps and assign the correct roles
        if not target_dps:
            self.cmd(
                "iot dps create --name {} --resource-group {} ".format(
                    self.entity_dps_name, self.entity_rg
                )
            )

    def create_hub(self):
        """Create an IoT hub for DPS testing purposes."""
        hubs_list = self.cmd(
            '''iot hub list -g "{}"'''.format(self.entity_rg)
        ).get_output_in_json()

        # Check if the generated name is already used
        target_hub = None
        for hub in hubs_list:
            if hub["name"] == self.entity_hub_name:
                target_hub = hub
                break

        # Create the min version hub and assign the correct roles
        if not target_hub:
            self.cmd(
                "iot hub create --name {} --resource-group {} --sku S1 ".format(
                    self.entity_hub_name, self.entity_rg
                )
            )

    def _ensure_dps_hub_link(self):
        hubs = self.cmd(
            "iot dps linked-hub list --dps-name {} -g {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        if not len(hubs) or not len(
            list(
                filter(
                    lambda linked_hub: linked_hub["name"]
                    == "{}.azure-devices.net".format(self.entity_hub_name),
                    hubs,
                )
            )
        ):
            self.cmd(
                "iot dps linked-hub create --dps-name {} -g {} --connection-string {} --location {}".format(
                    self.entity_dps_name, self.entity_rg, self.get_hub_cstring(), self.get_hub_region()
                )
            )

    def _cleanup_enrollments(self):
        """Delete all individual and group enrollments from the DPS."""
        enrollments = self.cmd(
            "iot dps enrollment list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        if len(enrollments) > 0:
            enrollment_ids = list(map(lambda x: x["registrationId"], enrollments))
            for id in enrollment_ids:
                self.cmd(
                    "iot dps enrollment delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, id
                    )
                )

        enrollment_groups = self.cmd(
            "iot dps enrollment-group list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        if len(enrollment_groups) > 0:
            enrollment_ids = list(map(lambda x: x["enrollmentGroupId"], enrollment_groups))
            for id in enrollment_ids:
                self.cmd(
                    "iot dps enrollment-group delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, id
                    )
                )

        self.cmd(
            "iot dps enrollment list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg),
            checks=self.is_empty(),
        )
        self.cmd(
            "iot dps enrollment-group list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg),
            checks=self.is_empty(),
        )

    def generate_device_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_DEVICE if not edge else PREFIX_EDGE_DEVICE, length=48
            )
            for i in range(count)
        ]
        return names

    def generate_enrollment_names(self, count=1, group=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_INDIVIDUAL_ENROLLMENT if not group else PREFIX_GROUP_ENROLLMENT, length=48
            )
            for i in range(count)
        ]
        return names

    def tearDown(self):
        if os.path.exists(CERT_PATH):
            os.remove(CERT_PATH)

    def get_hub_region(self):
        return self.cmd(
            "iot hub show -n {}".format(self.entity_hub_name)
        ).get_output_in_json()["location"]

    def get_hub_cstring(self, policy="iothubowner"):
        return self.cmd(
            "iot hub connection-string show -n {} -g {} --policy-name {}".format(
                self.entity_hub_name, self.entity_rg, policy
            )
        ).get_output_in_json()["connectionString"]

    def get_dps_cstring(self, policy="provisioningserviceowner"):
        return self.cmd(
            "iot dps connection-string show -n {} -g {} --policy-name {}".format(
                self.entity_dps_name, self.entity_rg, policy
            )
        ).get_output_in_json()["connectionString"]

    def set_cmd_auth_type(self, command: str, auth_type: str) -> str:
        if auth_type not in DATAPLANE_AUTH_TYPES:
            raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

        # cstring takes precedence
        if auth_type == "cstring":
            return f"{command} --login {self.dps_cstring}"

        # return command
        # Future iterations would support multiple auth-types
        return f"{command} --auth-type {auth_type}"

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        self.cmd(
            "iot dps linked-hub delete --dps-name {} --linked-hub {} --resource-group {}".format(
                ENTITY_DPS_NAME, self.hub_host_name, ENTITY_RG
            )
        )
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot hub delete --name {} --resource-group {}".format(
                    ENTITY_HUB_NAME, ENTITY_RG
                )
            )
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot dps delete --name {} --resource-group {}".format(
                    ENTITY_DPS_NAME, ENTITY_RG
                )
            )
