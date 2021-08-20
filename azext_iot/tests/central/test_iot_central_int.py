# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
import os

from azext_iot.tests.conftest import get_context_path

from azure.iot.device import Message
from azext_iot.common import utility
from azext_iot.monitor.parsers import strings
from azext_iot.tests import helpers
from azext_iot.tests.central import CentralLiveScenarioTest

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


class TestIotCentral(CentralLiveScenarioTest):
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
