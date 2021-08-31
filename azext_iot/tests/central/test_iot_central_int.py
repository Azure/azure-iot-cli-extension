# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
import os
import time
import pytest

from azext_iot.tests.conftest import get_context_path

from azure.iot.device import Message
from azext_iot.common import utility
from azext_iot.central.models.enum import DeviceStatus, Role
from azext_iot.monitor.parsers import strings

from azext_iot.tests import CaptureOutputLiveScenarioTest, helpers

APP_ID = os.environ.get("azext_iot_central_app_id")
APP_PRIMARY_KEY = os.environ.get("azext_iot_central_primarykey")
APP_SCOPE_ID = os.environ.get("azext_iot_central_scope_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
STORAGE_CSTRING = os.environ.get("azext_iot_central_storage_cstring")
STORAGE_CONTAINER = os.environ.get("azext_iot_central_storage_container")
TOKEN = os.environ.get("azext_iot_central_token")
DNS_SUFFIX = os.environ.get("azext_iot_central_dns_suffix")
device_template_path = get_context_path(__file__, "json/device_template_int_test.json")
sync_command_params = get_context_path(__file__, "json/sync_command_args.json")

if not all([APP_ID]):
    raise ValueError("Set azext_iot_central_app_id to run central integration tests.")


class TestIotCentral(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        super(TestIotCentral, self).__init__(test_scenario=test_scenario)

    def test_central_device_twin_show_fail(self):
        (device_id, _) = self._create_device()

        # Verify incorrect app-id throws error
        command = (
            "iot central device twin show --app-id incorrect-app --device-id {}".format(
                device_id
            )
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, expect_failure=True)

        # Verify incorrect device-id throws error
        command = "iot central device twin show --app-id {} --device-id incorrect-device".format(
            APP_ID
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, expect_failure=True)

        # Verify incorrect app-id throws error
        command = (
            "iot central device twin show --app-id incorrect-app --device-id {}".format(
                device_id
            )
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, expect_failure=True)
        # Verify incorrect device-id throws error
        command = "iot central device twin show --app-id {} --device-id incorrect-device".format(
            APP_ID
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, expect_failure=True)
        self._delete_device(device_id)

    def test_central_device_twin_show_success(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id, simulated=True)

        # wait about a few seconds for simulator to kick in so that provisioning completes
        time.sleep(60)

        command = "iot central device twin show --app-id {} --device-id {}".format(
            APP_ID, device_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, checks=[self.check("deviceId", device_id)])

        command = "iot central device twin show --app-id {} --device-id {}".format(
            APP_ID, device_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, checks=[self.check("deviceId", device_id)])
        self._delete_device(device_id)
        self._delete_device_template(template_id)

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
        command = "iot central diagnostics monitor-events --app-id {} -y".format(
            APP_ID + "zzz"
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command, expect_failure=True)

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

    @pytest.mark.skipif(
        not APP_SCOPE_ID, reason="empty azext_iot_central_scope_id env var"
    )
    @pytest.mark.skipif(
        not APP_PRIMARY_KEY, reason="empty azext_iot_central_primarykey env var"
    )
    def test_device_connect(self):
        device_id = "testDevice"

        command = "iot central device compute-device-key --pk {} -d {}".format(
            APP_PRIMARY_KEY, device_id
        )
        device_primary_key = self.cmd(command).get_output_in_json()

        credentials = {
            "idScope": APP_SCOPE_ID,
            "symmetricKey": {"primaryKey": device_primary_key},
        }
        device_client = helpers.dps_connect_device(device_id, credentials)

        command = "iot central device show --app-id {} -d {}".format(APP_ID, device_id)
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(
            command,
            checks=[self.check("id", device_id)],
        )

        self._delete_device(device_id)

        assert device_client.connected

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
            data=payload,
            content_encoding="utf-8",
            content_type="application/json",
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

        # list devices and get count
        start_device_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device list --app-id {}".format(APP_ID), TOKEN, DNS_SUFFIX
            )
        ).get_output_in_json()

        start_dev_count = len(start_device_list)
        (device_id, device_name) = self._create_device()

        command = "iot central device show --app-id {} -d {}".format(APP_ID, device_id)
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(
            command,
            checks=[
                self.check("enabled", True),
                self.check("displayName", device_name),
                self.check("id", device_id),
                self.check("simulated", False),
            ],
        )

        created_device_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device list --app-id {}".format(APP_ID), TOKEN, DNS_SUFFIX
            )
        ).get_output_in_json()

        created_dev_count = len(created_device_list)
        assert created_dev_count == (start_dev_count + 1)
        assert device_id in created_device_list.keys()
        self._delete_device(device_id)

        deleted_device_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device list --app-id {}".format(APP_ID), TOKEN, DNS_SUFFIX
            )
        ).get_output_in_json()

        deleted_dev_count = len(deleted_device_list)
        assert deleted_dev_count == start_dev_count
        assert device_id not in deleted_device_list.keys()

    def test_central_user_methods_CRD(self):
        users = self._create_users()

        command = "iot central user show --app-id {} --user-id {}".format(
            APP_ID, users[0].get("id")
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command)

        command = "iot central user list --app-id {}".format(APP_ID)
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command).get_output_in_json()

        user_list = result.get("value")

        for user in users:
            self._delete_user(user.get("id"))

        for user in users:
            assert user in user_list

    def test_central_api_token_methods_CRD(self):
        tokens = self._create_api_tokens()
        command = "iot central api-token show --app-id {} --token-id {}".format(
            APP_ID, tokens[0].get("id")
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(command)

        command = "iot central api-token list --app-id {}".format(
            APP_ID,
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command).get_output_in_json()

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

    def test_central_device_template_methods_CRD(self):
        # currently: create, show, list, delete

        # list device templates and get count
        start_device_template_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device-template list --app-id {}".format(APP_ID),
                TOKEN,
                DNS_SUFFIX,
            )
        ).get_output_in_json()

        start_dev_temp_count = len(start_device_template_list)
        (template_id, template_name) = self._create_device_template()

        command = "iot central device-template show --app-id {} --device-template-id {}".format(
            APP_ID, template_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(
            command,
            checks=[self.check("displayName", template_name)],
        )

        json_result = result.get_output_in_json()

        assert json_result["@id"] == template_id

        created_device_template_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device-template list --app-id {}".format(APP_ID),
                TOKEN,
                DNS_SUFFIX,
            )
        ).get_output_in_json()

        created_dev_temp_count = len(created_device_template_list)
        # assert number of device templates changed by 1 or none in case template was already present in the application
        assert (created_dev_temp_count == (start_dev_temp_count + 1)) or (
            created_dev_temp_count == start_dev_temp_count
        )
        assert template_id in created_device_template_list.keys()

        self._delete_device_template(template_id)
        deleted_device_template_list = self.cmd(
            self._appendOptionalArgsToCommand(
                "iot central device-template list --app-id {}".format(APP_ID),
                TOKEN,
                DNS_SUFFIX,
            )
        ).get_output_in_json()

        deleted_dev_temp_count = len(deleted_device_template_list)
        assert deleted_dev_temp_count == start_dev_temp_count
        assert template_id not in deleted_device_template_list.keys()

    @pytest.mark.skipif(
        not STORAGE_CSTRING or not STORAGE_CONTAINER,
        reason="empty azext_iot_central_storage_cstring or azext_iot_central_storage_container env var",
    )
    def test_central_fileupload_methods_CRD(self):
        file_upload = self._create_fileupload()
        self._wait_for_storage_configured()
        command = self._appendOptionalArgsToCommand(
            "iot central file-upload show -n {}".format(APP_ID), TOKEN, DNS_SUFFIX
        )
        result = self.cmd(command).get_output_in_json()
        assert result["connectionString"] == file_upload["connectionString"]
        assert result["container"] == file_upload["container"]
        self._delete_fileupload()

    def test_central_device_groups_list(self):
        result = self._list_device_groups()
        # assert object is empty or populated but not null
        assert result is not None and (result == {} or bool(result) is True)

    def test_central_roles_list(self):
        result = self._list_roles()
        # assert object is empty or populated but not null
        assert result is not None and (result == {} or bool(result) is True)

    def test_central_device_registration_info_registered(self):
        (template_id, _) = self._create_device_template()
        (device_id, device_name) = self._create_device(
            template=template_id, simulated=False
        )

        command = "iot central device registration-info --app-id {} -d {}".format(
            APP_ID, device_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command)

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
        assert device_registration_info.get("template") == template_id
        assert not device_registration_info.get("simulated")

        # Validation - dps state
        dps_state = json_result["dps_state"]
        assert len(dps_state) == 2
        assert device_registration_info.get("status") is None
        assert dps_state.get("error") == "Device is not yet provisioned."

    def test_central_run_command_root_level(self):
        command_name = "testRootCommand"
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id, simulated=True)

        self._wait_for_provisioned(device_id)

        command = "iot central device command run -n {} -d {} --cn {} -k '{}'".format(
            APP_ID, device_id, command_name, sync_command_params
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        run_command_result = self.cmd(command)

        command = "iot central device command history -n {} -d {} --cn {}".format(
            APP_ID, device_id, command_name
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        show_command_result = self.cmd(command)

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

        command = (
            "iot central device command run -n {} -d {} -i {} --cn {} -k '{}'".format(
                APP_ID, device_id, interface_id, command_name, sync_command_params
            )
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        run_command_result = self.cmd(command)

        command = "iot central device command history -n {} -d {} -i {} --cn {}".format(
            APP_ID, device_id, interface_id, command_name
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        show_command_result = self.cmd(command)

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

        command = "iot central device registration-info --app-id {} -d {}".format(
            APP_ID, device_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command)

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
        assert device_registration_info.get("template") is None
        assert not device_registration_info.get("simulated")

        # Validation - dps state
        dps_state = json_result["dps_state"]
        assert len(dps_state) == 2
        assert device_registration_info.get("status") is None
        assert (
            dps_state.get("error")
            == "Device does not have a valid template associated with it."
        )

    @pytest.mark.skipif(
        not DEVICE_ID, reason="empty azext_iot_central_device_id env var"
    )
    def test_central_device_registration_summary(self):

        command = "iot central diagnostics registration-summary --app-id {}".format(
            APP_ID
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command)

        json_result = result.get_output_in_json()
        assert json_result[DeviceStatus.provisioned.value] is not None
        assert json_result[DeviceStatus.registered.value] is not None
        assert json_result[DeviceStatus.unassociated.value] is not None
        assert json_result[DeviceStatus.blocked.value] is not None
        assert len(json_result) == 4

    def test_central_device_should_start_failover_and_failback(self):

        # created device template & device
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(instance_of=template_id, simulated=False)

        command = (
            "iot central device show-credentials --device-id {} --app-id {}".format(
                device_id, APP_ID
            )
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        credentials = self.cmd(command).get_output_in_json()

        # connect & disconnect device & wait to be provisioned
        self._connect_gettwin_disconnect_wait_tobeprovisioned(device_id, credentials)
        command = "iot central device manual-failover --app-id {} --device-id {} --ttl {}".format(
            APP_ID, device_id, 5
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        # initiating failover
        result = self.cmd(command)
        json_result = result.get_output_in_json()

        # check if failover started and getting original hub identifier
        hubIdentifierOriginal = json_result["hubIdentifier"]

        # connect & disconnect device & wait to be provisioned
        self._connect_gettwin_disconnect_wait_tobeprovisioned(device_id, credentials)

        command = (
            "iot central device manual-failback --app-id {} --device-id {}".format(
                APP_ID, device_id
            )
        )

        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        # Initiating failback
        fb_result = self.cmd(command)

        # checking if failover has been done by comparing original hub identifier with hub identifier after failover is done
        fb_json_result = fb_result.get_output_in_json()
        hubIdentifierFailOver = fb_json_result["hubIdentifier"]
        # connect & disconnect device & wait to be provisioned
        self._connect_gettwin_disconnect_wait_tobeprovisioned(device_id, credentials)

        # initiating failover again to see if hub identifier after failbackreturned to original state
        command = "iot central device manual-failover --app-id {} --device-id {} --ttl {}".format(
            APP_ID, device_id, 5
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        result = self.cmd(command)

        json_result = result.get_output_in_json()
        hubIdentifierFinal = json_result["hubIdentifier"]

        # Cleanup
        self._delete_device(device_id)
        self._delete_device_template(template_id)

        assert len(hubIdentifierOriginal) > 0
        assert len(hubIdentifierFailOver) > 0
        assert hubIdentifierOriginal != hubIdentifierFailOver
        assert len(hubIdentifierFinal) > 0
        assert hubIdentifierOriginal == hubIdentifierFinal

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

    def _create_users(
        self,
    ):

        users = []
        for role in Role:
            user_id = self.create_random_name(prefix="aztest", length=24)
            email = user_id + "@microsoft.com"
            command = "iot central user create --app-id {} --user-id {} -r {} --email {}".format(
                APP_ID,
                user_id,
                role.name,
                email,
            )
            command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
            checks = [
                self.check("id", user_id),
                self.check("email", email),
                self.check("type", "email"),
                self.check("roles[0].role", role.value),
            ]
            users.append(self.cmd(command, checks=checks).get_output_in_json())

        return users

    def _delete_user(self, user_id) -> None:
        command = "iot central user delete --app-id {} --user-id {}".format(
            APP_ID, user_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(
            command,
            checks=[self.check("result", "success")],
        )

    def _create_api_tokens(
        self,
    ):

        tokens = []
        for role in Role:
            token_id = self.create_random_name(prefix="aztest", length=24)
            command = (
                "iot central api-token create --app-id {} --token-id {} -r {}".format(
                    APP_ID,
                    token_id,
                    role.name,
                )
            )
            command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

            checks = [
                self.check("id", token_id),
                self.check("roles[0].role", role.value),
            ]

            tokens.append(self.cmd(command, checks=checks).get_output_in_json())
        return tokens

    def _delete_api_token(self, token_id) -> None:
        command = "iot central api-token delete --app-id {} --token-id {}".format(
            APP_ID, token_id
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)
        self.cmd(
            command,
            checks=[self.check("result", "success")],
        )

    def _create_fileupload(self):
        command = self._appendOptionalArgsToCommand(
            'iot central file-upload create --app-id {} -s "{}" -c "{}"'.format(
                APP_ID, STORAGE_CSTRING, STORAGE_CONTAINER
            ),
            TOKEN,
            DNS_SUFFIX,
        )
        print("Command: {}".format(command))
        return self.cmd(
            command,
            checks=[
                self.check("connectionString", STORAGE_CSTRING),
                self.check("container", STORAGE_CONTAINER),
            ],
        ).get_output_in_json()

    def _delete_fileupload(self):
        command = self._appendOptionalArgsToCommand(
            "iot central file-upload delete --app-id {}".format(APP_ID),
            TOKEN,
            DNS_SUFFIX,
        )
        self.cmd(
            command,
            checks=[
                self.check("result", "success"),
            ],
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

    def _wait_for_storage_configured(self):
        command = "iot central file-upload show --app-id {}".format(APP_ID)
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

        while True:
            result = self.cmd(command)
            file_upload = result.get_output_in_json()

            # return when its provisioned
            if file_upload.get("state") == "succeeded":
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

        result = self.cmd(
            command,
            checks=[
                self.check("displayName", template_name),
            ],
        )
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

    def _list_device_groups(self):
        command = self._appendOptionalArgsToCommand(
            "iot central device-group list --app-id {}".format(APP_ID),
            TOKEN,
            DNS_SUFFIX,
        )
        return self.cmd(command).get_output_in_json()

    def _list_roles(self):
        command = self._appendOptionalArgsToCommand(
            "iot central role list --app-id {}".format(APP_ID), TOKEN, DNS_SUFFIX
        )
        return self.cmd(command).get_output_in_json()

    def _get_credentials(self, device_id):
        command = self._appendOptionalArgsToCommand(
            "iot central device show-credentials --app-id {} -d {}".format(
                APP_ID, device_id
            ),
            TOKEN,
            DNS_SUFFIX,
        )
        return self.cmd(command).get_output_in_json()

    def _get_validate_messages_output(
        self, device_id, enqueued_time, duration=60, max_messages=1, asserts=None
    ):
        if not asserts:
            asserts = []

        command = self._appendOptionalArgsToCommand(
            "iot central diagnostics validate-messages --app-id {} -d {} --et {} --duration {} --mm {} -y --style json".format(
                APP_ID, device_id, enqueued_time, duration, max_messages
            ),
            TOKEN,
            DNS_SUFFIX,
        )
        output = self.command_execute_assert(
            command,
            asserts,
        )

        if not output:
            output = ""

        return output

    def _get_monitor_events_output(self, device_id, enqueued_time, asserts=None):
        if not asserts:
            asserts = []

        output = self.command_execute_assert(
            self._appendOptionalArgsToCommand(
                "iot central diagnostics monitor-events -n {} -d {} --et {} --to 1 -y".format(
                    APP_ID, device_id, enqueued_time
                ),
                TOKEN,
                DNS_SUFFIX,
            ),
            asserts,
        )

        if not output:
            output = ""

        return output

    def _connect_gettwin_disconnect_wait_tobeprovisioned(self, device_id, credentials):
        device_client = helpers.dps_connect_device(device_id, credentials)
        device_client.get_twin()
        device_client.disconnect()
        device_client.shutdown()
        self._wait_for_provisioned(device_id)

    def _appendOptionalArgsToCommand(self, command: str, token: str, dnsSuffix: str):
        if token:
            command = command + ' --token "{}"'.format(token)
        if dnsSuffix:
            command = command + ' --central-dns-suffix "{}"'.format(dnsSuffix)

        return command
