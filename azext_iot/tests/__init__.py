# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
import io
import os
import pytest
import time

from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from azure.cli.testsdk import LiveScenarioTest
from contextlib import contextmanager
from typing import List
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.generators import generate_generic_id
from azure.cli.core._profile import Profile
from azure.cli.core.mock import DummyCli
from azext_iot.tests.conftest import get_context_path
from azext_iot.common import utility
from azext_iot.central.models.enum import Role

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_DEVICE_MODULE = "test-module-"
PREFIX_CONFIG = "test-config-"
PREFIX_EDGE_CONFIG = "test-edgedeploy-"
PREFIX_JOB = "test-job-"
USER_ROLE = "IoT Hub Data Contributor"
DEFAULT_CONTAINER = "devices"

APP_ID = os.environ.get("azext_iot_central_app_id")
APP_PRIMARY_KEY = os.environ.get("azext_iot_central_primarykey")
APP_SCOPE_ID = os.environ.get("azext_iot_central_scope_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
TOKEN = os.environ.get("azext_iot_central_token")
DNS_SUFFIX = os.environ.get("azext_iot_central_dns_suffix")
device_template_path = get_context_path(__file__, "central/json/device_template_int_test.json")
sync_command_params = get_context_path(__file__, "central/json/sync_command_args.json")

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)

