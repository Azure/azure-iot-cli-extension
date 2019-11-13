# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import random
import json
import pytest

from azext_iot.common.utility import read_file_content
from . import IoTLiveScenarioTest
from azext_iot.constants import DEVICE_DEVICESCOPE_PREFIX


# Set these to the proper IoT Hub, IoT Hub Cstring and Resource Group for Live Integration Tests.
LIVE_HUB = os.environ.get("azext_iot_testhub")
LIVE_RG = os.environ.get("azext_iot_testrg")
LIVE_HUB_CS = os.environ.get("azext_iot_testhub_cs")
LIVE_HUB_MIXED_CASE_CS = LIVE_HUB_CS.replace("HostName", "hostname", 1)

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE = os.environ.get("azext_iot_teststorageuri")
LIVE_CONSUMER_GROUPS = ["test1", "test2", "test3"]

if not all([LIVE_HUB, LIVE_HUB_CS, LIVE_RG]):
    raise ValueError(
        "Set azext_iot_testhub, azext_iot_testhub_cs and azext_iot_testrg to run IoT Hub integration tests."
    )

CWD = os.path.dirname(os.path.abspath(__file__))

PRIMARY_THUMBPRINT = "A361EA6A7119A8B0B7BBFFA2EAFDAD1F9D5BED8C"
SECONDARY_THUMBPRINT = "14963E8F3BA5B3984110B3C1CA8E8B8988599087"


class TestIoTHub(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHub, self).__init__(test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS)

    def test_hub(self):
        self.cmd(
            "az iot hub generate-sas-token -n {} -g {}".format(LIVE_HUB, LIVE_RG),
            checks=[self.exists("sas")],
        )

        self.cmd(
            "az iot hub generate-sas-token -n {}".format(LIVE_HUB),
            checks=[self.exists("sas")],
        )

        self.cmd(
            "az iot hub generate-sas-token -n {} --du {}".format(LIVE_HUB, "1000"),
            checks=[self.exists("sas")],
        )

        # With connection string
        self.cmd(
            "az iot hub generate-sas-token --login {}".format(LIVE_HUB_CS),
            checks=[self.exists("sas")],
        )

        self.cmd(
            "az iot hub generate-sas-token --login {} --pn somepolicy".format(
                LIVE_HUB_CS
            ),
            expect_failure=True,
        )

        # With connection string
        # Error can't change key for a sas token with conn string
        self.cmd(
            "az iot hub generate-sas-token --login {} --kt secondary".format(
                LIVE_HUB_CS
            ),
            expect_failure=True,
        )

        self.cmd(
            'iot hub query --hub-name {} -q "{}"'.format(
                LIVE_HUB, "select * from devices"
            ),
            checks=[self.check("length([*])", 0)],
        )

        # With connection string
        self.cmd(
            'iot hub query --query-command "{}" --login {}'.format(
                "select * from devices", LIVE_HUB_CS
            ),
            checks=[self.check("length([*])", 0)],
        )

        # Test mode 2 handler
        self.cmd(
            'iot hub query -q "{}"'.format("select * from devices"), expect_failure=True
        )

        self.cmd(
            'iot hub query -q "{}" -l "{}"'.format(
                "select * from devices", "Hostname=badlogin;key=1235"
            ),
            expect_failure=True,
        )


