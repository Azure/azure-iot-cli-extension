# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import os
from time import sleep

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
    AuthenticationTypeDataplane.login.value,
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
USER_ROLE = "Device Provisioning Service Data Contributor"
MAX_HUB_RETRIES = 3

TEST_ENDORSEMENT_KEY = (
    "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1Q"
    "QsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3"
    "CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRI"
    "Dj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzB"
    "QQ1NpOJVhrsTrhyJzO7KNw=="
)

# Test Environment Variables
settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED,
    opt_env_set=list(set(ENV_SET_TEST_IOTHUB_OPTIONAL + ENV_SET_TEST_IOTDPS_OPTIONAL))
)
ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_DPS_NAME = settings.env.azext_iot_testdps if settings.env.azext_iot_testdps else "test-dps-" + generate_generic_id()
ENTITY_HUB_NAME = settings.env.azext_iot_testhub if settings.env.azext_iot_testhub else "test-dps-hub-" + generate_generic_id()
MAX_RBAC_ASSIGNMENT_TRIES = settings.env.azext_iot_rbac_max_tries if settings.env.azext_iot_rbac_max_tries else 10


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
        self._add_test_tag(test_tag=test_scenario)
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
            'iot dps list -g "{}"'.format(self.entity_rg)
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

        new_dps = self.cmd(
            "iot dps show --name {} --resource-group {} ".format(
                self.entity_dps_name, self.entity_rg
            )
        ).get_output_in_json()

        account = self.cmd("account show").get_output_in_json()
        user = account["user"]

        if user["name"] is None:
            raise Exception("User not found")

        tries = 0
        while tries < MAX_RBAC_ASSIGNMENT_TRIES:
            role_assignments = self.get_role_assignments(new_dps["id"], USER_ROLE)
            role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
            if user["name"] in role_assignment_principal_names:
                break
            # else assign DPS Data Contributor role to current user and check again
            self.cmd(
                '''role assignment create --assignee "{}" --role "{}" --scope "{}"'''.format(
                    user["name"], USER_ROLE, new_dps["id"]
                )
            )
            sleep(10)
            tries += 1

        if tries == MAX_RBAC_ASSIGNMENT_TRIES:
            raise Exception(
                "Reached max ({}) number of tries to assign RBAC role. Please re-run the test later "
                "or with more max number of tries.".format(MAX_RBAC_ASSIGNMENT_TRIES)
            )

    def create_hub(self):
        """Create an IoT hub for DPS testing purposes."""
        hub_state = None
        retries = 0
        while (not hub_state or hub_state.lower() != "succeeded") and retries < MAX_HUB_RETRIES:
            hubs_list = self.cmd(
                'iot hub list -g "{}"'.format(self.entity_rg)
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
                    "iot hub create --name {} --resource-group {} --sku S1 --tags dpsname={}".format(
                        self.entity_hub_name, self.entity_rg, self.entity_dps_name
                    )
                )

            hub_state = self.cmd(
                "iot hub show --name {} --resource-group {}".format(
                    self.entity_hub_name, self.entity_rg,
                )
            ).get_output_in_json()["properties"]["provisioningState"]
            if hub_state.lower() != "succeeded":
                # Hub is in bad state, need to recreate
                self.entity_hub_name = "test-dps-hub-" + generate_generic_id()
                retries += 1
                self.cmd(
                    "iot hub delete --name {} --resource-group {}".format(
                        self.entity_hub_name, self.entity_rg
                    )
                )

    def _ensure_dps_hub_link(self):
        hubs = self.cmd(
            "iot dps linked-hub list --dps-name {} -g {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        hub_names = [hub["name"] for hub in hubs]
        if "{}.azure-devices.net".format(self.entity_hub_name) not in hub_names:
            self.cmd(
                "iot dps linked-hub create --dps-name {} -g {} --connection-string {} --location {}".format(
                    self.entity_dps_name, self.entity_rg, self.get_hub_cstring(), self.get_hub_region()
                )
            )

    def _add_test_tag(self, test_tag):
        tags = self.cmd(
            "iot dps show -n {} -g {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()["tags"]

        if tags.get(test_tag):
            tags[test_tag] = int(tags[test_tag]) + 1
        else:
            tags[test_tag] = 1
        new_tags = " ".join(f"{k}={v}" for k, v in tags.items())

        self.cmd(
            "iot dps update -n {} -g {} --tags {}".format(
                self.entity_dps_name,
                self.entity_rg,
                new_tags
            )
        )

        self.cmd(
            "iot hub update -n {} -g {} --tags {} dpsname={}".format(
                self.entity_hub_name,
                self.entity_rg,
                new_tags,
                self.entity_dps_name
            )
        )

    def _cleanup_enrollments(self):
        """Delete all individual and group enrollments from the DPS."""
        enrollments = self.cmd(
            "iot dps enrollment list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        if enrollments:
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
        if enrollment_groups:
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
        if os.path.exists(CERT_PATH):
            os.remove(CERT_PATH)
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot hub delete --name {} --resource-group {}".format(
                    ENTITY_HUB_NAME, ENTITY_RG
                )
            )
        if not settings.env.azext_iot_testdps:
            self.cmd(
                "iot dps delete --name {} --resource-group {}".format(
                    ENTITY_DPS_NAME, ENTITY_RG
                )
            )
