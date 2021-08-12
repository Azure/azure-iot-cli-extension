# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import time

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.conftest import get_context_path
from azext_iot.common import utility
from azext_iot.central.models.enum import Role

APP_ID = os.environ.get("azext_iot_central_app_id")
APP_PRIMARY_KEY = os.environ.get("azext_iot_central_primarykey")
APP_SCOPE_ID = os.environ.get("azext_iot_central_scope_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
TOKEN = os.environ.get("azext_iot_central_token")
DNS_SUFFIX = os.environ.get("azext_iot_central_dns_suffix")
device_template_path = get_context_path(__file__, "json/device_template_int_test.json")
sync_command_params = get_context_path(__file__, "json/sync_command_args.json")


class CentralLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        super(CentralLiveScenarioTest, self).__init__(test_scenario)

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
