# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
import os
import time

from .conftest import get_context_path

from azure.iot.device import Message
from azext_iot.common import utility
from azext_iot.central.models.enum import DeviceStatus, Role
from azext_iot.monitor.parsers import strings

from . import CaptureOutputLiveScenarioTest, helpers

APP_ID = os.environ.get("azext_iot_central_app_id")

device_template_path = get_context_path(
    __file__, "central/json/device_template_int_test.json"
)
sync_command_params = get_context_path(__file__, "central/json/sync_command_args.json")

if not all([APP_ID]):
    raise ValueError("Set azext_iot_central_app_id to run central integration tests.")


class TestIotCentral(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        super(TestIotCentral, self).__init__(test_scenario=test_scenario)

    def test_central_device_twin_show_fail(self):
        (device_id, _) = self._create_device()

        # Verify incorrect app-id throws error
        self.cmd(
            "iot central app device-twin show --app-id incorrect-app --device-id {}".format(
                device_id
            ),
            expect_failure=True,
        )
        # Verify incorrect device-id throws error
        self.cmd(
            "iot central app device-twin show --app-id {} --device-id incorrect-device".format(
                APP_ID
            ),
            expect_failure=True,
        )

        self._delete_device(device_id)

    def test_central_device_twin_show_success(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(instance_of=template_id, simulated=True)

        # wait about a few seconds for simulator to kick in so that provisioning completes
        time.sleep(60)

        self.cmd(
            "iot central app device-twin show --app-id {} --device-id {}".format(
                APP_ID, device_id
            ),
            checks=[self.check("deviceId", device_id)],
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

    def test_central_monitor_events(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(instance_of=template_id)
        credentials = self._get_credentials(device_id)

        device_client = helpers.dps_connect_device(device_id, credentials)

        payload = {"Bool": True}
        msg = Message(
            data=json.dumps(payload),
            content_encoding="utf-8",
            content_type="application/json",
        )
        device_client.send_message(msg)

        enqueued_time = utility.calculate_millisec_since_unix_epoch_utc() - 10000

        # Test with invalid app-id
        self.cmd(
            "iot central app monitor-events --app-id {} -y".format(APP_ID + "zzz"),
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
        (device_id, _) = self._create_device(instance_of=template_id)
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
        (device_id, _) = self._create_device(instance_of=template_id)
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

    def test_central_device_methods_CRD(self):
        (device_id, device_name) = self._create_device()

        self.cmd(
            "iot central app device show --app-id {} -d {}".format(APP_ID, device_id),
            checks=[
                self.check("approved", True),
                self.check("displayName", device_name),
                self.check("id", device_id),
                self.check("simulated", False),
            ],
        )

        self._delete_device(device_id)

    def test_central_user_methods_CRD(self):
        users = self._create_users()

        self.cmd(
            "iot central app user show --app-id {} --user-id {}".format(
                APP_ID, users[0].get("id")
            ),
        )

        result = self.cmd(
            "iot central app user list --app-id {}".format(APP_ID,),
        ).get_output_in_json()

        user_list = result.get("value")

        for user in users:
            self._delete_user(user.get("id"))

        for user in users:
            assert user in user_list

    def test_central_device_template_methods_CRD(self):
        # currently: create, show, list, delete
        (template_id, template_name) = self._create_device_template()

        self.cmd(
            "iot central app device-template show --app-id {} --device-template-id {}".format(
                APP_ID, template_id
            ),
            checks=[
                self.check("displayName", template_name),
                self.check("id", template_id),
            ],
        )

        self._delete_device_template(template_id)

    def test_central_device_registration_info_registered(self):
        (template_id, _) = self._create_device_template()
        (device_id, device_name) = self._create_device(
            instance_of=template_id, simulated=False
        )

        result = self.cmd(
            "iot central app device registration-info --app-id {} -d {}".format(
                APP_ID, device_id
            )
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

        json_result = result.get_output_in_json()

        assert json_result["@device_id"] == device_id

        # since time taken for provisioning to complete is not known
        # we can only assert that the payload is populated, not anything specific beyond that
        assert json_result["device_registration_info"] is not None
        assert json_result["dps_state"] is not None

        # Validation - device registration.
        device_registration_info = json_result["device_registration_info"]
        assert len(device_registration_info) == 5
        assert device_registration_info.get("device_status") == "registered"
        assert device_registration_info.get("id") == device_id
        assert device_registration_info.get("display_name") == device_name
        assert device_registration_info.get("instance_of") == template_id
        assert not device_registration_info.get("simulated")

        # Validation - dps state
        dps_state = json_result["dps_state"]
        assert len(dps_state) == 2
        assert device_registration_info.get("status") is None
        assert dps_state.get("error") == "Device is not yet provisioned."

    def test_central_run_command(self):
        interface_id = "modelOne_g4"
        command_name = "sync_cmd"
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(instance_of=template_id, simulated=True)

        self._wait_for_provisioned(device_id)

        run_command_result = self.cmd(
            "iot central app device run-command"
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
            "iot central app device show-command-history"
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

    def test_central_device_registration_info_unassociated(self):

        (device_id, device_name) = self._create_device()

        result = self.cmd(
            "iot central app device registration-info --app-id {} -d {}".format(
                APP_ID, device_id
            )
        )

        self._delete_device(device_id)

        json_result = result.get_output_in_json()

        assert json_result["@device_id"] == device_id

        # since time taken for provisioning to complete is not known
        # we can only assert that the payload is populated, not anything specific beyond that
        assert json_result["device_registration_info"] is not None
        assert json_result["dps_state"] is not None

        # Validation - device registration.
        device_registration_info = json_result["device_registration_info"]
        assert len(device_registration_info) == 5
        assert device_registration_info.get("device_status") == "unassociated"
        assert device_registration_info.get("id") == device_id
        assert device_registration_info.get("display_name") == device_name
        assert device_registration_info.get("instance_of") is None
        assert not device_registration_info.get("simulated")

        # Validation - dps state
        dps_state = json_result["dps_state"]
        assert len(dps_state) == 2
        assert device_registration_info.get("status") is None
        assert (
            dps_state.get("error")
            == "Device does not have a valid template associated with it."
        )

    def test_central_device_registration_summary(self):

        result = self.cmd(
            "iot central app device registration-summary --app-id {}".format(APP_ID)
        )

        json_result = result.get_output_in_json()
        assert json_result[DeviceStatus.provisioned.value] is not None
        assert json_result[DeviceStatus.registered.value] is not None
        assert json_result[DeviceStatus.unassociated.value] is not None
        assert json_result[DeviceStatus.blocked.value] is not None
        assert len(json_result) == 4

    def _create_device(self, **kwargs) -> (str, str):
        """
        kwargs:
            instance_of: template_id (str)
            simulated: if the device is to be simulated (bool)
        """
        device_id = self.create_random_name(prefix="aztest", length=24)
        device_name = self.create_random_name(prefix="aztest", length=24)

        command = "iot central app device create --app-id {} -d {} --device-name {}".format(
            APP_ID, device_id, device_name
        )
        checks = [
            self.check("approved", True),
            self.check("displayName", device_name),
            self.check("id", device_id),
        ]

        instance_of = kwargs.get("instance_of")
        if instance_of:
            command = command + " --instance-of {}".format(instance_of)
            checks.append(self.check("instanceOf", instance_of))

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
            command = "iot central app user create --app-id {} --user-id {} -r {} --email {}".format(
                APP_ID, user_id, role.name, email,
            )

            checks = [
                self.check("id", user_id),
                self.check("email", email),
                self.check("type", "EmailUser"),
                self.check("roles[0].role", role.value),
            ]
            users.append(self.cmd(command, checks=checks).get_output_in_json())

        return users

    def _delete_user(self, user_id) -> None:
        self.cmd(
            "iot central app user delete --app-id {} --user-id {}".format(
                APP_ID, user_id
            ),
            checks=[self.check("result", "success")],
        )

    def _wait_for_provisioned(self, device_id):
        command = "iot central app device show --app-id {} -d {}".format(
            APP_ID, device_id
        )
        while True:
            result = self.cmd(command)
            device = result.get_output_in_json()

            # return when its provisioned
            if device.get("provisioned"):
                return

            # wait 10 seconds for provisioning to complete
            time.sleep(10)

    def _delete_device(self, device_id) -> None:
        self.cmd(
            "iot central app device delete --app-id {} -d {}".format(APP_ID, device_id),
            checks=[self.check("result", "success")],
        )

    def _create_device_template(self):
        template = utility.process_json_arg(
            device_template_path, argument_name="device_template_path"
        )
        template_name = template["displayName"]
        template_id = template_name + "id"

        self.cmd(
            "iot central app device-template create --app-id {} --device-template-id {} -k '{}'".format(
                APP_ID, template_id, device_template_path
            ),
            checks=[
                self.check("displayName", template_name),
                self.check("id", template_id),
            ],
        )

        return (template_id, template_name)

    def _delete_device_template(self, template_id):
        attempts = range(0, 10)
        command = "iot central app device-template delete --app-id {} --device-template-id {}".format(
            APP_ID, template_id
        )

        # retry logic to delete the template
        for _ in attempts:
            try:
                self.cmd(command, checks=[self.check("result", "success")])
                return
            except:
                time.sleep(10)

    def _get_credentials(self, device_id):
        return self.cmd(
            "iot central app device show-credentials --app-id {} -d {}".format(
                APP_ID, device_id
            )
        ).get_output_in_json()

    def _get_validate_messages_output(
        self, device_id, enqueued_time, duration=60, max_messages=1, asserts=None
    ):
        if not asserts:
            asserts = []

        output = self.command_execute_assert(
            "iot central app validate-messages --app-id {} -d {} --et {} --duration {} --mm {} -y --style json".format(
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
            "iot central app monitor-events -n {} -d {} --et {} --to 1 -y".format(
                APP_ID, device_id, enqueued_time
            ),
            asserts,
        )

        if not output:
            output = ""

        return output
