# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json

from time import sleep
from uuid import uuid4
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from azext_iot.common.utility import (
    calculate_millisec_since_unix_epoch_utc,
    validate_key_value_pairs
)


class TestIoTHubC2DMessages(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubC2DMessages, self).__init__(
            test_case
        )

    def test_iothub_c2d_messages(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        # Ensure role assignment is complete
        sleep(30)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            test_ce = "utf-16" if auth_phase == AuthenticationTypeDataplane.login.value else "utf-8"
            test_body = f"{uuid4()} шеллы 😁"  # Mixed unicode blocks
            test_props = f"key0={str(uuid4())};key1={str(uuid4())}"
            test_cid = str(uuid4())
            test_mid = str(uuid4())
            test_ct = "text/plain"
            test_et = calculate_millisec_since_unix_epoch_utc(3600)  # milliseconds since epoch

            self.kwargs["c2d_json_send_data"] = json.dumps({"data": str(uuid4())})

            # Send C2D message
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot device c2d-message send -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} "
                    f"--data '{test_body}' --cid {test_cid} --mid {test_mid} --ct {test_ct} --expiry {test_et} "
                    f"--ce {test_ce} -p '{test_props}' -y",
                    auth_type=auth_phase
                ),
                checks=self.is_empty(),
            )

            c2d_receive_result = self.cmd(
                f"iot device c2d-message receive -d {device_ids[0]} --hub-name {self.entity_name} -g {self.entity_rg} --complete",
            ).get_output_in_json()

            assert c2d_receive_result["data"] == test_body

            # Assert system properties
            received_system_props = c2d_receive_result["properties"]["system"]
            assert received_system_props["ContentEncoding"] == test_ce
            assert received_system_props["ContentType"] == test_ct
            assert received_system_props["iothub-correlationid"] == test_cid
            assert received_system_props["iothub-messageid"] == test_mid
            assert received_system_props["iothub-expiry"]
            assert received_system_props["iothub-to"] == f"/devices/{device_ids[0]}/messages/devicebound"

            # Ack is tested in message feedback tests
            assert received_system_props["iothub-ack"] == "none"

            # Assert app properties
            received_app_props = c2d_receive_result["properties"]["app"]
            assert received_app_props == validate_key_value_pairs(test_props)
            assert c2d_receive_result["etag"]
