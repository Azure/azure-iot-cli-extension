# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import os
import time
import pytest

from azext_iot.tests.conftest import get_context_path

from azext_iot.central.models.enum import DeviceStatus

from azext_iot.tests import helpers
from azext_iot.tests.central.test_iot_central_int import TestIotCentral

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


class TestIotCentralDevices(TestIotCentral):
    def __init__(self, test_scenario):
        super(TestIotCentralDevices, self).__init__(test_scenario=test_scenario)

    def test_central_device_twin_show_fail(self):
        (device_id, _) = self._create_device()

        # Verify incorrect app-id throws error
        self.cmd(
            "iot central device twin show --app-id incorrect-app --device-id {}".format(
                device_id
            ),
            expect_failure=True,
        )
        # Verify incorrect device-id throws error
        self.cmd(
            "iot central device twin show --app-id {} --device-id incorrect-device".format(
                APP_ID
            ),
            expect_failure=True,
        )

        # Verify incorrect app-id throws error
        self.cmd(
            "iot central device twin show --app-id incorrect-app --device-id {}".format(
                device_id
            ),
            expect_failure=True,
        )

        # Verify incorrect device-id throws error
        self.cmd(
            "iot central device twin show --app-id {} --device-id incorrect-device".format(
                APP_ID
            ),
            expect_failure=True,
        )

        self._delete_device(device_id)

    def test_central_device_twin_show_success(self):
        (template_id, _) = self._create_device_template()
        (device_id, _) = self._create_device(template=template_id, simulated=True)

        # wait about a few seconds for simulator to kick in so that provisioning completes
        time.sleep(60)

        self.cmd(
            "iot central device twin show --app-id {} --device-id {}".format(
                APP_ID, device_id
            ),
            checks=[self.check("deviceId", device_id)],
        )

        self.cmd(
            "iot central device twin show --app-id {} --device-id {}".format(
                APP_ID, device_id
            ),
            checks=[self.check("deviceId", device_id)],
        )

        self._delete_device(device_id)
        self._delete_device_template(template_id)

    @pytest.mark.skipif(
        not APP_SCOPE_ID, reason="empty azext_iot_central_scope_id env var"
    )
    @pytest.mark.skipif(
        not APP_PRIMARY_KEY, reason="empty azext_iot_central_primarykey env var"
    )
    def test_device_connect(self):
        device_id = "testDevice"

        device_primary_key = self.cmd(
            "iot central device compute-device-key --pk {} -d {}".format(
                APP_PRIMARY_KEY, device_id
            ),
        ).get_output_in_json()

        credentials = {
            "idScope": APP_SCOPE_ID,
            "symmetricKey": {"primaryKey": device_primary_key},
        }
        device_client = helpers.dps_connect_device(device_id, credentials)

        self.cmd(
            "iot central device show --app-id {} -d {}".format(APP_ID, device_id),
            checks=[self.check("id", device_id)],
        )

        self._delete_device(device_id)

        assert device_client.connected

    def test_central_device_methods_CRD(self):

        (device_id, device_name) = self._create_device()

        self.cmd(
            "iot central device show --app-id {} -d {}".format(APP_ID, device_id),
            checks=[
                self.check("enabled", True),
                self.check("displayName", device_name),
                self.check("id", device_id),
                self.check("simulated", False),
            ],
        )

        self._delete_device(device_id)

    def test_central_device_template_methods_CRD(self):
        # currently: create, show, list, delete
        (template_id, template_name) = self._create_device_template()

        result = self.cmd(
            "iot central device-template show --app-id {} --device-template-id {}".format(
                APP_ID, template_id
            ),
            checks=[self.check("displayName", template_name)],
        )

        json_result = result.get_output_in_json()

        assert json_result["@id"] == template_id

        self._delete_device_template(template_id)

    def test_central_device_groups_list(self):
        result = self._list_device_groups()
        # assert object is empty or populated but not null
        assert result is not None and (result == {} or bool(result) is True)

    def test_central_device_registration_info_registered(self):
        (template_id, _) = self._create_device_template()
        (device_id, device_name) = self._create_device(
            template=template_id, simulated=False
        )

        result = self.cmd(
            "iot central device registration-info --app-id {} -d {}".format(
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
        assert device_registration_info.get("template") == template_id
        assert not device_registration_info.get("simulated")

        # Validation - dps state
        dps_state = json_result["dps_state"]
        assert len(dps_state) == 2
        assert device_registration_info.get("status") is None
        assert dps_state.get("error") == "Device is not yet provisioned."

    def test_central_device_registration_info_unassociated(self):

        (device_id, device_name) = self._create_device()

        result = self.cmd(
            "iot central device registration-info --app-id {} -d {}".format(
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
        not DEVICE_ID, reason="empty azext_iot_central_primarykey env var"
    )
    def test_central_device_registration_summary(self):

        result = self.cmd(
            "iot central diagnostics registration-summary --app-id {}".format(APP_ID)
        )

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

        command = "iot central device show-credentials --device-id {} --app-id {}".format(
            device_id, APP_ID
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

        command = "iot central device manual-failback --app-id {} --device-id {}".format(
            APP_ID, device_id
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
        result = self.cmd(
            "iot central device manual-failover"
            " --app-id {}"
            " --device-id {}"
            " --ttl {}".format(APP_ID, device_id, 5)
        )
        command = self._appendOptionalArgsToCommand(command, TOKEN, DNS_SUFFIX)

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

    def _list_device_groups(self):
        return self.cmd(
            "iot central device-group list --app-id {}".format(
                APP_ID)
        ).get_output_in_json()

    def _connect_gettwin_disconnect_wait_tobeprovisioned(self, device_id, credentials):
        device_client = helpers.dps_connect_device(device_id, credentials)
        device_client.get_twin()
        device_client.disconnect()
        device_client.shutdown()
        self._wait_for_provisioned(device_id)
