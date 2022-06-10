# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import os
from time import sleep
from azext_iot.tests.helpers import add_test_tag

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
from azext_iot.tests.test_constants import ResourceTypes
from knack.log import get_logger


logger = get_logger(__name__)
DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    AuthenticationTypeDataplane.login.value,
    "cstring",
]

CERT_NAME = "aziotcli"
CERT_PATH = "aziotcli-cert.pem"
KEY_PATH = "aziotcli-key.pem"
SECONDARY_CERT_NAME = "aziotcli2"
SECONDARY_CERT_PATH = "aziotcli2-cert.pem"
SECONDARY_KEY_PATH = "aziotcli2-key.pem"
WEBHOOK_URL = "https://www.test.test"
API_VERSION = "2019-03-31"

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_INDIVIDUAL_ENROLLMENT = "test-enrollment-"
PREFIX_GROUP_ENROLLMENT = "test-groupenroll-"
USER_ROLE = "Device Provisioning Service Data Contributor"
HUB_USER_ROLE = "IoT Hub Data Contributor"
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
    def __init__(self, test_scenario, cert_only: bool = True):
        assert test_scenario
        self.entity_rg = ENTITY_RG
        self.entity_dps_name = ENTITY_DPS_NAME
        self.entity_hub_name = ENTITY_HUB_NAME
        self.tracked_certs = []
        super(IoTDPSLiveScenarioTest, self).__init__(test_scenario)

        # Create resources if needed
        if not settings.env.azext_iot_testdps:
            self.create_dps()
        if not settings.env.azext_iot_testhub:
            self.create_hub()

        # Prep the DPS for testing
        add_test_tag(
            cmd=self.cmd,
            name=self.entity_dps_name,
            rg=self.entity_rg,
            rtype=ResourceTypes.dps.value,
            test_tag=test_scenario
        )
        add_test_tag(
            cmd=self.cmd,
            name=self.entity_hub_name,
            rg=self.entity_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=test_scenario
        )
        self.dps_cstring = self.get_dps_cstring()
        self.hub_cstring = self.get_hub_cstring()
        self._ensure_dps_hub_link()
        self._cleanup_enrollments()

        # Create the test certificate
        self.thumbprint = self.create_test_cert(cert_only=cert_only)

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

    def create_test_cert(self, subject=CERT_NAME, cert_only=True, file_prefix=None):
        output_dir = os.getcwd()
        thumbprint = create_self_signed_certificate(
            subject=subject, valid_days=1, cert_output_dir=output_dir, cert_only=cert_only, file_prefix=file_prefix
        )["thumbprint"]
        self.tracked_certs.append(CERT_PATH)
        if not cert_only:
            self.tracked_certs.append(KEY_PATH)
        return thumbprint

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
            target_dps = self.cmd(
                "iot dps create --name {} --resource-group {} ".format(
                    self.entity_dps_name, self.entity_rg
                )
            ).get_output_in_json()

        account = self.cmd("account show").get_output_in_json()
        user = account["user"]
        if user["name"] is None:
            raise Exception("User not found")

        tries = 0
        while tries < MAX_RBAC_ASSIGNMENT_TRIES:
            role_assignments = self.get_role_assignments(target_dps["id"], USER_ROLE)
            role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
            if user["name"] in role_assignment_principal_names:
                break
            # else assign DPS Data Contributor role to current user and check again
            self.cmd(
                '''role assignment create --assignee "{}" --role "{}" --scope "{}"'''.format(
                    user["name"], USER_ROLE, target_dps["id"]
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
            target_hub = self.cmd(
                "iot hub create --name {} --resource-group {} --sku S1 --tags dpsname={}".format(
                    self.entity_hub_name, self.entity_rg, self.entity_dps_name
                )
            ).get_output_in_json()

    def add_hub_permissions(self):
        """Add IoT Hub permission for dataplane operations."""
        target_hub = self.cmd(
            "iot hub show -n {} -g {}".format(self.entity_hub_name, self.entity_rg)
        ).get_output_in_json()

        account = self.cmd("account show").get_output_in_json()
        user = account["user"]

        if user["name"] is None:
            raise Exception("User not found")

        tries = 0
        while tries < MAX_RBAC_ASSIGNMENT_TRIES:
            role_assignments = self.get_role_assignments(target_hub["id"], HUB_USER_ROLE)
            role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
            if user["name"] in role_assignment_principal_names:
                break
            # else assign IoT Hub Data Contributor role to current user and check again
            self.cmd(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    user["name"], HUB_USER_ROLE, target_hub["id"]
                )
            )
            sleep(10)
            tries += 1

        if tries == MAX_RBAC_ASSIGNMENT_TRIES:
            raise Exception(
                "Reached max ({}) number of tries to assign RBAC role. Please re-run the test later "
                "or with more max number of tries.".format(MAX_RBAC_ASSIGNMENT_TRIES)
            )

    def _ensure_dps_hub_link(self):
        hubs = self.cmd(
            "iot dps linked-hub list --dps-name {} -g {}".format(self.entity_dps_name, self.entity_rg)
        ).get_output_in_json()
        hub_names = [hub["name"] for hub in hubs]
        if "{}.azure-devices.net".format(self.entity_hub_name) not in hub_names:
            self.cmd(
                "iot dps linked-hub create --dps-name {} -g {} --connection-string {} --location {}".format(
                    self.entity_dps_name, self.entity_rg, self.hub_cstring, self.get_hub_region()
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

        # Check again only if needed
        if enrollments:
            self.cmd(
                "iot dps enrollment list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg),
                checks=self.is_empty(),
            )

        if enrollment_groups:
            self.cmd(
                "iot dps enrollment-group list --dps-name {} -g  {}".format(self.entity_dps_name, self.entity_rg),
                checks=self.is_empty(),
            )

    def check_hub_device(self, device: str, auth_type: str, key: str = None, thumbprint: str = None):
        """Helper method to check whether a device exists in a hub."""

        device_auth = self.cmd(
            "iot hub device-identity show -l {} -d {}".format(
                self.hub_cstring,
                device,
            )
        ).get_output_in_json()["authentication"]
        assert auth_type == device_auth["type"]
        if key:
            assert key == device_auth["symmetricKey"]["primaryKey"]
        if thumbprint:
            assert thumbprint == device_auth["x509Thumbprint"]["primaryThumbprint"]

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
            for _ in range(count)
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

    def get_dps_id_scope(self):
        return self.cmd(
            "iot dps show -n {} -g {}".format(
                self.entity_dps_name, self.entity_rg
            )
        ).get_output_in_json()["properties"]["idScope"]

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
        for cert in self.tracked_certs:
            if os.path.exists(cert):
                try:
                    os.remove(cert)
                except OSError as e:
                    logger.error(f"Failed to remove {cert}. {e}")
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
