# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import time
from typing import Tuple
from knack.util import CLIError
from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.conftest import get_context_path
from azext_iot.common import utility
from azext_iot.central.models.enum import Role, UserTypePreview, UserTypeV1, ApiVersion

APP_ID = os.environ.get("azext_iot_central_app_id")
APP_PRIMARY_KEY = os.environ.get("azext_iot_central_primarykey")
APP_SCOPE_ID = os.environ.get("azext_iot_central_scope_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
TOKEN = os.environ.get("azext_iot_central_token")
DNS_SUFFIX = os.environ.get("azext_iot_central_dns_suffix")
STORAGE_CSTRING = os.environ.get("azext_iot_central_storage_cstring")
STORAGE_CONTAINER = os.environ.get("azext_iot_central_storage_container")
device_template_path = get_context_path(__file__, "json/device_template_int_test.json")
device_template_path_preview = get_context_path(
    __file__, "json/device_template_int_test_preview.json"
)
sync_command_params = get_context_path(__file__, "json/sync_command_args.json")
DEFAULT_FILE_UPLOAD_TTL = "PT1H"


class CentralLiveScenarioTest(CaptureOutputLiveScenarioTest):
    def __init__(self, test_scenario):
        super(CentralLiveScenarioTest, self).__init__(test_scenario)

    def cmd(self, command, api_version=None, checks=None, expect_failure=False):
        command = self._appendOptionalArgsToCommand(
            command, token=TOKEN, dns_suffix=DNS_SUFFIX, api_version=api_version
        )
        return super().cmd(command, checks=checks, expect_failure=expect_failure)
    
    def cmd_withoutToken(self, command, api_version=None, checks=None, expect_failure=False):
        command = self._appendOptionalArgsToCommand(
            command, api_version=api_version
        )
        return super().cmd(command, checks=checks, expect_failure=expect_failure)

    def _create_device(self, api_version, **kwargs) -> Tuple[str, str]:
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

        checks = [
            self.check("displayName", device_name),
            self.check("id", device_id),
        ]

        if api_version == ApiVersion.preview.value:
            checks.append(self.check("approved", True))
        else:
            checks.append(self.check("enabled", True))

        template = kwargs.get("template")
        if template:
            command = command + " --template {}".format(template)
            checks.append(
                self.check(
                    "instanceOf"
                    if api_version == ApiVersion.preview.value
                    else "template",
                    template,
                )
            )

        simulated = bool(kwargs.get("simulated"))
        if simulated:
            command = command + " --simulated"

        checks.append(self.check("simulated", simulated))

        self.cmd(command, api_version=api_version, checks=checks)
        return (device_id, device_name)

    def _create_users(self, api_version):

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

            checks = [
                self.check("id", user_id),
                self.check("email", email),
                self.check(
                    "type",
                    UserTypePreview.email.value
                    if api_version == ApiVersion.preview.value
                    else UserTypeV1.email.value,
                ),
                self.check("roles[0].role", role.value),
            ]
            users.append(
                self.cmd(
                    command, api_version=api_version, checks=checks
                ).get_output_in_json()
            )

        return users

    def _delete_user(self, api_version, user_id) -> None:
        self.cmd(
            "iot central user delete --app-id {} --user-id {}".format(APP_ID, user_id),
            api_version=api_version,
            checks=[self.check("result", "success")],
        )

    def _create_api_tokens(self, api_version):

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

            checks = [
                self.check("id", token_id),
                self.check("roles[0].role", role.value),
            ]

            tokens.append(
                self.cmd(
                    command, api_version=api_version, checks=checks
                ).get_output_in_json()
            )
        return tokens

    def _delete_api_token(self, api_version, token_id) -> None:
        self.cmd(
            "iot central api-token delete --app-id {} --token-id {}".format(
                APP_ID, token_id
            ),
            api_version=api_version,
            checks=[self.check("result", "success")],
        )

    def _wait_for_provisioned(self, api_version, device_id):
        command = "iot central device show --app-id {} -d {}".format(APP_ID, device_id)

        while True:
            result = self.cmd(command, api_version=api_version)
            device = result.get_output_in_json()

            # return when its provisioned
            if device.get("provisioned"):
                return

            # wait 10 seconds for provisioning to complete
            time.sleep(10)

    def _delete_device(self, api_version, device_id) -> None:

        command = "iot central device delete --app-id {} -d {} ".format(
            APP_ID, device_id
        )

        self.cmd(
            command, api_version=api_version, checks=[self.check("result", "success")]
        )

    def _create_device_template(self, api_version):
        if api_version == ApiVersion.preview.value:
            template = utility.process_json_arg(
                device_template_path_preview,
                argument_name="device_template_path_preview",
            )
        else:
            template = utility.process_json_arg(
                device_template_path, argument_name="device_template_path"
            )
        template_name = template["displayName"]
        template_id = template_name + "id"

        command = "iot central device-template create --app-id {} --device-template-id {} -k '{}'".format(
            APP_ID,
            template_id,
            device_template_path_preview
            if api_version == ApiVersion.preview.value
            else device_template_path,
        )

        result = self.cmd(
            command,
            api_version=api_version,
            checks=[
                self.check("displayName", template_name),
            ],
        )
        json_result = result.get_output_in_json()

        if api_version == ApiVersion.preview.value:
            assert json_result["id"] == template_id
        else:
            assert json_result["@id"] == template_id
        return (template_id, template_name)

    def _delete_device_template(self, api_version, template_id):
        attempts = range(0, 10)
        command = "iot central device-template delete --app-id {} --device-template-id {}".format(
            APP_ID, template_id
        )

        # retry logic to delete the template
        error = None
        for _ in attempts:
            try:
                error = None
                self.cmd(
                    command,
                    api_version=api_version,
                    checks=[self.check("result", "success")],
                )
                return
            except Exception as e:
                error = e
                # delete associated devices if any.
                command = "iot central device list --app-id {}".format(APP_ID)
                devices = self.cmd(
                    command, api_version=api_version
                ).get_output_in_json()

                if devices:
                    for device in devices:
                        device_template = device[
                            "instanceOf"
                            if api_version == ApiVersion.preview.value
                            else "template"
                        ]
                        if device_template == template_id:
                            self.cmd(
                                "iot central device delete --app-id {} --device-id {}".format(
                                    APP_ID, device["id"]
                                ),
                                api_version=api_version,
                            )
                time.sleep(10)

        raise CLIError(
            f"Device template {template_id} cannot be deleted."
            + (f" Error: {error}" if error is not None else "")
        )

    def _list_device_groups(self, api_version):
        command = "iot central device-group list --app-id {}".format(APP_ID)
        return self.cmd(command, api_version=api_version).get_output_in_json()

    def _list_roles(self, api_version):
        return self.cmd(
            "iot central role list --app-id {}".format(APP_ID), api_version=api_version
        ).get_output_in_json()

    def _get_credentials(self, api_version, device_id):
        return self.cmd(
            "iot central device show-credentials --app-id {} -d {}".format(
                APP_ID, device_id
            ),
            api_version=api_version,
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

    def _get_monitor_events_output(
        self, api_version, device_id, enqueued_time, asserts=None
    ):
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

    def _create_fileupload(self, api_version, account_name=None, sasttl=None):
        command = (
            'iot central file-upload-config create --app-id {} -s "{}" -c "{}"'.format(
                APP_ID, STORAGE_CSTRING, STORAGE_CONTAINER
            )
        )

        if account_name is not None:
            command += " --account {}".format(account_name)
        if sasttl is not None:
            command += " --sas-ttl {}".format(sasttl)

        return self.cmd(
            command,
            api_version=api_version,
            checks=[
                self.check("connectionString", STORAGE_CSTRING),
                self.check("container", STORAGE_CONTAINER),
                self.check("account", None if account_name is None else account_name),
                self.check("state", "pending"),
                self.check(
                    "sasttl", DEFAULT_FILE_UPLOAD_TTL if sasttl is None else sasttl
                ),
            ],
        ).get_output_in_json()

    def _delete_fileupload(self, api_version):
        command = "iot central file-upload-config delete --app-id {}".format(APP_ID)
        self.cmd(
            command,
            api_version=api_version,
            checks=[
                self.check("result", "success"),
            ],
        )

    def _create_organization(self, api_version):
        org_id = self.create_random_name(prefix="aztest", length=24)
        command = "iot central organization create --app-id {} --org-id {}".format(
            APP_ID, org_id
        )

        return self.cmd(
            command,
            api_version=api_version,
            checks=[
                self.check("id", org_id),
            ],
        ).get_output_in_json()

    def _delete_organization(self, api_version, org_id):
        command = "iot central organization delete --app-id {} --org-id {}".format(
            APP_ID, org_id
        )
        self.cmd(
            command,
            api_version=api_version,
            checks=[
                self.check("result", "success"),
            ],
        )

    def _create_destination(self, api_version, dest_id):
        self.kwargs["authorization"] = json.dumps(
            {
                "type": "connectionString",
                "connectionString": STORAGE_CSTRING,
                "containerName": STORAGE_CONTAINER,
            }
        )
        command = "iot central export destination create --app-id {} \
            --dest-id {} --type {} --name '{}' --authorization '{}'".format(
            APP_ID,
            dest_id,
            "blobstorage@v1",
            "Blob Storage",
            "{authorization}",
        )
        return self.cmd(
            command, api_version=api_version, checks=[self.check("id", dest_id)]
        ).get_output_in_json()

    def _delete_destination(self, api_version, dest_id):
        command = (
            "iot central export destination delete --app-id {} --dest-id {}".format(
                APP_ID, dest_id
            )
        )
        self.cmd(command, api_version=api_version)

    def _create_export(self, api_version, export_id, dest_id):

        self.kwargs["enrichments"] = json.dumps({"Simulated": {"path": "$simulated"}})
        self.kwargs["destinations"] = json.dumps([{"id": dest_id}])

        command = "iot central export create --app-id {} --export-id {} --name {} \
            --filter {} --source {} --enabled {} --enrichments '{}' --destinations '{}'".format(
            APP_ID,
            export_id,
            '"Test Export"',
            '"SELECT * FROM devices WHERE $simulated = true"',
            "Telemetry",
            "True",
            "{enrichments}",
            "{destinations}",
        )
        return self.cmd(
            command, api_version=api_version, checks=[self.check("id", export_id)]
        ).get_output_in_json()

    def _delete_export(self, api_version, export_id):
        command = "iot central export delete --app-id {} --export-id {}".format(
            APP_ID, export_id
        )
        self.cmd(command, api_version=api_version)

    def _wait_for_storage_configured(self, api_version):
        command = "iot central file-upload-config show --app-id {}".format(APP_ID)

        while True:
            try:
                result = self.cmd(command, api_version=api_version)
            except CLIError as e:
                if e.args[0] and "code" in e.args[0]:
                    err = dict(e.args[0])
                    if err["code"] == "NotFound":
                        # storage has been deleted
                        return
                    raise e
            file_upload = result.get_output_in_json()

            # return when its provisioned
            if file_upload.get("state") == "succeeded":
                return file_upload

            # wait 10 seconds for provisioning to complete
            time.sleep(10)

    def _appendOptionalArgsToCommand(
        self, command: str, token: str, dns_suffix: str, api_version: str
    ):
        if token:
            command += ' --token "{}"'.format(token)
        if dns_suffix:
            command += ' --central-dns-suffix "{}"'.format(dns_suffix)
        if api_version:
            command += " --api-version {}".format(api_version)

        return command