class TestIoTHubDevices(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDevices, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_hub_devices(self):
        device_count = 5
        edge_device_count = 2

        device_ids = self.generate_device_names(device_count)
        edge_device_ids = self.generate_device_names(edge_device_count, edge=True)
        total_devices = device_count + edge_device_count

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[4], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", device_ids[4]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("connectionState", "Disconnected"),
                self.check("capabilities.iotEdge", False),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        for edge_device in edge_device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {} --ee --add-children {} --force".format(
                    edge_device, LIVE_HUB, LIVE_RG, device_ids[4]
                ),
                checks=[
                    self.check("deviceId", edge_device),
                    self.check("status", "enabled"),
                    self.check("statusReason", None),
                    self.check("connectionState", "Disconnected"),
                    self.check("capabilities.iotEdge", True),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                ],
            )

            device_scope_str_pattern = r"^{}{}-".format(
                DEVICE_DEVICESCOPE_PREFIX, edge_device
            )
            self.cmd(
                "iot hub device-identity show -d {} -n {} -g {}".format(
                    device_ids[4], LIVE_HUB, LIVE_RG
                ),
                checks=[
                    self.check("deviceId", device_ids[4]),
                    self.check_pattern("deviceScope", device_scope_str_pattern),
                ],
            )

        # All edge devices + child device
        query_checks = [self.check("length([*])", edge_device_count + 1)]
        for i in edge_device_ids:
            query_checks.append(self.exists("[?deviceId==`{}`]".format(i)))
        query_checks.append(self.exists("[?deviceId==`{}`]".format(device_ids[4])))

        # Not currently supported
        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --auth-method x509_thumbprint --ee".format(
                "willnotwork", LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # Not currently supported
        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --auth-method x509_ca --ee".format(
                "willnotwork", LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        self.cmd(
            'iot hub query --hub-name {} -g {} -q "{}"'.format(
                LIVE_HUB, LIVE_RG, "select * from devices"
            ),
            checks=query_checks,
        )

        # With connection string
        self.cmd(
            'iot hub query -q "{}" --login {}'.format(
                "select * from devices", LIVE_HUB_CS
            ),
            checks=query_checks,
        )

        # -1 for no return limit
        self.cmd(
            'iot hub query -q "{}" --login {} --top -1'.format(
                "select * from devices", LIVE_HUB_CS
            ),
            checks=query_checks,
        )

        self.cmd(
            """iot hub device-identity create --device-id {} --hub-name {} --resource-group {}
                    --auth-method x509_thumbprint --primary-thumbprint {} --secondary-thumbprint {}""".format(
                device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                PRIMARY_THUMBPRINT,
                SECONDARY_THUMBPRINT,
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("capabilities.iotEdge", False),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check(
                    "authentication.x509Thumbprint.primaryThumbprint",
                    PRIMARY_THUMBPRINT,
                ),
                self.check(
                    "authentication.x509Thumbprint.secondaryThumbprint",
                    SECONDARY_THUMBPRINT,
                ),
            ],
        )

        self.cmd(
            """iot hub device-identity create --device-id {} --hub-name {} --resource-group {}
                    --auth-method x509_thumbprint --valid-days {}""".format(
                device_ids[1], LIVE_HUB, LIVE_RG, 10
            ),
            checks=[
                self.check("deviceId", device_ids[1]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("capabilities.iotEdge", False),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.exists("authentication.x509Thumbprint.primaryThumbprint"),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
            ],
        )

        # With connection string
        status_reason = "Test Status Reason"
        self.cmd(
            '''iot hub device-identity create --device-id {} --login {}
                    --auth-method x509_ca --status disabled --status-reason "{}"'''.format(
                device_ids[2], LIVE_HUB_CS, status_reason
            ),
            checks=[
                self.check("deviceId", device_ids[2]),
                self.check("status", "disabled"),
                self.check("statusReason", status_reason),
                self.check("capabilities.iotEdge", False),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check("authentication.x509Thumbprint.primaryThumbprint", None),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
            ],
        )

        child_device_scope_str_pattern = r"^{}{}-".format(
            DEVICE_DEVICESCOPE_PREFIX, edge_device_ids[0]
        )

        # Create device with parent device
        self.cmd(
            """iot hub device-identity create --device-id {} --hub-name {} --resource-group {}
                    --auth-method x509_thumbprint --valid-days {} --set-parent {}""".format(
                device_ids[3], LIVE_HUB, LIVE_RG, 10, edge_device_ids[0]
            ),
            checks=[
                self.check("deviceId", device_ids[3]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("capabilities.iotEdge", False),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.exists("authentication.x509Thumbprint.primaryThumbprint"),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
                self.exists("deviceScope"),
                self.check_pattern("deviceScope", child_device_scope_str_pattern),
            ],
        )

        self.cmd(
            "iot hub device-identity show -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("connectionState", "Disconnected"),
                self.check("capabilities.iotEdge", True),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub device-identity show -d {} --login {}".format(
                edge_device_ids[0], LIVE_HUB_CS
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("connectionState", "Disconnected"),
                self.check("capabilities.iotEdge", True),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # List all devices
        self.cmd(
            "iot hub device-identity list --hub-name {} --resource-group {}".format(
                LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("length([*])", total_devices)],
        )

        self.cmd(
            "iot hub device-identity list --hub-name {} --resource-group {} --top -1".format(
                LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("length([*])", total_devices)],
        )

        # List only edge devices
        self.cmd(
            "iot hub device-identity list -n {} -g {} --ee".format(LIVE_HUB, LIVE_RG),
            checks=[self.check("length([*])", edge_device_count)],
        )

        # With connection string
        self.cmd(
            "iot hub device-identity list --ee --login {}".format(LIVE_HUB_CS),
            checks=[self.check("length([*])", edge_device_count)],
        )

        self.cmd(
            "iot hub device-identity update -d {} -n {} -g {} --set capabilities.iotEdge={}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, True
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.check("capabilities.iotEdge", True),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check(
                    "authentication.x509Thumbprint.primaryThumbprint",
                    PRIMARY_THUMBPRINT,
                ),
                self.check(
                    "authentication.x509Thumbprint.secondaryThumbprint",
                    SECONDARY_THUMBPRINT,
                ),
            ],
        )

        self.cmd(
            "iot hub device-identity update -d {} -n {} -g {} --ee {} --auth-method {}"
            .format(device_ids[0], LIVE_HUB, LIVE_RG, False, 'x509_ca'),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.check("capabilities.iotEdge", False),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check("authentication.x509Thumbprint.primaryThumbprint", None),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
                self.check("authentication.type", 'certificateAuthority')
            ]
        )

        self.cmd("iot hub device-identity update -d {} -n {} -g {} --auth-method {}"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 'x509_thumbprint'),
                 expect_failure=True)

        self.cmd("iot hub device-identity update -d {} -n {} -g {} --auth-method {} --pk {}"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 'shared_private_key', '123'),
                 expect_failure=True)

        self.cmd(
            '''iot hub device-identity update -d {} -n {} -g {} --primary-key=""
                    --secondary-key=""'''.format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_device_ids[1]),
                self.check("status", "enabled"),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # With connection string
        self.cmd(
            '''iot hub device-identity update -d {} --login {} --set authentication.symmetricKey.primaryKey=""
                 authentication.symmetricKey.secondaryKey=""'''.format(
                edge_device_ids[1], LIVE_HUB_CS
            ),
            checks=[
                self.check("deviceId", edge_device_ids[1]),
                self.check("status", "enabled"),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        sym_conn_str_pattern = r"^HostName={}\.azure-devices\.net;DeviceId={};SharedAccessKey=".format(
            LIVE_HUB, edge_device_ids[0]
        )
        cer_conn_str_pattern = r"^HostName={}\.azure-devices\.net;DeviceId={};x509=true".format(
            LIVE_HUB, device_ids[2]
        )

        self.cmd(
            "iot hub device-identity show-connection-string -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check_pattern("connectionString", sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub device-identity show-connection-string -d {} -n {} -g {} --kt {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, "secondary"
            ),
            checks=[self.check_pattern("connectionString", sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub device-identity show-connection-string -d {} -n {} -g {}".format(
                device_ids[2], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check_pattern("connectionString", cer_conn_str_pattern)],
        )

        self.cmd(
            "iot hub generate-sas-token -n {} -g {} -d {}".format(
                LIVE_HUB, LIVE_RG, edge_device_ids[0]
            ),
            checks=[self.exists("sas")],
        )

        self.cmd(
            "iot hub generate-sas-token -n {} -g {} -d {} --du {}".format(
                LIVE_HUB, LIVE_RG, edge_device_ids[0], "1000"
            ),
            checks=[self.exists("sas")],
        )

        # None SAS device auth
        self.cmd(
            "iot hub generate-sas-token -n {} -g {} -d {}".format(
                LIVE_HUB, LIVE_RG, device_ids[1]
            ),
            expect_failure=True,
        )

        self.cmd(
            'iot hub generate-sas-token -n {} -g {} -d {} --kt "secondary"'.format(
                LIVE_HUB, LIVE_RG, edge_device_ids[1]
            ),
            checks=[self.exists("sas")],
        )

        # With connection string
        self.cmd(
            "iot hub generate-sas-token -d {} --login {}".format(
                edge_device_ids[0], LIVE_HUB_CS
            ),
            checks=[self.exists("sas")],
        )

        self.cmd(
            'iot hub generate-sas-token -d {} --login {} --kt "secondary"'.format(
                edge_device_ids[1], LIVE_HUB_CS
            ),
            checks=[self.exists("sas")],
        )

        self.cmd(
            'iot hub generate-sas-token -d {} --login {} --pn "mypolicy"'.format(
                edge_device_ids[1], LIVE_HUB_CS
            ),
            expect_failure=True,
        )


class TestIoTHubDeviceTwins(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDeviceTwins, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_hub_device_twins(self):
        self.kwargs["generic_dict"] = {"key": "value"}
        self.kwargs["bad_format"] = "{'key: 'value'}"

        device_count = 3
        device_ids = self.generate_device_names(device_count)

        for device in device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {}".format(
                    device, LIVE_HUB, LIVE_RG
                ),
                checks=[self.check("deviceId", device)],
            )

        self.cmd(
            "iot hub device-twin show -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub device-twin show -d {} --login {}".format(
                device_ids[0], LIVE_HUB_CS
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        result = self.cmd(
            "iot hub device-twin update -d {} -n {} -g {} --set properties.desired.special={}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, '"{generic_dict}"'
            )
        ).get_output_in_json()
        assert result["deviceId"] == device_ids[0]
        assert result["properties"]["desired"]["special"]["key"] == "value"

        # Removal of desired property from twin
        result = self.cmd(
            'iot hub device-twin update -d {} -n {} -g {} --set properties.desired.special="null"'.format(
                device_ids[0], LIVE_HUB, LIVE_RG
            )
        ).get_output_in_json()
        assert result["deviceId"] == device_ids[0]
        assert result["properties"]["desired"].get("special") is None

        # With connection string
        result = self.cmd(
            "iot hub device-twin update -d {} --login {} --set properties.desired.special={}".format(
                device_ids[0], LIVE_HUB_CS, '"{generic_dict}"'
            )
        ).get_output_in_json()
        assert result["deviceId"] == device_ids[0]
        assert result["properties"]["desired"]["special"]["key"] == "value"

        # Error case, test type enforcer
        self.cmd(
            "iot hub device-twin update -d {} -n {} -g {} --set tags={}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, '"{bad_format}"'
            ),
            expect_failure=True,
        )

        content_path = os.path.join(CWD, "test_generic_replace.json")
        self.cmd(
            "iot hub device-twin replace -d {} -n {} -g {} -j '{}'".format(
                device_ids[0], LIVE_HUB, LIVE_RG, content_path
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        self.kwargs["twin_payload"] = read_file_content(content_path)
        self.cmd(
            "iot hub device-twin replace -d {} -n {} -g {} -j '{}'".format(
                device_ids[1], LIVE_HUB, LIVE_RG, "{twin_payload}"
            ),
            checks=[
                self.check("deviceId", device_ids[1]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub device-twin replace -d {} --login {} -j '{}'".format(
                device_ids[1], LIVE_HUB_CS, "{twin_payload}"
            ),
            checks=[
                self.check("deviceId", device_ids[1]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        # TODO move distributed tracing tests
        self.cmd(
            "iot hub distributed-tracing show -d {} -n {} -g {}".format(
                device_ids[2], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        result = self.cmd(
            "iot hub distributed-tracing update -d {} -n {} -g {} --sm on --sr 50".format(
                device_ids[2], LIVE_HUB, LIVE_RG
            )
        ).get_output_in_json()
        assert result["deviceId"] == device_ids[2]
        assert result["samplingMode"] == "enabled"
        assert result["samplingRate"] == "50%"
        assert not result["isSynced"]


class TestIoTHubModules(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubModules, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_hub_modules(self):
        edge_device_count = 2
        device_count = 1
        module_count = 2

        edge_device_ids = self.generate_device_names(edge_device_count, edge=True)
        device_ids = self.generate_device_names(device_count)
        module_ids = self.generate_module_names(module_count)

        for edge_device in edge_device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                    edge_device, LIVE_HUB, LIVE_RG
                ),
                checks=[self.check("deviceId", edge_device)],
            )

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        # Symmetric Key
        # With connection string
        self.cmd(
            "iot hub module-identity create --device-id {} --hub-name {} --resource-group {} --module-id {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[1]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[1]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        self.cmd(
            "iot hub module-identity create -d {} --login {} -m {}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # Error can't get a sas token for module without device
        self.cmd(
            "az iot hub generate-sas-token -n {} -g {} -m {}".format(
                LIVE_HUB, LIVE_RG, module_ids[1]
            ),
            expect_failure=True,
        )

        # sas token for module
        self.cmd(
            "iot hub generate-sas-token -n {} -g {} -d {} -m {}".format(
                LIVE_HUB, LIVE_RG, edge_device_ids[0], module_ids[1]
            ),
            checks=[self.exists("sas")],
        )

        # sas token for module with connection string
        self.cmd(
            "iot hub generate-sas-token -d {} -m {} --login {}".format(
                edge_device_ids[0], module_ids[1], LIVE_HUB_CS
            ),
            checks=[self.exists("sas")],
        )

        # sas token for module with mixed case connection string
        self.cmd(
            "iot hub generate-sas-token -d {} -m {} --login {}".format(
                edge_device_ids[0], module_ids[1], LIVE_HUB_MIXED_CASE_CS
            ),
            checks=[self.exists("sas")],
        )

        # X509 Thumbprint
        # With connection string
        self.cmd(
            """iot hub module-identity create --module-id {} --device-id {} --login {}
                    --auth-method x509_thumbprint --primary-thumbprint {} --secondary-thumbprint {}""".format(
                module_ids[0],
                device_ids[0],
                LIVE_HUB_CS,
                PRIMARY_THUMBPRINT,
                SECONDARY_THUMBPRINT,
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check(
                    "authentication.x509Thumbprint.primaryThumbprint",
                    PRIMARY_THUMBPRINT,
                ),
                self.check(
                    "authentication.x509Thumbprint.secondaryThumbprint",
                    SECONDARY_THUMBPRINT,
                ),
            ],
        )

        self.cmd(
            """iot hub module-identity create -m {} -d {} -n {} -g {} --am x509_thumbprint --vd {}""".format(
                module_ids[1], device_ids[0], LIVE_HUB, LIVE_RG, 10
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("moduleId", module_ids[1]),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.exists("authentication.x509Thumbprint.primaryThumbprint"),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
            ],
        )

        # X509 CA
        # With connection string
        self.cmd(
            """iot hub module-identity create --module-id {} --device-id {} --login {} --auth-method x509_ca""".format(
                module_ids[0], edge_device_ids[1], LIVE_HUB_CS
            ),
            checks=[
                self.check("deviceId", edge_device_ids[1]),
                self.check("moduleId", module_ids[0]),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check("authentication.x509Thumbprint.primaryThumbprint", None),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
            ],
        )

        # Includes $edgeAgent && $edgeHub system modules
        result = self.cmd(
            'iot hub query --hub-name {} -g {} -q "{}"'.format(
                LIVE_HUB,
                LIVE_RG,
                "select * from devices.modules where devices.deviceId='{}'".format(
                    edge_device_ids[0]
                ),
            )
        ).get_output_in_json()
        assert len(result) == 4

        self.cmd(
            '''iot hub module-identity update -d {} -n {} -g {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''.format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # With connection string
        self.cmd(
            '''iot hub module-identity update -d {} --login {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''.format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        self.cmd(
            "iot hub module-identity list -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("length([*])", 4),
                self.exists("[?moduleId=='$edgeAgent']"),
                self.exists("[?moduleId=='$edgeHub']"),
            ],
        )

        self.cmd(
            "iot hub module-identity list -d {} -n {} -g {} --top -1".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("length([*])", 3),
                self.exists("[?moduleId=='$edgeAgent']"),
                self.exists("[?moduleId=='$edgeHub']"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub module-identity list -d {} --login {}".format(
                edge_device_ids[0], LIVE_HUB_CS
            ),
            checks=[
                self.check("length([*])", 4),
                self.exists("[?moduleId=='$edgeAgent']"),
                self.exists("[?moduleId=='$edgeHub']"),
            ],
        )

        self.cmd(
            "iot hub module-identity show -d {} -n {} -g {} -m {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub module-identity show -d {} --login {} -m {}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        mod_sym_conn_str_pattern = r"^HostName={}\.azure-devices\.net;DeviceId={};ModuleId={};SharedAccessKey=".format(
            LIVE_HUB, edge_device_ids[0], module_ids[0]
        )
        self.cmd(
            "iot hub module-identity show-connection-string -d {} -n {} -g {} -m {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        # With connection string
        self.cmd(
            "iot hub module-identity show-connection-string -d {} --login {} -m {}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0]
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub module-identity show-connection-string -d {} -n {} -g {} -m {} --kt {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], "secondary"
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        for i in module_ids:
            if module_ids.index(i) == (module_count - 1):
                # With connection string
                self.cmd(
                    "iot hub module-identity delete -d {} --login {} --module-id {}".format(
                        edge_device_ids[0], LIVE_HUB_CS, i
                    ),
                    checks=self.is_empty(),
                )
            else:
                self.cmd(
                    "iot hub module-identity delete -d {} -n {} -g {} --module-id {}".format(
                        edge_device_ids[0], LIVE_HUB, LIVE_RG, i
                    ),
                    checks=self.is_empty(),
                )


class TestIoTHubModuleTwins(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubModuleTwins, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_hub_module_twins(self):
        self.kwargs["generic_dict"] = {"key": "value"}
        self.kwargs["bad_format"] = "{'key: 'value'}"

        edge_device_count = 1
        device_count = 1
        module_count = 1

        edge_device_ids = self.generate_device_names(edge_device_count, True)
        device_ids = self.generate_device_names(device_count)
        module_ids = self.generate_module_names(module_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", edge_device_ids[0])],
        )

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        self.cmd(
            "iot hub module-identity create -d {} -n {} -g {} -m {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        self.cmd(
            "iot hub module-identity create -d {} -n {} -g {} -m {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        self.cmd(
            "iot hub module-twin show -d {} -n {} -g {} -m {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub module-twin show -d {} --login {} -m {}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        self.cmd(
            "iot hub module-twin update -d {} -n {} -g {} -m {} --set properties.desired.special={}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], '"{generic_dict}"'
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("properties.desired.special.key", "value"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub module-twin update -d {} --login {} -m {} --set properties.desired.special={}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{generic_dict}"'
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("properties.desired.special.key", "value"),
            ],
        )

        # Error case test type enforcer
        self.cmd(
            "iot hub module-twin update -d {} --login {} -m {} --set properties.desired={}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{bad_format}"'
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot hub module-twin update -d {} --login {} -m {} --set tags={}".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{bad_format}"'
            ),
            expect_failure=True,
        )

        content_path = os.path.join(CWD, "test_generic_replace.json")
        self.cmd(
            "iot hub module-twin replace -d {} -n {} -g {} -m {} -j '{}'".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], content_path
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub module-twin replace -d {} --login {} -m {} -j '{}'".format(
                edge_device_ids[0], LIVE_HUB_CS, module_ids[0], content_path
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        self.kwargs["twin_payload"] = read_file_content(content_path)
        self.cmd(
            "iot hub module-twin replace -d {} -n {} -g {} -m {} -j '{}'".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], "{twin_payload}"
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        for i in module_ids:
            self.cmd(
                "iot hub module-identity delete -d {} -n {} -g {} --module-id {}".format(
                    edge_device_ids[0], LIVE_HUB, LIVE_RG, i
                ),
                checks=self.is_empty(),
            )


class TestIoTHubDeviceConfigs(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDeviceConfigs, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_device_configurations(self):
        self.kwargs["generic_dict"] = {"key": "value"}
        self.kwargs["bad_format"] = "{'key: 'value'}"

        config_count = 5
        config_ids = self.generate_config_names(config_count)

        content_path = os.path.join(CWD, "test_config_device_content.json")
        metrics_path = os.path.join(CWD, "test_config_device_metrics.json")

        self.kwargs["configuration_payload"] = read_file_content(content_path)
        self.kwargs["metrics_payload"] = read_file_content(metrics_path)

        priority = random.randint(1, 10)
        condition = "tags.building=9 and tags.environment='test'"
        empty_metrics = {"queries": {}, "results": {}}

        # With connection string
        self.cmd(
            "iot hub configuration create -c {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}'".format(
                config_ids[0],
                LIVE_HUB_CS,
                priority,
                condition,
                '"{generic_dict}"',
                content_path,
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check("metrics", empty_metrics),
            ],
        )

        self.cmd(
            """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict}"',
                "{configuration_payload}",
            ),
            checks=[
                self.check("id", config_ids[1]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check("metrics", empty_metrics),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub configuration create -c {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}' -m '{}'".format(
                config_ids[2],
                LIVE_HUB_CS,
                priority,
                condition,
                '"{generic_dict}"',
                content_path,
                metrics_path,
            ),
            checks=[
                self.check("id", config_ids[2]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["metrics_payload"])["queries"],
                ),
            ],
        )

        self.cmd(
            """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}' --metrics '{}'""".format(
                config_ids[3],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict}"',
                "{configuration_payload}",
                "{metrics_payload}",
            ),
            checks=[
                self.check("id", config_ids[3]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "deviceContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["metrics_payload"])["queries"],
                ),
            ],
        )

        self.cmd(
            """iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                 --content '{}' """.format(
                config_ids[4], LIVE_HUB, LIVE_RG, priority, "{configuration_payload}"
            ),
            checks=[
                self.check("id", config_ids[4]),
                self.check("priority", priority),
                self.check("targetCondition", ""),
                self.check(
                    "content.deviceContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "deviceContent"
                    ],
                ),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub configuration show -c {} --login {}".format(
                config_ids[0], LIVE_HUB_CS
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check("metrics", empty_metrics),
            ],
        )

        self.cmd(
            "iot hub configuration show -c {} --login {}".format(
                config_ids[3], LIVE_HUB_CS
            ),
            checks=[
                self.check("id", config_ids[3]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["metrics_payload"])["queries"],
                ),
            ],
        )

        self.cmd(
            "iot hub configuration show --config-id {} --hub-name {} --resource-group {}".format(
                config_ids[2], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("id", config_ids[2]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["metrics_payload"])["queries"],
                ),
            ],
        )

        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs["generic_dict_updated"] = {"key": "super_value"}
        self.cmd(
            'iot hub configuration update -c {} -n {} -g {} --set priority={} targetCondition="{}" labels={}'.format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict_updated}"',
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict_updated"]),
            ],
        )

        # With connection string
        self.cmd(
            'iot hub configuration update -c {} --login {} --set priority={} targetCondition="{}" labels={}'.format(
                config_ids[0],
                LIVE_HUB_CS,
                priority,
                condition,
                '"{generic_dict_updated}"',
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict_updated"]),
            ],
        )

        # Error via type enforcer
        self.cmd(
            'iot hub configuration update -c {} --login {} --set priority={} targetCondition="{}" labels={}'.format(
                config_ids[0], LIVE_HUB_CS, priority, condition, '"{bad_format}"'
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot hub configuration update -c {} --login {} --set content={}".format(
                config_ids[0], LIVE_HUB_CS, '"{bad_format}"'
            ),
            expect_failure=True,
        )

        # Metrics
        user_metric_name = "mymetric"
        system_metric_name = "appliedCount"
        config_output = self.cmd(
            "iot hub configuration show --login {} --config-id {}".format(
                LIVE_HUB_CS, config_ids[2]
            )
        ).get_output_in_json()

        self.cmd(
            "iot hub configuration show-metric --metric-id {} --login {} --config-id {} --metric-type {}".format(
                user_metric_name, LIVE_HUB_CS, config_ids[2], "user"
            ),
            checks=[
                self.check("metric", user_metric_name),
                self.check(
                    "query", config_output["metrics"]["queries"][user_metric_name]
                ),
            ],
        )

        # With connection string
        self.cmd(
            "iot hub configuration show-metric -m {} --login {} -c {} --metric-type {}".format(
                "doesnotexist", LIVE_HUB_CS, config_ids[2], "user"
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot hub configuration show-metric -m {} --login {} -c {} --metric-type {}".format(
                system_metric_name, LIVE_HUB_CS, config_ids[2], "system"
            ),
            checks=[
                self.check("metric", system_metric_name),
                self.check(
                    "query",
                    config_output["systemMetrics"]["queries"][system_metric_name],
                ),
            ],
        )

        config_list_check = [
            self.check("length([*])", 5),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2])),
            self.exists("[?id=='{}']".format(config_ids[3])),
            self.exists("[?id=='{}']".format(config_ids[4])),
        ]

        self.cmd(
            "iot hub configuration list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
            checks=config_list_check,
        )

        # With connection string
        self.cmd(
            "iot hub configuration list --login {}".format(LIVE_HUB_CS),
            checks=config_list_check,
        )

        # Error top of -1 does not work with configurations
        self.cmd(
            "iot hub configuration list -n {} -g {} --top -1".format(LIVE_HUB, LIVE_RG),
            expect_failure=True,
        )

        # Error max top of 20 with configurations
        self.cmd(
            "iot hub configuration list -n {} -g {} --top 100".format(
                LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )


class TestIoTEdge(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTEdge, self).__init__(test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS)

    def test_edge_set_modules(self):
        edge_device_count = 2
        edge_device_ids = self.generate_device_names(edge_device_count, True)

        for device_id in edge_device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                    device_id, LIVE_HUB, LIVE_RG
                )
            )

        content_path = os.path.join(CWD, "test_config_modules_content.json")
        content_path_malformed = os.path.join(
            CWD, "test_config_modules_content_malformed.json"
        )
        content_path_v1 = os.path.join(CWD, "test_config_modules_content_v1.json")

        self.kwargs["generic_content"] = read_file_content(content_path)

        # iot edge set-modules replaces apply-configuration
        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG, content_path
            ),
            checks=[self.check("length([*])", 3)],
        )

        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} --content '{}'".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG, "{generic_content}"
            ),
            self.check("length([*])", 3),
        )

        # With connection string
        self.cmd(
            "iot edge set-modules -d {} --login {} -k '{}'".format(
                edge_device_ids[1], LIVE_HUB_CS, content_path_v1
            ),
            checks=[self.check("length([*])", 4)],
        )

        # Error schema validation - Malformed deployment content causes validation error
        self.cmd(
            "iot edge set-modules -d {} -n {} -g {} -k '{}'".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG, content_path_malformed
            ),
            expect_failure=True,
        )


