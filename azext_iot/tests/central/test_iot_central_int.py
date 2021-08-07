# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
import os
import time

from azext_iot.tests.conftest import get_context_path

from azure.iot.device import Message
from azext_iot.common import utility
from azext_iot.central.models.enum import Role
from azext_iot.monitor.parsers import strings

from azext_iot.tests import CaptureOutputLiveScenarioTest, helpers

APP_ID = os.environ.get("azext_iot_central_app_id")
APP_PRIMARY_KEY = os.environ.get("azext_iot_central_primarykey")
APP_SCOPE_ID = os.environ.get("azext_iot_central_scope_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
TOKEN = os.environ.get("azext_iot_central_token")
DNS_SUFFIX = os.environ.get("azext_iot_central_dns_suffix")
device_template_path = get_context_path(__file__, "json/device_template_int_test.json")
sync_command_params = get_context_path(__file__, "json/sync_command_args.json")

if not all([APP_ID]):
    raise ValueError("Set azext_iot_central_app_id to run central integration tests.")


class TestIotCentral(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        super(TestIotCentral, self).__init__(test_scenario=test_scenario)

    def test_central_monitor_events(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id)
        credentials = self._get_credentials(device_id)

        device_client = helpers.dps_connect_device(device_id, credentials)

        enqueued_time = utility.calculate_millisec_since_unix_epoch_utc() - 10000

        payload = {"Bool": True}
        msg = Message(
            data=json.dumps(payload),
            content_encoding="utf-8",
            content_type="application/json",
        )
        device_client.send_message(msg)

        # Test with invalid app-id
        self.cmd(
            "iot central diagnostics monitor-events --app-id {} -y".format(
                APP_ID + "zzz"
            ),
            expect_failure=True,
        )

        # Ensure no failure
        output = self._get_monitor_events_output(device_id, enqueued_time)

        self._delete_device(device_id)
        self._delete_device_template(template_id)
        assert '"Bool": true' in output
        assert device_id in output

    def test_central_validate_messages_success(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id)
        credentials = self._get_credentials(device_id)

        device_client = helpers.dps_connect_device(device_id, credentials)

        enqueued_time = utility.calculate_millisec_since_unix_epoch_utc() - 10000

        payload = {"Bool": True}
        msg = Message(
            data=json.dumps(payload),
            content_encoding="utf-8",
            content_type="application/json",
        )
        device_client.send_message(msg)

        # Validate the messages
        output = self._get_validate_messages_output(device_id, enqueued_time)

        self._delete_device(device_id)
        self._delete_device_template(template_id)

        assert output
        assert "Successfully parsed 1 message(s)" in output
        assert "No errors detected" in output

    def test_central_validate_messages_issues_detected(self):
        expected_messages = []
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id)
        credentials = self._get_credentials(device_id)

        device_client = helpers.dps_connect_device(device_id, credentials)

        enqueued_time = utility.calculate_millisec_since_unix_epoch_utc() - 10000

        # Invalid encoding
        payload = {"Bool": True}
        msg = Message(data=json.dumps(payload), content_type="application/json")
        device_client.send_message(msg)
        expected_messages.append(strings.invalid_encoding(""))

        # Content type mismatch (e.g. non application/json)
        payload = {"Bool": True}
        msg = Message(data=json.dumps(payload), content_encoding="utf-8")
        device_client.send_message(msg)
        expected_messages.append(strings.content_type_mismatch("", "application/json"))

        # Invalid type
        payload = {"Bool": 123}
        msg = Message(
            data=json.dumps(payload),
            content_encoding="utf-8",
            content_type="application/json",
        )
        device_client.send_message(msg)
        expected_messages.append(
            strings.invalid_primitive_schema_mismatch_template("Bool", "boolean", 123)
        )

        # Telemetry not defined
        payload = {"NotPresentInTemplate": True}
        msg = Message(
            data=json.dumps(payload),
            content_encoding="utf-8",
            content_type="application/json",
        )
        device_client.send_message(msg)
        # this error is harder to build from strings because we have to construct a whole template for it
        expected_messages.append(
            "Following capabilities have NOT been defined in the device template '['NotPresentInTemplate']'"
        )

        # Invalid JSON
        payload = '{"asd":"def}'
        msg = Message(
            data=payload, content_encoding="utf-8", content_type="application/json",
        )
        device_client.send_message(msg)
        expected_messages.append(strings.invalid_json())

        # Validate the messages
        output = self._get_validate_messages_output(
            device_id, enqueued_time, max_messages=len(expected_messages)
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

        assert output

        expected_issues = [
            "No encoding found. Expected encoding 'utf-8' to be present in message header.",
            "Content type '' is not supported. Expected Content type is 'application/json'.",
            "Datatype of telemetry field 'Bool' does not match the datatype boolean.",
            "Data sent by the device : 123.",
            "For more information, see: https://aka.ms/iotcentral-payloads",
            "Following capabilities have NOT been defined in the device template '['NotPresentInTemplate']'",
            "Invalid JSON format",
        ]
        for issue in expected_issues:
            assert issue in output

    def test_central_user_methods_CRD(self):
        users = self._create_users()

        self.cmd(
            "iot central user show --app-id {} --user-id {}".format(
                APP_ID, users[0].get("id")
            ),
        )

        result = self.cmd(
            "iot central user list --app-id {}".format(APP_ID,),
        ).get_output_in_json()

        user_list = result.get("value")

        for user in users:
            self._delete_user(user.get("id"))

        for user in users:
            assert user in user_list

    def test_central_api_token_methods_CRD(self):
        tokens = self._create_api_tokens()

        self.cmd(
            "iot central api-token show --app-id {} --token-id {}".format(
                APP_ID, tokens[0].get("id")
            ),
        )

        result = self.cmd(
            "iot central api-token list --app-id {}".format(APP_ID,),
        ).get_output_in_json()

        token_list = result.get("value")

        for token in tokens:
            self._delete_api_token(token.get("id"))

        for token in tokens:
            token_info_basic = {
                "expiry": token.get("expiry"),
                "id": token.get("id"),
                "roles": token.get("roles"),
            }
            assert token_info_basic in token_list

    def test_central_roles_list(self):
        result = self._list_roles()
        # assert object is empty or populated but not null
        assert result is not None and (result == {} or bool(result) is True)

    def test_central_run_command_root_level(self):
        command_name = "testRootCommand"
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id, simulated=True)

        self._wait_for_provisioned(device_id)

        run_command_result = self.cmd(
            "iot central device command run"
            " -n {}"
            " -d {}"
            " --cn {}"
            " -k '{}'"
            "".format(APP_ID, device_id, command_name, sync_command_params)
        )

        show_command_result = self.cmd(
            "iot central device command history"
            " -n {}"
            " -d {}"
            " --cn {}"
            "".format(APP_ID, device_id, command_name)
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

        run_result = run_command_result.get_output_in_json()
        show_result = show_command_result.get_output_in_json()

        # from file indicated by `sync_command_params`
        assert run_result["request"] == {"argument": "value"}

        # check that run result and show result indeed match
        assert run_result["response"] == show_result["value"][0]["response"]

    def test_central_run_command_component(self):
        interface_id = "dtmiIntTestDeviceTemplateV33jl"
        command_name = "testCommand"
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id, simulated=True)

        self._wait_for_provisioned(device_id)

        run_command_result = self.cmd(
            "iot central device command run"
            " -n {}"
            " -d {}"
            " -i {}"
            " --cn {}"
            " -k '{}'"
            "".format(
                APP_ID, device_id, interface_id, command_name, sync_command_params
            )
        )

        show_command_result = self.cmd(
            "iot central device command history"
            " -n {}"
            " -d {}"
            " -i {}"
            " --cn {}"
            "".format(APP_ID, device_id, interface_id, command_name)
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

        run_result = run_command_result.get_output_in_json()
        show_result = show_command_result.get_output_in_json()

        # from file indicated by `sync_command_params`
        assert run_result["request"] == {"argument": "value"}

        # check that run result and show result indeed match
        assert run_result["response"] == show_result["value"][0]["response"]

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
