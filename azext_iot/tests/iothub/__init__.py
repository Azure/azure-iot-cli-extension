# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from contextlib import ExitStack

from azure.cli.core.azclierror import CLIInternalError
from azext_iot.tests.helpers import (
    add_test_tag,
    clean_up_iothub_device_config,
    create_storage_account,
    DATAPLANE_AUTH_TYPES as SERVICE_AUTH_TYPES,
    set_cmd_auth_type
)
from azext_iot.tests.settings import (
    DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL, HUB_TEST_LOCATION
)
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests import CaptureOutputLiveScenarioTest

from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.test_constants import ResourceTypes
from azext_iot.tests.iothub._integration_helpers import (
    assert_hub_policy, assign_role_with_propagation, delete_known_devices, get_or_create_hub, scope_known_hub
)
from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider
from azext_iot._factory import iot_hub_service_factory

DATAPLANE_AUTH_TYPES = SERVICE_AUTH_TYPES

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
ENTITY_NAME = settings.env.azext_iot_testhub or "test-hub-" + generate_generic_id()
STORAGE_ACCOUNT = settings.env.azext_iot_teststorageaccount or "hubstore" + generate_generic_id()[:4]
STORAGE_CONTAINER = settings.env.azext_iot_teststoragecontainer or DEFAULT_CONTAINER
MAX_RBAC_ASSIGNMENT_TRIES = settings.env.azext_iot_rbac_max_tries or 10
ROLE_ASSIGNMENT_REFRESH_TIME = 120


@pytest.mark.usefixtures("fixture_provision_existing_hub_role", "fixture_provision_existing_hub_device_config")
class IoTLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario, add_data_contributor=True):
        assert test_scenario
        self.entity_rg = ENTITY_RG
        self.entity_name = ENTITY_NAME
        self._generated_device_ids = []
        super(IoTLiveScenarioTest, self).__init__(test_scenario)

        if hasattr(self, 'storage_cstring'):
            self._create_storage_account()

        client = iot_hub_service_factory(self.cli_ctx).iot_hub_resource
        if not settings.env.azext_iot_testhub:
            target_hub, _ = get_or_create_hub(
                client, self.entity_name, self.entity_rg, self._create_hub
            )
        else:
            target_hub = client.get(resource_group_name=self.entity_rg, resource_name=self.entity_name)
        assert_hub_policy(target_hub)

        if add_data_contributor:
            self._add_data_contributor(target_hub)

        self.host_name = target_hub["properties"]["hostName"]
        # Device-facing hostname (GWv2 hubs expose a distinct deviceHostName; classic hubs reuse hostName)
        self.device_host_name = target_hub["properties"].get("deviceHostName") or self.host_name
        self.region = target_hub["location"]
        add_test_tag(
            cmd=self.cmd,
            name=self.entity_name,
            rg=self.entity_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=test_scenario
        )

    def _create_hub(self):
        command = (
            f"iot hub create --name {self.entity_name} --resource-group {self.entity_rg} "
            f"--location {HUB_TEST_LOCATION} --disable-local-auth true --sku S1"
        )
        if hasattr(self, "storage_cstring"):
            command += f" --fc {self.storage_container} --fcs {self.storage_cstring}"
        self.cmd(command)

    def cmd(self, command, *args, **kwargs):
        command = scope_known_hub(
            command, self.entity_rg,
            (self.entity_name, getattr(self, "host_name", None), getattr(self, "device_host_name", None)),
        )
        return super().cmd(command, *args, **kwargs)

    @property
    def connection_string(self):
        # Only metadata/offline-token tests need a Hub policy key. Service calls use Entra.
        return self.get_hub_cstring()

    def _add_data_contributor(self, target_hub):
        account = self.cmd("account show").get_output_in_json()
        user = account["user"]

        if user["name"] is None:
            raise CLIInternalError("User not found")  # pylint: disable=broad-except

        assign_role_with_propagation(
            role=USER_ROLE,
            scope=target_hub["id"],
            assignee=user["name"],
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES,
            wait=ROLE_ASSIGNMENT_REFRESH_TIME,
        )

    def generate_device_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_DEVICE if not edge else PREFIX_EDGE_DEVICE, length=32
            )
            for i in range(count)
        ]
        self._generated_device_ids.extend(names)
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

    def _create_storage_account(self):
        """
        Create a storage account and container if a storage account was not created yet.
        Populate the following variables if needed:
          - storage_account_name
          - storage_container
          - storage_cstring
        """
        self.storage_account_name = STORAGE_ACCOUNT
        self.storage_container = STORAGE_CONTAINER

        self.storage_cstring = create_storage_account(
            cmd=self.cmd,
            account_name=self.storage_account_name,
            container_name=self.storage_container,
            rg=self.entity_rg,
            resource_name=self.entity_name,
            create_account=(not settings.env.azext_iot_teststorageaccount),
            location=HUB_TEST_LOCATION,
        )

    def _delete_storage_account(self):
        """
        Delete the storage account if it was created.
        """
        if not settings.env.azext_iot_teststorageaccount:
            self.cmd(
                "storage account delete -n {} -g {} -y".format(
                    self.storage_account_name, self.entity_rg
                ),
            )

        elif not settings.env.azext_iot_teststoragecontainer:
            self.cmd(
                "storage container delete -n {} --connection-string '{}'".format(
                    self.storage_account_name, self.storage_cstring
                ),
            )

    def tearDown(self):
        if not settings.env.azext_iot_testhub:
            with ExitStack() as cleanup:
                cleanup.callback(clean_up_iothub_device_config, hub_name=self.entity_name, rg=self.entity_rg)
                if self._generated_device_ids:
                    provider = DeviceIdentityProvider(
                        cmd=self, hub_name=self.entity_name, rg=self.entity_rg, auth_type_dataplane="login"
                    )
                    # A fresh identity may not appear in the query used by legacy cleanup.
                    for device_id in dict.fromkeys(self._generated_device_ids):
                        cleanup.callback(delete_known_devices, provider.service_sdk.devices, [device_id])

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

    def get_device_cstring(self, device_id):
        return self.cmd(
            f"iot hub device-identity connection-string show -d {device_id} "
            f"-n {self.entity_name} -g {self.entity_rg} --auth-type login"
        ).get_output_in_json()["connectionString"]

    def get_device_key(self, device_id):
        return self.cmd(
            f"iot hub device-identity show -d {device_id} "
            f"-n {self.entity_name} -g {self.entity_rg} --auth-type login"
        ).get_output_in_json()["authentication"]["symmetricKey"]["primaryKey"]

    def set_cmd_auth_type(self, command: str, auth_type: str) -> str:
        return set_cmd_auth_type(
            command=command, auth_type=auth_type, cstring=self.connection_string if auth_type == "cstring" else None
        )

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        # Hub deletion is handled by the session-scoped _cleanup_dynamic_hub
        # fixture in conftest.py to avoid race conditions between classes.
        if hasattr(self, "storage_cstring"):
            self._delete_storage_account()