class TestIoTEdgeDeployments(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTEdgeDeployments, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_edge_deployments(self):
        self.kwargs["generic_dict"] = {"key": "value"}

        config_count = 3
        config_ids = self.generate_config_names(config_count)

        content_path = os.path.join(CWD, "test_config_modules_content.json")
        content_path_malformed = os.path.join(
            CWD, "test_config_modules_content_malformed.json"
        )
        content_path_v1 = os.path.join(CWD, "test_config_modules_content_v1.json")

        configuration_content = read_file_content(content_path)
        configuration_content_v1 = read_file_content(content_path_v1)
        configuration_content_malformed = read_file_content(content_path_malformed)

        # TODO: Build configuration payload generators in common tooling.
        config_object = json.loads(configuration_content)
        config_object[
            "$schema"
        ] = "http://json.schemastore.org/azure-iot-edge-deployment-2.0"
        configuration_content_with_schema = json.dumps(config_object)

        self.kwargs["configuration_payload"] = configuration_content
        self.kwargs["configuration_payload_malformed"] = configuration_content_malformed
        self.kwargs["configuration_payload_v1"] = configuration_content_v1
        self.kwargs[
            "configuration_payload_with_schema"
        ] = configuration_content_with_schema

        priority = random.randint(1, 10)
        condition = "tags.building=9 and tags.environment='test'"

        # With connection string and file path
        self.cmd(
            "iot edge deployment create -d {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}' --metrics '{}'".format(
                config_ids[0],
                LIVE_HUB_CS,
                priority,
                condition,
                '"{generic_dict}"',
                content_path,
                content_path
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["configuration_payload"])["content"][
                        "modulesContent"
                    ],
                ),
                self.check(
                    "metrics.queries",
                    json.loads(self.kwargs["configuration_payload"])["metrics"]["queries"]
                )
            ],
        )

        # Error schema validation - Malformed deployment content causes validation error
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict}"',
                "{configuration_payload_malformed}",
            ),
            expect_failure=True,
        )

        # Certain elements such as $schema included in the edge payload will be popped before validation
        self.cmd(
            """iot edge deployment create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'""".format(
                config_ids[1],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict}"',
                "{configuration_payload_with_schema}",
            ),
            checks=[
                self.check("id", config_ids[1]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.modulesContent",
                    json.loads(self.kwargs["configuration_payload_with_schema"])[
                        "content"
                    ]["modulesContent"],
                ),
                self.check(
                    "metrics.queries",
                    {}
                )
            ],
        )

        # v1 deployment content
        self.cmd(
            """iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'""".format(
                config_ids[2],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict}"',
                content_path_v1,
            ),
            checks=[
                self.check("id", config_ids[2]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
                self.check(
                    "content.modulesContent",
                    json.loads(
                        # moduleContent for v1
                        self.kwargs["configuration_payload_v1"]
                    )["content"]["moduleContent"],
                ),
            ],
        )

        # With connection string
        self.cmd(
            "iot edge deployment show -d {} --login {}".format(
                config_ids[1], LIVE_HUB_CS
            ),
            checks=[
                self.check("id", config_ids[1]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
            ],
        )

        self.cmd(
            "iot edge deployment show --deployment-id {} --hub-name {} --resource-group {}".format(
                config_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict"]),
            ],
        )

        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs["generic_dict_updated"] = {"key": "super_value"}
        self.cmd(
            'iot edge deployment update -d {} -n {} -g {} --set priority={} targetCondition="{}" labels={}'.format(
                config_ids[0],
                LIVE_HUB,
                LIVE_RG,
                priority,
                condition,
                '"{generic_dict_updated}"',
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict_updated"]),
            ],
        )

        # With connection string
        self.cmd(
            'iot edge deployment update -d {} --login {} --set priority={} targetCondition="{}" labels={}'.format(
                config_ids[0],
                LIVE_HUB_CS,
                priority,
                condition,
                '"{generic_dict_updated}"',
            ),
            checks=[
                self.check("id", config_ids[0]),
                self.check("priority", priority),
                self.check("targetCondition", condition),
                self.check("labels", self.kwargs["generic_dict_updated"]),
            ],
        )

        # Metrics
        system_metric_name = "appliedCount"
        config_output = self.cmd(
            "iot edge deployment show --login {} --deployment-id {}".format(
                LIVE_HUB_CS, config_ids[2]
            )
        ).get_output_in_json()

        self.cmd(
            "iot edge deployment show-metric --metric-id {} --deployment-id {} --hub-name {}".format(
                system_metric_name, config_ids[2], LIVE_HUB
            ),
            checks=[
                self.check("metric", system_metric_name),
                self.check(
                    "query",
                    config_output["systemMetrics"]["queries"][system_metric_name],
                ),
            ],
        )

        # With connection string
        self.cmd(
            "iot edge deployment show-metric -m {} --login {} -d {}".format(
                "doesnotexist", LIVE_HUB_CS, config_ids[2]
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot edge deployment show-metric --metric-id {} --login {} --deployment-id {}".format(
                system_metric_name, LIVE_HUB_CS, config_ids[2]
            ),
            checks=[
                self.check("metric", system_metric_name),
                self.check(
                    "query",
                    config_output["systemMetrics"]["queries"][system_metric_name],
                ),
            ],
        )

        config_list_check = [
            self.check("length([*])", 3),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2])),
        ]

        self.cmd(
            "iot edge deployment list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
            checks=config_list_check,
        )

        # With connection string
        self.cmd(
            "iot edge deployment list --login {}".format(LIVE_HUB_CS),
            checks=config_list_check,
        )

        # Explicit delete for edge deployment
        self.cmd(
            "iot edge deployment delete -d {} -n {} -g {}".format(
                config_ids[1], LIVE_HUB, LIVE_RG
            )
        )
        del self.config_ids[1]

        self.cmd(
            "iot edge deployment delete -d {} --login {}".format(
                config_ids[0], LIVE_HUB_CS
            )
        )
        del self.config_ids[0]

        # Error top of -1 does not work with configurations
        self.cmd(
            "iot edge deployment list -n {} -g {} --top -1".format(LIVE_HUB, LIVE_RG),
            expect_failure=True,
        )

        # Error max top of 20 with configurations
        self.cmd(
            "iot edge deployment list -n {} -g {} --top 100".format(LIVE_HUB, LIVE_RG),
            expect_failure=True,
        )