ENTITY_RG = settings.env.azext_iot_testrg
ENTITY_NAME = settings.env.azext_iot_testhub if settings.env.azext_iot_testhub else "test-hub-" + generate_generic_id()
STORAGE_CONTAINER = (
    settings.env.azext_iot_teststoragecontainer if settings.env.azext_iot_teststoragecontainer else DEFAULT_CONTAINER
)
ROLE_ASSIGNMENT_REFRESH_TIME = 60


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

    def _create_device(self, **kwargs) -> (str, str):
        """
        kwargs:
            instance_of: template_id (str)
            simulated: if the device is to be simulated (bool)
        """
        device_id = self.create_random_name(prefix="aztest", length=24)
        device_name = self.create_random_name(prefix="aztest", length=24)

        command = "iot central device create --app-id {} -d {} --device-name {}".format(
            APP_ID, device_id, device_name
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        checks = [
            self.check("enabled", True),
            self.check("displayName", device_name),
            self.check("id", device_id),
        ]

        template = kwargs.get("template")
        if template:
            command = command + " --template {}".format(template)
            checks.append(self.check("template", template))

        simulated = bool(kwargs.get("simulated"))
        if simulated:
            command = command + " --simulated"

        checks.append(self.check("simulated", simulated))

        self.cmd(command, checks=checks)
        return (device_id, device_name)

    def _create_users(self,):

        users = []
        for role in Role:
            user_id = self.create_random_name(prefix="aztest", length=24)
            email = user_id + "@microsoft.com"
            command = "iot central user create --app-id {} --user-id {} -r {} --email {}".format(
                APP_ID, user_id, role.name, email,
            )

            checks = [
                self.check("id", user_id),
                self.check("email", email),
                self.check("type", "email"),
                self.check("roles[0].role", role.value),
            ]
            users.append(self.cmd(command, checks=checks).get_output_in_json())

        return users

    def _delete_user(self, user_id) -> None:
        self.cmd(
            "iot central user delete --app-id {} --user-id {}".format(APP_ID, user_id),
            checks=[self.check("result", "success")],
        )

    def _create_api_tokens(self,):

        tokens = []
        for role in Role:
            token_id = self.create_random_name(prefix="aztest", length=24)
            command = "iot central api-token create --app-id {} --token-id {} -r {}".format(
                APP_ID, token_id, role.name,
            )

            checks = [
                self.check("id", token_id),
                self.check("roles[0].role", role.value),
            ]

            tokens.append(self.cmd(command, checks=checks).get_output_in_json())
        return tokens

    def _delete_api_token(self, token_id) -> None:
        self.cmd(
            "iot central api-token delete --app-id {} --token-id {}".format(
                APP_ID, token_id
            ),
            checks=[self.check("result", "success")],
        )

    def _wait_for_provisioned(self, device_id):
        command = "iot central device show --app-id {} -d {}".format(APP_ID, device_id)
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        while True:
            result = self.cmd(command)
            device = result.get_output_in_json()

            # return when its provisioned
            if device.get("provisioned"):
                return

            # wait 10 seconds for provisioning to complete
            time.sleep(10)

    def _delete_device(self, device_id) -> None:

        command = "iot central device delete --app-id {} -d {} ".format(
            APP_ID, device_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        self.cmd(command, checks=[self.check("result", "success")])

    def _create_device_template(self):
        template = utility.process_json_arg(
            device_template_path, argument_name="device_template_path"
        )
        template_name = template["displayName"]
        template_id = template_name + "id"

        command = "iot central device-template create --app-id {} --device-template-id {} -k '{}'".format(
            APP_ID, template_id, device_template_path
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        result = self.cmd(command, checks=[self.check("displayName", template_name), ],)
        json_result = result.get_output_in_json()

        assert json_result["@id"] == template_id
        return (template_id, template_name)

    def _delete_device_template(self, template_id):
        attempts = range(0, 10)
        command = "iot central device-template delete --app-id {} --device-template-id {}".format(
            APP_ID, template_id
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        # retry logic to delete the template
        for _ in attempts:
            try:
                self.cmd(command, checks=[self.check("result", "success")])
                return
            except:
                time.sleep(10)

    def _list_roles(self):
        return self.cmd(
            "iot central role list --app-id {}".format(
                APP_ID)
        ).get_output_in_json()

    def _get_credentials(self, device_id):
        return self.cmd(
            "iot central device show-credentials --app-id {} -d {}".format(
                APP_ID, device_id
            )
        ).get_output_in_json()

    def _get_validate_messages_output(
        self, device_id, enqueued_time, duration=60, max_messages=1, asserts=None
    ):
        if not asserts:
            asserts = []

        output = self.command_execute_assert(
            "iot central diagnostics validate-messages"
            " --app-id {} "
            " -d {} "
            " --et {} "
            " --duration {} "
            " --mm {} -y --style json".format(
                APP_ID, device_id, enqueued_time, duration, max_messages
            ),
            asserts,
        )

        if not output:
            output = ""

        return output

    def _get_monitor_events_output(self, device_id, enqueued_time, asserts=None):
        if not asserts:
            asserts = []

        output = self.command_execute_assert(
            "iot central diagnostics monitor-events -n {} -d {} --et {} --to 1 -y".format(
                APP_ID, device_id, enqueued_time
            ),
            asserts,
        )

        if not output:
            output = ""

        return output

    def _appendOptionalArgsToCommand(self, command: str, token: str, dnsSuffix: str):
        if token:
            command = command + ' --token "{}"'.format(token)
        if dnsSuffix:
            command = command + ' --central-dns-suffix "{}"'.format(dnsSuffix)

        return command


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

                new_hub = self.cmd(
                    "iot hub show -n {} -g {}".format(self.entity_name, self.entity_rg)
                ).get_output_in_json()

                account = self.cmd("account show").get_output_in_json()
                user = account["user"]

                # assign IoT Hub Data Contributor role to current user
                self.cmd(
                    '''role assignment create --assignee "{}" --role "{}" --scope "{}"'''.format(
                        user["name"], USER_ROLE, new_hub["id"]
                    )
                )

                profile = Profile(cli_ctx=DummyCli())
                profile.refresh_accounts()
                time.sleep(ROLE_ASSIGNMENT_REFRESH_TIME)

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

    @pytest.fixture(scope='class', autouse=True)
    def tearDownSuite(self):
        yield None
        if not settings.env.azext_iot_testhub:
            self.cmd(
                "iot hub delete --name {} --resource-group {}".format(
                    ENTITY_NAME, ENTITY_RG
                )
            )


def disable_telemetry(test_function):
    def wrapper(*args, **kwargs):
        print("Disabling Telemetry.")
        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        test_function(*args, **kwargs)

    return wrapper
