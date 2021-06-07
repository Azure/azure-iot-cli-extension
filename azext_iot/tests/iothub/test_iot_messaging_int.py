# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json

from time import time
from uuid import uuid4
from azext_iot.tests import IoTLiveScenarioTest, PREFIX_DEVICE
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.common.utility import (
    execute_onthread,
    calculate_millisec_since_unix_epoch_utc,
    validate_key_value_pairs
)

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg

LIVE_CONSUMER_GROUPS = ["test1", "test2", "test3"]
MQTT_CLIENT_SETUP_TIME = 11


class TestIoTHubMessaging(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubMessaging, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_uamqp_device_messaging(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
        )

        test_body = str(uuid4())
        test_props = "key0={};key1={}".format(str(uuid4()), str(uuid4()))
        test_cid = str(uuid4())
        test_mid = str(uuid4())
        test_ct = "text/plain"
        test_et = int((time() + 3600) * 1000)  # milliseconds since epoch
        test_ce = "utf8"
        test_mn = "Test_Method_1"
        test_mp = {'payload_data1': 'payload_value1'}

        self.kwargs["c2d_json_send_data"] = json.dumps({"data": str(uuid4())})
        self.kwargs["method_payload_test_data"] = json.dumps(test_mp)

        # Send C2D message
        self.cmd(
            """iot device c2d-message send -d {} -n {} -g {} --data '{}' --cid {} --mid {} --ct {} --expiry {}
            --ce {} --props {}""".format(
                device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                test_body,
                test_cid,
                test_mid,
                test_ct,
                test_et,
                test_ce,
                test_props,
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --hub-name {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            )
        ).get_output_in_json()

        assert result["data"] == test_body

        system_props = result["properties"]["system"]
        assert system_props["ContentEncoding"] == test_ce
        assert system_props["ContentType"] == test_ct
        assert system_props["iothub-correlationid"] == test_cid
        assert system_props["iothub-messageid"] == test_mid
        assert system_props["iothub-expiry"]
        assert system_props["iothub-to"] == "/devices/{}/messages/devicebound".format(
            device_ids[0]
        )

        # Ack is tested in message feedback tests
        assert system_props["iothub-ack"] == "none"

        app_props = result["properties"]["app"]
        assert app_props == validate_key_value_pairs(test_props)

        # Implicit etag assertion
        etag = result["etag"]

        self.cmd(
            "iot device c2d-message complete -d {} --hub-name {} -g {} --etag {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, etag
            ),
            checks=self.is_empty(),
        )

        utf_32_encoding = "utf-32"
        string_payload = "Test payload encoding decoding"

        # Send C2D Message with UTF-32 encoding
        self.cmd(
            """iot device c2d-message send -d {} -n {} -g {} --data '{}' --cid {} --mid {} --ct {} --expiry {}
            --ce {} --props {}""".format(
                device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                string_payload,
                test_cid,
                test_mid,
                test_ct,
                test_et,
                utf_32_encoding,
                test_props,
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --hub-name {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            )
        ).get_output_in_json()

        # Verify that the data was decoded correctly
        assert result["data"] == string_payload

        # Send C2D message via --login + application/json content ype

        test_ct = "application/json"
        test_mid = str(uuid4())

        self.cmd(
            """iot device c2d-message send -d {} --login {} --data '{}' --cid {} --mid {} --ct {} --expiry {}
            --ce {} --ack positive --props {}""".format(
                device_ids[0],
                self.connection_string,
                "{c2d_json_send_data}",
                test_cid,
                test_mid,
                test_ct,
                test_et,
                test_ce,
                test_props,
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()

        assert result["data"] == self.kwargs["c2d_json_send_data"]

        system_props = result["properties"]["system"]
        assert system_props["ContentEncoding"] == test_ce
        assert system_props["ContentType"] == test_ct
        assert system_props["iothub-correlationid"] == test_cid
        assert system_props["iothub-messageid"] == test_mid
        assert system_props["iothub-expiry"]
        assert system_props["iothub-to"] == "/devices/{}/messages/devicebound".format(
            device_ids[0]
        )

        assert system_props["iothub-ack"] == "positive"

        app_props = result["properties"]["app"]
        assert app_props == validate_key_value_pairs(test_props)

        etag = result["etag"]

        self.cmd(
            "iot device c2d-message reject -d {} --etag {} --login {}".format(
                device_ids[0], etag, self.connection_string
            ),
            checks=self.is_empty(),
        )

        # Test waiting for ack from c2d send
        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)

        token, thread = execute_onthread(
            method=iot_simulate_device,
            args=[
                client,
                device_ids[0],
                LIVE_HUB,
                "complete",
                "Testing mqtt c2d and direct method invocations",
                2,
                5,
                "mqtt",
            ],
            max_runs=4,
            return_handle=True,
        )

        self.cmd(
            "iot device c2d-message send -d {} --ack {} --login {} --wait -y".format(
                device_ids[0], "full", self.connection_string
            )
        )
        token.set()
        thread.join()

        # invoke device method without response status and payload
        res = self.cmd(
            """iot hub invoke-device-method -d {} --method-name {} --login {} --method-payload '{}'""".format(
                device_ids[0], test_mn, self.connection_string, "{method_payload_test_data}")).get_output_in_json()

        assert res is not None
        assert res["status"] == 200
        assert res["payload"] == {
            "methodName": test_mn,
            "methodRequestId": "1",
            "methodRequestPayload": test_mp
        }

        token.set()
        thread.join()

        token, thread = execute_onthread(
            method=iot_simulate_device,
            args=[
                client,
                device_ids[0],
                LIVE_HUB,
                "complete",
                "Ping from c2d ack wait test",
                2,
                5,
                "http",
            ],
            max_runs=4,
            return_handle=True,
        )

        self.cmd(
            "iot device c2d-message send -d {} --ack {} --login {} --wait -y".format(
                device_ids[0], "full", self.connection_string
            )
        )
        token.set()
        thread.join()

        # Error - invalid wait when no ack requested
        self.cmd(
            "iot device c2d-message send -d {} --login {} --wait -y".format(
                device_ids[0], self.connection_string
            ),
            expect_failure=True,
        )

        # Error - content-type is application/json but data is not.
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ct application/json --data notjson".format(
                device_ids[0], self.connection_string
            ),
            expect_failure=True,
        )

        # Error - expiry is in the past.
        self.cmd(
            "iot device c2d-message send -d {} --login {} --expiry {}".format(
                device_ids[0], self.connection_string, int(time() * 1000)
            ),
            expect_failure=True,
        )

    def test_mqtt_device_direct_method_with_custom_response_status_payload(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli
        from time import sleep

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)

        token, thread = execute_onthread(
            method=iot_simulate_device,
            args=[
                client,
                device_ids[0],
                LIVE_HUB,
                "complete",
                "Testing direct method invocations when simulator is run with custom method response status and payload",
                4,
                5,
                "mqtt",
                None,
                None,
                None,
                204,
                "{'result': 'Direct method executed successfully'}"
            ],
            max_runs=4,
            return_handle=True,
        )

        sleep(MQTT_CLIENT_SETUP_TIME)

        # invoke device method with response status and payload
        result = self.cmd(
            "iot hub invoke-device-method -d {} --method-name Test_Method_2 --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()

        assert result is not None
        assert result["status"] == 204
        assert result["payload"] == {
            "result": "Direct method executed successfully"
        }

        token.set()
        thread.join()

    def test_twin_properties_update(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        test_twin_props = {'twin_test_prop_1': 'twin_test_value_1'}
        self.kwargs["twin_desired_properties"] = json.dumps(test_twin_props)

        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli
        from time import sleep

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)

        token, thread = execute_onthread(
            method=iot_simulate_device,
            args=[
                client,
                device_ids[0],
                LIVE_HUB,
                "complete",
                "Testing device twin reported properties update",
                4,
                5,
                "mqtt",
            ],
            max_runs=4,
            return_handle=True,
        )

        sleep(MQTT_CLIENT_SETUP_TIME)

        # invoke device twin property update
        self.cmd(
            """iot hub device-twin update -d {} --login {} --desired '{}'""".format(
                device_ids[0], self.connection_string, "{twin_desired_properties}"
            )
        )

        # get device twin
        result = self.cmd(
            "iot hub device-twin show -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()

        assert result is not None
        for key in test_twin_props:
            assert result["properties"]["reported"][key] == result["properties"]["desired"][key]

        token.set()
        thread.join()

    def test_device_messaging(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        self.cmd(
            "iot device c2d-message receive -d {} --hub-name {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], self.connection_string
            ),
            checks=self.is_empty(),
        )

        etag = "00000000-0000-0000-0000-000000000000"
        self.cmd(
            "iot device c2d-message complete -d {} --hub-name {} -g {} -e {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, etag
            ),
            expect_failure=True,
        )

        # With connection string
        self.cmd(
            "iot device c2d-message complete -d {} --login {} -e {}".format(
                device_ids[0], self.connection_string, etag
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot device c2d-message reject -d {} --hub-name {} -g {} -e {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, etag
            ),
            expect_failure=True,
        )

        # With connection string
        self.cmd(
            "iot device c2d-message reject -d {} --login {} -e {}".format(
                device_ids[0], self.connection_string, etag
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot device c2d-message abandon -d {} --hub-name {} -g {} --etag {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, etag
            ),
            expect_failure=True,
        )

        # With connection string
        self.cmd(
            "iot device c2d-message abandon -d {} --login {} --etag {}".format(
                device_ids[0], self.connection_string, etag
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot device simulate -d {} -n {} -g {} --mc {} --mi {} --data '{}' --rs 'complete'".format(
                device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, "IoT Ext Test"
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            "iot device simulate -d {} --login {} --mc {} --mi {} --data '{}' --rs 'complete'".format(
                device_ids[0], self.connection_string, 2, 1, "IoT Ext Test"
            ),
            checks=self.is_empty(),
        )

        self.cmd(
            "iot device simulate -d {} -n {} -g {} --mc {} --mi {} --data '{}' --rs 'abandon' --protocol http".format(
                device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, "IoT Ext Test"
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            "iot device simulate -d {} --login {} --mc {} --mi {} --data '{}' --rs 'abandon' --protocol http".format(
                device_ids[0], self.connection_string, 2, 1, "IoT Ext Test"
            ),
            checks=self.is_empty(),
        )

        self.cmd(
            "iot device simulate -d {} -n {} -g {} --data '{}' --rs 'reject'".format(
                device_ids[0], LIVE_HUB, LIVE_RG, "IoT Ext Test"
            ),
            checks=self.is_empty(),
            expect_failure=True,
        )

        # Send arbitrary properties with device simulation - mqtt
        self.cmd(
            "iot device simulate -d {} -n {} -g {} --mc {} --mi {} --properties '{}'".format(
                device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                2,
                1,
                "myprop=myvalue;$.ct=application/json",
            ),
            checks=self.is_empty(),
        )

        # Send arbitrary properties with device simulation - http
        self.cmd(
            "iot device simulate -d {} -n {} -g {} --mc {} --mi {} --proto http -p '{}'".format(
                device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                2,
                1,
                "iothub-app-myprop=myvalue;iothub-messageid=1",
            ),
            checks=self.is_empty(),
        )

        self.cmd(
            "iot device send-d2c-message -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        self.cmd(
            'iot device send-d2c-message -d {} -n {} -g {} --props "MessageId=12345;CorrelationId=54321"'.format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            'iot device send-d2c-message -d {} --login {} --props "MessageId=12345;CorrelationId=54321"'.format(
                device_ids[0], self.connection_string
            ),
            checks=self.is_empty(),
        )

    def test_hub_monitor_events(self):
        for cg in LIVE_CONSUMER_GROUPS:
            self.cmd(
                "az iot hub consumer-group create --hub-name {} --resource-group {} --name {}".format(
                    LIVE_HUB, LIVE_RG, cg
                ),
                checks=[self.check("name", cg)],
            )

        from azext_iot.operations.hub import iot_device_send_message
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)

        device_count = 10
        device_ids = self.generate_device_names(device_count)
        send_message_data = '{\r\n"payload_data1":"payload_value1"\r\n}'

        # Test with invalid connection string
        self.cmd(
            "iot hub monitor-events -t 1 -y --login {}".format(self.connection_string + "zzz"),
            expect_failure=True,
        )

        # Create and Simulate Devices
        for i in range(device_count):
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {}".format(
                    device_ids[i], LIVE_HUB, LIVE_RG
                ),
                checks=[self.check("deviceId", device_ids[i])],
            )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        for i in range(device_count):
            execute_onthread(
                method=iot_device_send_message,
                args=[
                    client,
                    device_ids[i],
                    LIVE_HUB,
                    send_message_data,
                    "$.mid=12345;key0=value0;key1=1",
                    1,
                    LIVE_RG,
                    None
                ],
                max_runs=1,
                return_handle=True,
            )

        # Monitor events for all devices and include sys, anno, app
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 -y -p sys anno app".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            device_ids
            + [
                "system",
                "annotations",
                "application",
                '"message_id": "12345"',
                '"key0": "value0"',
                '"key1": "1"',
            ],
        )

        # Monitor events for a single device
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} -d {} --cg {} --et {} -t 8 -y -p all".format(
                LIVE_HUB, LIVE_RG, device_ids[0], LIVE_CONSUMER_GROUPS[1], enqueued_time
            ),
            [
                device_ids[0],
                "system",
                "annotations",
                "application",
                '"message_id": "12345"',
                '"key0": "value0"',
                '"key1": "1"',
            ],
        )

        # Monitor events with device-id wildcards
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} -d {} --et {} -t 8 -y -p sys anno app".format(
                LIVE_HUB, LIVE_RG, PREFIX_DEVICE + "*", enqueued_time
            ),
            device_ids,
        )

        # Monitor events for specific devices using query language
        device_subset_include = device_ids[: device_count // 2]
        device_include_string = ", ".join(
            ["'" + deviceId + "'" for deviceId in device_subset_include]
        )
        query_string = "select * from devices where deviceId in [{}]".format(
            device_include_string
        )

        self.command_execute_assert(
            'iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 8 -y -p sys anno app'.format(
                LIVE_HUB, LIVE_RG, query_string, enqueued_time
            ),
            device_subset_include,
        )

        # Expect failure for excluded devices
        device_subset_exclude = device_ids[device_count // 2 :]
        with pytest.raises(Exception):
            self.command_execute_assert(
                'iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 8 -y -p sys anno app'.format(
                    LIVE_HUB, LIVE_RG, query_string, enqueued_time
                ),
                device_subset_exclude,
            )

        # Monitor events with --login parameter
        self.command_execute_assert(
            "iot hub monitor-events -t 8 -y -p all --cg {} --et {} --login {}".format(
                LIVE_CONSUMER_GROUPS[2], enqueued_time, self.connection_string
            ),
            device_ids,
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload, but do not pass $.ct property
        iot_device_send_message(
            client,
            device_ids[i],
            LIVE_HUB,
            send_message_data,
            "",
            1,
            LIVE_RG,
            None
        )

        # Monitor messages for ugly JSON output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            ["\\r\\n"],
        )

        # Monitor messages and parse payload as JSON with the --ct parameter
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 --ct application/json -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time
            ),
            ['"payload_data1": "payload_value1"'],
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload and have $.ct property
        iot_device_send_message(
            client,
            device_ids[i],
            LIVE_HUB,
            send_message_data,
            "$.ct=application/json",
            1,
            LIVE_RG,
        )

        # Monitor messages for pretty JSON output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            ['"payload_data1": "payload_value1"'],
        )

        # Monitor messages with yaml output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 -y -o yaml".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time
            ),
            ["payload_data1: payload_value1"],
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have improperly formatted JSON payload and a $.ct property
        iot_device_send_message(
            client,
            device_ids[i],
            LIVE_HUB,
            '{\r\n"payload_data1""payload_value1"\r\n}',
            "$.ct=application/json",
            1,
            LIVE_RG,
        )

        # Monitor messages to ensure it returns improperly formatted JSON
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 8 -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            ['{\\r\\n\\"payload_data1\\"\\"payload_value1\\"\\r\\n}'],
        )

        for cg in LIVE_CONSUMER_GROUPS:
            self.cmd(
                "az iot hub consumer-group delete --hub-name {} --resource-group {} --name {}".format(
                    LIVE_HUB, LIVE_RG, cg
                ),
                expect_failure=False,
            )

    def test_hub_monitor_feedback(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        for i in range(device_count):
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {}".format(
                    device_ids[i], LIVE_HUB, LIVE_RG
                ),
                checks=[self.check("deviceId", device_ids[i])],
            )

        ack = "full"
        self.cmd(
            "iot device c2d-message send -d {} --hub-name {} -g {} --ack {} -y".format(
                device_ids[0], LIVE_HUB, LIVE_RG, ack
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --hub-name {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            )
        ).get_output_in_json()

        system_props = result["properties"]["system"]
        msg_id = system_props["iothub-messageid"]

        etag = result["etag"]
        assert system_props["iothub-ack"] == ack

        self.cmd(
            "iot device c2d-message complete -d {} --hub-name {} -g {} -e {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, etag
            )
        )

        self.command_execute_assert(
            "iot hub monitor-feedback -n {} -g {} -w {} -y".format(
                LIVE_HUB, LIVE_RG, msg_id
            ),
            ["description: Success"],
        )

        # With connection string - filter on device
        ack = "positive"
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ack {} -y".format(
                device_ids[0], self.connection_string, ack
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()

        system_props = result["properties"]["system"]
        msg_id = system_props["iothub-messageid"]

        etag = result["etag"]
        assert system_props["iothub-ack"] == ack

        self.cmd(
            "iot device c2d-message complete -d {} --login {} -e {}".format(
                device_ids[0], self.connection_string, etag
            )
        )

        self.command_execute_assert(
            "iot hub monitor-feedback --login {} -w {} -d {} -y".format(
                self.connection_string, msg_id, device_ids[0]
            ),
            ["description: Success"],
        )

        # With connection string - dead lettered case + unrelated ack
        ack = "negative"

        # Create some noise
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ack {} -y".format(
                device_ids[0], self.connection_string, ack
            ),
            checks=self.is_empty(),
        )
        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()
        etag = result["etag"]

        self.cmd(
            "iot device c2d-message reject -d {} --login {} -e {}".format(
                device_ids[0], self.connection_string, etag
            )
        )

        # Target message
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ack {} -y".format(
                device_ids[0], self.connection_string, ack
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()

        system_props = result["properties"]["system"]
        msg_id = system_props["iothub-messageid"]

        etag = result["etag"]
        assert system_props["iothub-ack"] == ack

        self.cmd(
            "iot device c2d-message reject -d {} --login {} -e {}".format(
                device_ids[0], self.connection_string, etag
            )
        )

        self.command_execute_assert(
            "iot hub monitor-feedback --login {} -w {} -y".format(self.connection_string, msg_id),
            ["description: Message rejected"],
        )

        # purge messages
        num_messages = 3
        for i in range(num_messages):
            self.cmd(
                "iot device c2d-message send -d {} --login {}".format(
                    device_ids[0], self.connection_string
                ),
                checks=self.is_empty(),
            )
        purge_result = self.cmd(
            "iot device c2d-message purge -d {} --login {}".format(
                device_ids[0], self.connection_string
            )
        ).get_output_in_json()
        assert purge_result["deviceId"] == device_ids[0]
        assert purge_result["totalMessagesPurged"] == num_messages
        assert not purge_result["moduleId"]

        # Errors with multiple ack arguments
        self.cmd(
            "iot device c2d-message receive -d {} --login {} --complete --abandon".format(
                device_ids[0], self.connection_string
            ),
            expect_failure=True,
        )
        self.cmd(
            "iot device c2d-message receive -d {} --login {} --reject --abandon".format(
                device_ids[0], self.connection_string
            ),
            expect_failure=True,
        )
        self.cmd(
            "iot device c2d-message receive -d {} --login {} --reject --complete --abandon".format(
                device_ids[0], self.connection_string
            ),
            expect_failure=True,
        )

        # Receive with auto-ack
        for ack_test in ["complete", "abandon", "reject"]:
            self.cmd(
                "iot device c2d-message send -d {} --login {}".format(
                    device_ids[0], self.connection_string
                ),
                checks=self.is_empty(),
            )
            result = self.cmd(
                "iot device c2d-message receive -d {} --login {} --{}".format(
                    device_ids[0], self.connection_string, ack_test
                )
            ).get_output_in_json()
            assert result["ack"] == ack_test
            assert json.dumps(result["data"])
            assert json.dumps(result["properties"]["system"])
