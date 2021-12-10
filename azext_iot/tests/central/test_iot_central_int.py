# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import json
from azext_iot.central.models.enum import ApiVersion, Role, get_enum_values
from azure.iot.device import Message
from azext_iot.common import utility
from azext_iot.monitor.parsers import strings
from azext_iot.tests import helpers
from azext_iot.tests.central import (
    CentralLiveScenarioTest,
    APP_ID,
    STORAGE_CSTRING,
    STORAGE_CONTAINER,
    DEFAULT_FILE_UPLOAD_TTL,
    sync_command_params,
)
import pytest


if not all([APP_ID]):
    raise ValueError("Set azext_iot_central_app_id to run central integration tests.")

IS_1_1_PREVIEW = True


class TestIotCentral(CentralLiveScenarioTest):
    @pytest.fixture(autouse=True)
    def fixture_api_version(self, request):
        self._api_version = request.config.getoption("--api-version")
        IS_1_1_PREVIEW = (
            self._api_version == ApiVersion.v1_1_preview.value
            or self._api_version is None
        )  # either explicitely selected or omitted
        if IS_1_1_PREVIEW:
            print("Testing 1.1-preview")
        yield

    def __init__(self, test_scenario):
        super(TestIotCentral, self).__init__(test_scenario=test_scenario)

    def test_central_monitor_events(self):
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version
        )
        credentials = self._get_credentials(
            device_id=device_id, api_version=self._api_version
        )

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
        self.cmd(command, api_version=self._api_version, expect_failure=True)

        # Ensure no failure
        output = self._get_monitor_events_output(
            device_id=device_id,
            enqueued_time=enqueued_time,
            api_version=self._api_version,
        )

        self._delete_device(device_id=device_id, api_version=self._api_version)

        self._delete_device_template(
            template_id=template_id, api_version=self._api_version
        )

        assert '"Bool": true' in output
        assert device_id in output

    def test_central_validate_messages_success(self):
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version
        )
        credentials = self._get_credentials(
            device_id=device_id, api_version=self._api_version
        )

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

        self._delete_device(device_id=device_id, api_version=self._api_version)

        self._delete_device_template(
            template_id=template_id, api_version=self._api_version
        )

        assert output
        assert "Successfully parsed 1 message(s)" in output
        assert "No errors detected" in output

    def test_central_validate_messages_issues_detected(self):
        expected_messages = []
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version
        )
        credentials = self._get_credentials(
            device_id=device_id, api_version=self._api_version
        )

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

        self._delete_device(device_id=device_id, api_version=self._api_version)

        self._delete_device_template(
            template_id=template_id, api_version=self._api_version
        )

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

    def test_central_user_methods_CRUD(self):
        users = self._create_users(api_version=self._api_version)

        command = "iot central user show --app-id {} --user-id {}".format(
            APP_ID, users[0].get("id")
        )
        self.cmd(command, api_version=self._api_version)

        command = "iot central user list --app-id {}".format(APP_ID)
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()

        for user in users:
            assert user in result
        # UPDATE
        for user in users:
            current_role = user["roles"][0]["role"]
            new_role = [x for x in get_enum_values(Role) if x != current_role][0]
            command = "iot central user update --app-id {} --email {} --role {} --user-id {}".format(
                APP_ID, user["email"], new_role, user["id"]
            )
            checks = [self.check("roles[0].role", new_role)]
            self.cmd(command, api_version=self._api_version, checks=checks)

        # DELETE
        for user in users:
            self._delete_user(user_id=user.get("id"), api_version=self._api_version)

    def test_central_api_token_methods_CRD(self):
        tokens = self._create_api_tokens(api_version=self._api_version)
        command = "iot central api-token show --app-id {} --token-id {}".format(
            APP_ID, tokens[0].get("id")
        )
        self.cmd(command, api_version=self._api_version)

        command = "iot central api-token list --app-id {}".format(
            APP_ID,
        )
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()

        token_list = result.get("value")

        for token in tokens:
            self._delete_api_token(
                token_id=token.get("id"), api_version=self._api_version
            )

        for token in tokens:
            token_info_basic = {
                "expiry": token.get("expiry"),
                "id": token.get("id"),
                "roles": token.get("roles"),
            }
            assert token_info_basic in token_list

    def test_central_roles_list(self):
        result = self._list_roles(api_version=self._api_version)
        # assert object is empty or populated but not null
        assert result is not None and (result == {} or bool(result) is True)

    def test_central_run_command_root_level(self):
        command_name = "testRootCommand"
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version, simulated=True
        )

        self._wait_for_provisioned(device_id=device_id, api_version=self._api_version)

        command = "iot central device command run -n {} -d {} --cn {} -k '{}'".format(
            APP_ID, device_id, command_name, sync_command_params
        )

        run_command_result = self.cmd(command, api_version=self._api_version)

        command = "iot central device command history -n {} -d {} --cn {}".format(
            APP_ID, device_id, command_name
        )

        show_command_result = self.cmd(command, api_version=self._api_version)

        self._delete_device(device_id=device_id, api_version=self._api_version)

        self._delete_device_template(
            template_id=template_id, api_version=self._api_version
        )

        run_result = run_command_result.get_output_in_json()
        show_result = show_command_result.get_output_in_json()

        # from file indicated by `sync_command_params`
        assert run_result["request"] == {"argument": "value"}

        # check that run result and show result indeed match
        assert run_result["response"] == show_result["value"][0]["response"]

    def test_central_run_command_component(self):
        interface_id = "dtmiIntTestDeviceTemplateV33jl"
        command_name = "testCommand"
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version, simulated=True
        )

        self._wait_for_provisioned(device_id=device_id, api_version=self._api_version)

        command = (
            "iot central device command run -n {} -d {} -i {} --cn {} -k '{}'".format(
                APP_ID, device_id, interface_id, command_name, sync_command_params
            )
        )
        run_command_result = self.cmd(command, api_version=self._api_version)

        command = "iot central device command history -n {} -d {} -i {} --cn {}".format(
            APP_ID, device_id, interface_id, command_name
        )
        show_command_result = self.cmd(command, api_version=self._api_version)

        self._delete_device(device_id=device_id, api_version=self._api_version)

        self._delete_device_template(
            template_id=template_id,
            api_version=self._api_version,
        )

        run_result = run_command_result.get_output_in_json()
        show_result = show_command_result.get_output_in_json()

        # from file indicated by `sync_command_params`
        assert run_result["request"] == {"argument": "value"}

        # check that run result and show result indeed match
        assert run_result["response"] == show_result["value"][0]["response"]

    @pytest.mark.skipif(
        not STORAGE_CSTRING or not STORAGE_CONTAINER,
        reason="empty azext_iot_central_storage_cstring or azext_iot_central_storage_container env var",
    )
    @pytest.mark.xfail(
        condition=not IS_1_1_PREVIEW,
        reason="Api version not supported",
    )
    def test_central_fileupload_methods_CRUD_required(self):
        file_upload = self._create_fileupload(api_version=self._api_version)

        result = self._wait_for_storage_configured(api_version=self._api_version)

        assert result["state"] == "succeeded"
        assert result["connectionString"] == file_upload["connectionString"]
        assert result["container"] == file_upload["container"]
        assert result["account"] is None  # account was not passed in params
        assert (
            result["sasTtl"] == DEFAULT_FILE_UPLOAD_TTL
        )  # sasTTL not passed in params

        # UPDATE
        command = (
            "iot central file-upload-config update --app-id {} --sasTtl {}".format(
                APP_ID, "PT4H"
            )
        )
        checks = [self.check("sasTtl", "PT4H")]
        self.cmd(command, api_version=self._api_version, checks=checks)

        # DELETE
        self._delete_fileupload(api_version=self._api_version)
        # check deleting state
        command = "iot central file-upload-config show -n {}".format(APP_ID)
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()
        assert result["state"] == "deleting"
        self._wait_for_storage_configured(api_version=self._api_version)

    @pytest.mark.skipif(
        not STORAGE_CSTRING or not STORAGE_CONTAINER,
        reason="empty azext_iot_central_storage_cstring or azext_iot_central_storage_container env var",
    )
    def test_central_fileupload_methods_CRUD_optional(self):
        ACCOUNT_NAME = "account"
        SAS_TTL = "PT2H"
        file_upload = self._create_fileupload(
            api_version=self._api_version, account_name=ACCOUNT_NAME, sasttl=SAS_TTL
        )

        result = self._wait_for_storage_configured(api_version=self._api_version)
        assert result["state"] == "succeeded"
        assert result["connectionString"] == file_upload["connectionString"]
        assert result["container"] == file_upload["container"]
        assert result["account"] == ACCOUNT_NAME
        assert result["sasTtl"] == SAS_TTL

        # UPDATE
        command = (
            "iot central file-upload-config update --app-id {} --sasTtl {}".format(
                APP_ID, "PT4H"
            )
        )
        checks = [self.check("sasTtl", "PT4H")]
        self.cmd(command, api_version=self._api_version, checks=checks)

        self._delete_fileupload(api_version=self._api_version)

        # check deleting state
        command = "iot central file-upload-config show -n {}".format(APP_ID)
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()
        assert result["state"] == "deleting"
        self._wait_for_storage_configured(api_version=self._api_version)

    @pytest.mark.xfail(
        condition=not IS_1_1_PREVIEW,
        reason="Api version not supported",
    )
    def test_central_organization_methods_CRUD(self):
        org = self._create_organization(api_version=self._api_version)
        command = "iot central organization show -n {} --org-id {}".format(
            APP_ID, org["id"]
        )
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()
        assert result["id"] == org["id"]

        # UPDATE
        command = "iot central organization update --app-id {} --org-id {} --org-name {}".format(
            APP_ID, org["id"], "new_name"
        )
        checks = [self.check("displayName", "new_name")]
        self.cmd(command, api_version=self._api_version, checks=checks)
        # DELETE
        self._delete_organization(org_id=org["id"], api_version=self._api_version)

    @pytest.mark.xfail(
        condition=not IS_1_1_PREVIEW,
        reason="Api version not supported",
    )
    def test_central_destination_export_methods_CRD(self):
        dest_id = "aztestdest0001"
        export_id = "aztestexport001"
        dest = self._create_destination(api_version=self._api_version, dest_id=dest_id)
        command = "iot central export destination show -n {} --dest-id {}".format(
            APP_ID, dest["id"]
        )
        result = self.cmd(command, api_version=self._api_version).get_output_in_json()
        assert result["id"] == dest["id"]

        export = self._create_export(
            api_version=self._api_version, export_id=export_id, dest_id=dest_id
        )
        command = "iot central export show -n {} --export-id {}".format(
            APP_ID, export["id"]
        )
        export_result = self.cmd(
            command, api_version=self._api_version
        ).get_output_in_json()
        assert export_result["id"] == export["id"]

        self._delete_export(export_id=export["id"], api_version=self._api_version)
        self._delete_destination(dest_id=dest_id, api_version=self._api_version)

    @pytest.mark.xfail(
        condition=not IS_1_1_PREVIEW,
        reason="Api version not supported",
    )
    def test_central_query_methods_run(self):
        (template_id, _) = self._create_device_template(api_version=self._api_version)
        (device_id, _) = self._create_device(
            template=template_id, api_version=self._api_version, simulated=True
        )

        command = 'iot central query -n {} --query-string "{}"'.format(
            APP_ID,
            "SELECT TOP 1 testDefaultCapability FROM dtmi:intTestDeviceTemplateid WHERE WITHIN_WINDOW(PT1H)",
        )
        response = self.cmd(command, api_version=self._api_version).get_output_in_json()

        assert response["results"] is not None
        self._delete_device(api_version=self._api_version, device_id=device_id)
        self._delete_device_template(
            api_version=self._api_version, template_id=template_id
        )
