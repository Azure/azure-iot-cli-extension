# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
import json

from time import time
from uuid import uuid4
from . import IoTLiveScenarioTest, PREFIX_DEVICE

# Temporary workaround.
from azext_iot.common.utility import (
    validate_min_python_version,
    execute_onthread,
    calculate_millisec_since_unix_epoch_utc,
    validate_key_value_pairs
)

# Set these to the proper IoT Hub, IoT Hub Cstring and Resource Group for Live Integration Tests.
LIVE_HUB = os.environ.get("azext_iot_testhub")
LIVE_RG = os.environ.get("azext_iot_testrg")
LIVE_HUB_CS = os.environ.get("azext_iot_testhub_cs")

LIVE_CONSUMER_GROUPS = ["test1", "test2", "test3"]


if not all([LIVE_HUB, LIVE_HUB_CS, LIVE_RG]):
    raise ValueError(
        "Set azext_iot_testhub, azext_iot_testhub_cs and azext_iot_testrg to run IoT Hub integration tests."
    )


# IoT Hub Messaging tests currently are run live due to non HTTP based interaction i.e. amqp, mqtt.
class TestIoTHubMessaging(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubMessaging, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    @pytest.mark.skipif(
        not validate_min_python_version(3, 4, exit_on_fail=False),
        reason="minimum python version not satisfied",
    )
    def test_uamqp_device_messaging(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        test_body = str(uuid4())
        test_props = "key0={};key1={}".format(str(uuid4()), str(uuid4()))
        test_cid = str(uuid4())
        test_mid = str(uuid4())
        test_ct = "text/plain"
        test_et = int((time() + 3600) * 1000)  # milliseconds since epoch
        test_ce = "utf8"

        self.kwargs["c2d_json_send_data"] = json.dumps({"data": str(uuid4())})

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

        # Send C2D message via --login + application/json content ype

        test_ct = "application/json"
        test_mid = str(uuid4())

        self.cmd(
            """iot device c2d-message send -d {} --login {} --data '{}' --cid {} --mid {} --ct {} --expiry {}
            --ce {} --ack positive --props {}""".format(
                device_ids[0],
                LIVE_HUB_CS,
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
                device_ids[0], LIVE_HUB_CS
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
                device_ids[0], etag, LIVE_HUB_CS
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
                device_ids[0], "full", LIVE_HUB_CS
            )
        )
        token.set()
        thread.join()

        # Error - invalid wait when no ack requested
        self.cmd(
            "iot device c2d-message send -d {} --login {} --wait -y".format(
                device_ids[0], LIVE_HUB_CS
            ),
            expect_failure=True,
        )

        # Error - content-type is application/json but data is not.
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ct application/json --data notjson".format(
                device_ids[0], LIVE_HUB_CS
            ),
            expect_failure=True,
        )

        # Error - expiry is in the past.
        self.cmd(
            "iot device c2d-message send -d {} --login {} --expiry {}".format(
                device_ids[0], LIVE_HUB_CS, int(time() * 1000)
            ),
            expect_failure=True,
        )

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
                device_ids[0], LIVE_HUB_CS
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
                device_ids[0], LIVE_HUB_CS, etag
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
                device_ids[0], LIVE_HUB_CS, etag
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
                device_ids[0], LIVE_HUB_CS, etag
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
                device_ids[0], LIVE_HUB_CS, 2, 1, "IoT Ext Test"
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
                device_ids[0], LIVE_HUB_CS, 2, 1, "IoT Ext Test"
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
                device_ids[0], LIVE_HUB_CS
            ),
            checks=self.is_empty(),
        )

    @pytest.mark.skipif(
        not validate_min_python_version(3, 5, exit_on_fail=False),
        reason="minimum python version not satisfied",
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

        # Test with invalid connection string
        self.cmd(
            "iot hub monitor-events -t 1 -y --login {}".format(LIVE_HUB_CS + "zzz"),
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
                    '{\r\n"payload_data1":"payload_value1"\r\n}',
                    "$.mid=12345;key0=value0;key1=1",
                    1,
                    LIVE_RG,
                    None,
                    0,
                ],
                max_runs=1,
            )
        # Monitor events for all devices and include sys, anno, app
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y -p sys anno app".format(
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
            "iot hub monitor-events -n {} -g {} -d {} --cg {} --et {} -t 10 -y -p all".format(
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
            "iot hub monitor-events -n {} -g {} -d {} --et {} -t 10 -y -p sys anno app".format(
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
            'iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 10 -y -p sys anno app'.format(
                LIVE_HUB, LIVE_RG, query_string, enqueued_time
            ),
            device_subset_include,
        )

        # Expect failure for excluded devices
        device_subset_exclude = device_ids[device_count // 2 :]
        with pytest.raises(Exception):
            self.command_execute_assert(
                'iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 10 -y -p sys anno app'.format(
                    LIVE_HUB, LIVE_RG, query_string, enqueued_time
                ),
                device_subset_exclude,
            )

        # Monitor events with --login parameter
        self.command_execute_assert(
            "iot hub monitor-events -t 10 -y -p all --cg {} --et {} --login {}".format(
                LIVE_CONSUMER_GROUPS[2], enqueued_time, LIVE_HUB_CS
            ),
            device_ids,
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload, but do not pass $.ct property
        execute_onthread(
            method=iot_device_send_message,
            args=[
                client,
                device_ids[i],
                LIVE_HUB,
                '{\r\n"payload_data1":"payload_value1"\r\n}',
                "",
                1,
                LIVE_RG,
                None,
                1,
            ],
            max_runs=1,
        )

        # Monitor messages for ugly JSON output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            ["\\r\\n"],
        )

        # Monitor messages and parse payload as JSON with the --ct parameter
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 --ct application/json -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time
            ),
            ['"payload_data1": "payload_value1"'],
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload and have $.ct property
        execute_onthread(
            method=iot_device_send_message,
            args=[
                client,
                device_ids[i],
                LIVE_HUB,
                '{\r\n"payload_data1":"payload_value1"\r\n}',
                "$.ct=application/json",
                1,
                LIVE_RG,
            ],
            max_runs=1,
        )

        # Monitor messages for pretty JSON output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time
            ),
            ['"payload_data1": "payload_value1"'],
        )

        # Monitor messages with yaml output
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y -o yaml".format(
                LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time
            ),
            ["payload_data1: payload_value1"],
        )

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have improperly formatted JSON payload and a $.ct property
        execute_onthread(
            method=iot_device_send_message,
            args=[
                client,
                device_ids[i],
                LIVE_HUB,
                '{\r\n"payload_data1""payload_value1"\r\n}',
                "$.ct=application/json",
                1,
                LIVE_RG,
            ],
            max_runs=1,
        )

        # Monitor messages to ensure it returns improperly formatted JSON
        self.command_execute_assert(
            "iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y".format(
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

    @pytest.mark.skipif(
        not validate_min_python_version(3, 4, exit_on_fail=False),
        reason="minimum python version not satisfied",
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
                device_ids[0], LIVE_HUB_CS, ack
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], LIVE_HUB_CS
            )
        ).get_output_in_json()

        system_props = result["properties"]["system"]
        msg_id = system_props["iothub-messageid"]

        etag = result["etag"]
        assert system_props["iothub-ack"] == ack

        self.cmd(
            "iot device c2d-message complete -d {} --login {} -e {}".format(
                device_ids[0], LIVE_HUB_CS, etag
            )
        )

        self.command_execute_assert(
            "iot hub monitor-feedback --login {} -w {} -d {} -y".format(
                LIVE_HUB_CS, msg_id, device_ids[0]
            ),
            ["description: Success"],
        )

        # With connection string - dead lettered case + unrelated ack
        ack = "negative"

        # Create some noise
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ack {} -y".format(
                device_ids[0], LIVE_HUB_CS, ack
            ),
            checks=self.is_empty(),
        )
        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], LIVE_HUB_CS
            )
        ).get_output_in_json()
        etag = result["etag"]

        self.cmd(
            "iot device c2d-message reject -d {} --login {} -e {}".format(
                device_ids[0], LIVE_HUB_CS, etag
            )
        )

        # Target message
        self.cmd(
            "iot device c2d-message send -d {} --login {} --ack {} -y".format(
                device_ids[0], LIVE_HUB_CS, ack
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot device c2d-message receive -d {} --login {}".format(
                device_ids[0], LIVE_HUB_CS
            )
        ).get_output_in_json()

        system_props = result["properties"]["system"]
        msg_id = system_props["iothub-messageid"]

        etag = result["etag"]
        assert system_props["iothub-ack"] == ack

        self.cmd(
            "iot device c2d-message reject -d {} --login {} -e {}".format(
                device_ids[0], LIVE_HUB_CS, etag
            )
        )

        self.command_execute_assert(
            "iot hub monitor-feedback --login {} -w {} -y".format(LIVE_HUB_CS, msg_id),
            ["description: Message rejected"],
        )
