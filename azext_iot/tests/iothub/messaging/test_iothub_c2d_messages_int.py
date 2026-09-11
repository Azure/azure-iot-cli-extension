# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import pytest
import re
import yaml

from time import sleep
from uuid import uuid4
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from azext_iot.tests.iothub._integration_helpers import device_receiver, LOCAL_AUTH_DEVICE_HTTP_REASON
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
        """Entra service send, with a real device-key MQTT receiver."""
        device_id = self.generate_device_names()[0]
        self.cmd(
            f"iot hub device-identity create -d {device_id} -n {self.entity_name} "
            f"-g {self.entity_rg} --auth-type login"
        )
        with device_receiver(self.get_device_cstring(device_id)) as messages:
            for encoding in ("utf-8", "utf-16"):
                body = f"{uuid4()} шеллы 😁"
                message_id, correlation_id = str(uuid4()), str(uuid4())
                properties = {"key0": str(uuid4()), "key1": str(uuid4())}
                self.cmd(
                    f"iot device c2d-message send -d {device_id} -n {self.entity_name} -g {self.entity_rg} "
                    f"--auth-type login --data '{body}' --mid {message_id} --cid {correlation_id} "
                    f"--ct text/plain --ce {encoding} "
                    f"--props 'key0={properties['key0']};key1={properties['key1']}' -y"
                )
                received = messages.get(timeout=60)
                payload = received.data
                if isinstance(payload, bytes):
                    payload = payload.decode(encoding)
                assert payload == body
                assert received.message_id == message_id
                assert received.correlation_id == correlation_id
                assert received.content_type == "text/plain"
                assert received.content_encoding == encoding
                assert received.custom_properties == properties

    def test_iothub_c2d_feedback(self):
        """The AMQP feedback path supports Entra; device receipt/ack uses a device key."""
        device_id = self.generate_device_names()[0]
        self.cmd(
            f"iot hub device-identity create -d {device_id} -n {self.entity_name} "
            f"-g {self.entity_rg} --auth-type login"
        )
        body, message_id = str(uuid4()), str(uuid4())
        with device_receiver(self.get_device_cstring(device_id)) as messages:
            output = self.command_execute_assert(
                f"iot device c2d-message send -d {device_id} -n {self.entity_name} -g {self.entity_rg} "
                f"--auth-type login --data '{body}' --mid {message_id} --ack full --wait -y"
            )
            received = messages.get(timeout=60)
            payload = received.data.decode("utf-8") if isinstance(received.data, bytes) else received.data
            assert payload == body
            assert received.message_id == message_id

        # The monitor prints a banner followed by one or more YAML feedback
        # mappings, without YAML document separators. Match all three fields in
        # the same record, not unrelated fragments elsewhere in captured stdout.
        feedback = [
            yaml.safe_load(record)["feedback"]
            for record in re.findall(r"(?m)^feedback:\n(?:[ \t]+.*\n)*", output)
        ]
        assert any(
            record.get("deviceId") == device_id
            and record.get("statusCode") == "Success"
            and record.get("originalMessageId") == message_id
            for record in feedback
        ), f"No successful feedback for device {device_id}, message {message_id}: {feedback}"

    @pytest.mark.skip(reason=LOCAL_AUTH_DEVICE_HTTP_REASON)
    def test_iothub_c2d_messages_http(self):
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
                    f"iot device c2d-message send -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg} "
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
            assert received_system_props["content-encoding"] == test_ce
            assert received_system_props["content-type"] == test_ct
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