class TestIoTStorage(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTStorage, self).__init__(test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS)

    @pytest.mark.skipif(
        not LIVE_STORAGE, reason="empty azext_iot_teststorageuri env var"
    )
    def test_storage(self):
        device_count = 1

        content_path = os.path.join(CWD, "test_config_modules_content_v1.json")
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        self.cmd(
            'iot device upload-file -d {} -n {} --fp "{}" --ct {}'.format(
                device_ids[0], LIVE_HUB, content_path, "application/json"
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            'iot device upload-file -d {} --login {} --fp "{}" --ct {}'.format(
                device_ids[0], LIVE_HUB_CS, content_path, "application/json"
            ),
            checks=self.is_empty(),
        )

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}"'.format(
                LIVE_HUB, LIVE_STORAGE
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.exists("jobId"),
            ],
        )


class TestIoTEdgeOffline(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTEdgeOffline, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

    def test_edge_offline(self):
        device_count = 3
        edge_device_count = 2

        device_ids = self.generate_device_names(device_count)
        edge_device_ids = self.generate_device_names(edge_device_count, True)

        for edge_device in edge_device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                    edge_device, LIVE_HUB, LIVE_RG
                ),
                checks=[
                    self.check("deviceId", edge_device),
                    self.check("status", "enabled"),
                    self.check("statusReason", None),
                    self.check("connectionState", "Disconnected"),
                    self.check("capabilities.iotEdge", True),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                    self.exists("deviceScope"),
                ],
            )

        for device in device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {}".format(
                    device, LIVE_HUB, LIVE_RG
                ),
                checks=[
                    self.check("deviceId", device),
                    self.check("status", "enabled"),
                    self.check("statusReason", None),
                    self.check("connectionState", "Disconnected"),
                    self.check("capabilities.iotEdge", False),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                    self.check("deviceScope", None),
                ],
            )

        # get-parent of edge device
        self.cmd(
            "iot hub device-identity get-parent -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # get-parent of device which doesn't have any parent set
        self.cmd(
            "iot hub device-identity get-parent -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting non-edge device as a parent of non-edge device
        self.cmd(
            "iot hub device-identity set-parent -d {} --pd {} -n {} -g {}".format(
                device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting edge device as a parent of edge device
        self.cmd(
            "iot hub device-identity set-parent -d {} --pd {} -n {} -g {}".format(
                edge_device_ids[0], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add device as a child of non-edge device
        self.cmd(
            "iot hub device-identity add-children -d {} --child-list {} -n {} -g {}".format(
                device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add device list as children of edge device
        self.cmd(
            "iot hub device-identity add-children -d {} --child-list '{}' -n {} -g {}".format(
                edge_device_ids[0], ", ".join(device_ids), LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # setting edge device as a parent of non-edge device which already having different parent device
        self.cmd(
            "iot hub device-identity set-parent -d {} --pd {} -n {} -g {}".format(
                device_ids[2], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting edge device as a parent of non-edge device which already having different parent device by force
        self.cmd(
            "iot hub device-identity set-parent -d {} --pd {} -n {} -g {} --force".format(
                device_ids[2], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # get-parent of device
        self.cmd(
            "iot hub device-identity get-parent -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.exists("deviceScope"),
            ],
        )

        # add same device as a child of same parent device
        self.cmd(
            "iot hub device-identity add-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # add same device as a child of another edge device
        self.cmd(
            "iot hub device-identity add-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add same device as a child of another edge device by force
        self.cmd(
            "iot hub device-identity add-children -d {} --child-list {} -n {} -g {} --force".format(
                edge_device_ids[1], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # list child devices of edge device
        output = self.cmd(
            "iot hub device-identity list-children -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=False,
        )

        # TODO: Result should be JSON
        expected_output = "{}".format(device_ids[1])
        assert output.get_output_in_json() == expected_output

        # removing all child devices of non-edge device
        self.cmd(
            "iot hub device-identity remove-children -d {} -n {} -g {} --remove-all".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove all child devices from edge device
        self.cmd(
            "iot hub device-identity remove-children -d {} -n {} -g {} --remove-all".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # removing all child devices of edge device which doesn't have any child devices
        self.cmd(
            "iot hub device-identity remove-children -d {} -n {} -g {} --remove-all".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # removing child devices of edge device neither passing child devices list nor remove-all parameter
        self.cmd(
            "iot hub device-identity remove-children -d {} -n {} -g {}".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove edge device from edge device
        self.cmd(
            "iot hub device-identity remove-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove device from edge device but device is a child of another edge device
        self.cmd(
            "iot hub device-identity remove-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove device
        self.cmd(
            "iot hub device-identity remove-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # remove device which doesn't have any parent set
        self.cmd(
            "iot hub device-identity remove-children -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # list child devices of edge device which doesn't have any children
        self.cmd(
            "iot hub device-identity list-children -d {} -n {} -g {}".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )
