# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
import warnings

from azext_iot.common.utility import read_file_content
from . import IoTLiveScenarioTest
from .settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.constants import DEVICE_DEVICESCOPE_PREFIX

opt_env_set = ["azext_iot_teststorageuri", "azext_iot_testidentity"]

settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_BASIC, opt_env_set=opt_env_set
)

LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE = settings.env.azext_iot_teststorageuri

# Set this environment variable to enable identity-based integration tests
# You will need to have configured your IoT Hub and Storage Account before running.
LIVE_IDENTITY = settings.env.azext_iot_testidentity

LIVE_CONSUMER_GROUPS = ["test1", "test2", "test3"]

CWD = os.path.dirname(os.path.abspath(__file__))

PRIMARY_THUMBPRINT = "A361EA6A7119A8B0B7BBFFA2EAFDAD1F9D5BED8C"
SECONDARY_THUMBPRINT = "14963E8F3BA5B3984110B3C1CA8E8B8988599087"


class TestIoTHub(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHub, self).__init__(test_case, LIVE_HUB, LIVE_RG)

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
            "az iot hub generate-sas-token --login {}".format(self.connection_string),
            checks=[self.exists("sas")],
        )

        self.cmd(
            "az iot hub generate-sas-token --login {} --pn somepolicy".format(
                self.connection_string
            ),
            expect_failure=True,
        )

        # Test 'az iot hub connection-string show'
        conn_str_pattern = r'^HostName={0}.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey='.format(
            LIVE_HUB)
        conn_str_eventhub_pattern = r'^Endpoint=sb://'

        hubs_in_sub = self.cmd('iot hub connection-string show').get_output_in_json()
        hubs_in_rg = self.cmd('iot hub connection-string show -g {}'.format(LIVE_RG)).get_output_in_json()
        assert len(hubs_in_sub) >= len(hubs_in_rg)

        self.cmd('iot hub connection-string show -n {0}'.format(LIVE_HUB), checks=[
            self.check_pattern('connectionString', conn_str_pattern)
        ])

        self.cmd('iot hub connection-string show -n {0} --eh'.format(LIVE_HUB), checks=[
            self.check_pattern('connectionString', conn_str_eventhub_pattern)
        ])

        self.cmd('iot hub connection-string show -n {0} -g {1}'.format(LIVE_HUB, LIVE_RG), checks=[
            self.check('length(@)', 1),
            self.check_pattern('connectionString', conn_str_pattern)
        ])

        self.cmd('iot hub connection-string show -n {0} -g {1} --all'.format(LIVE_HUB, LIVE_RG), checks=[
            self.greater_than('length(connectionString[*])', 0),
            self.check_pattern('connectionString[0]', conn_str_pattern)
        ])

        self.cmd('iot hub connection-string show -n {0} -g {1} --all --eh'.format(LIVE_HUB, LIVE_RG), checks=[
            self.greater_than('length(connectionString[*])', 0),
            self.check_pattern('connectionString[0]', conn_str_eventhub_pattern)
        ])

        # With connection string
        # Error can't change key for a sas token with conn string
        self.cmd(
            "az iot hub generate-sas-token --login {} --kt secondary".format(
                self.connection_string
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
                "select * from devices", self.connection_string
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
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_hub_devices(self):
        device_count = 5
        edge_device_count = 2
        edge_x509_device_count = 2
        total_edge_device_count = edge_x509_device_count + edge_device_count

        device_ids = self.generate_device_names(device_count)
        edge_device_ids = self.generate_device_names(edge_device_count, edge=True)
        edge_x509_device_ids = self.generate_device_names(edge_x509_device_count, edge=True)

        total_devices = device_count + total_edge_device_count

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
        query_checks = [self.check("length([*])", total_edge_device_count + 1)]
        for i in edge_device_ids:
            query_checks.append(self.exists("[?deviceId==`{}`]".format(i)))
        query_checks.append(self.exists("[?deviceId==`{}`]".format(device_ids[4])))

        # Edge x509_thumbprint
        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --auth-method x509_thumbprint --ptp {} --stp {} --ee".format(
                edge_x509_device_ids[0], LIVE_HUB, LIVE_RG, PRIMARY_THUMBPRINT, SECONDARY_THUMBPRINT
            ),
            checks=[
                self.check("deviceId", edge_x509_device_ids[0]),
                self.check("status", "enabled"),
                self.check("statusReason", None),
                self.check("capabilities.iotEdge", True),
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
            ]
        )

        # Edge x509_ca
        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --auth-method x509_ca --ee".format(
                edge_x509_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_x509_device_ids[1]),
                self.check("status", "enabled"),
                self.check("capabilities.iotEdge", True),
                self.check("connectionState", "Disconnected"),
                self.check("authentication.symmetricKey.primaryKey", None),
                self.check("authentication.symmetricKey.secondaryKey", None),
                self.check("authentication.x509Thumbprint.primaryThumbprint", None),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", None),
                self.check("authentication.type", "certificateAuthority")
            ]
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
                "select * from devices", self.connection_string
            ),
            checks=query_checks,
        )

        # -1 for no return limit
        self.cmd(
            'iot hub query -q "{}" --login {} --top -1'.format(
                "select * from devices", self.connection_string
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
                device_ids[2], self.connection_string, status_reason
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
                self.exists("parentScopes"),
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
                edge_device_ids[0], self.connection_string
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
            checks=[self.check("length([*])", total_edge_device_count)],
        )

        # With connection string
        self.cmd(
            "iot hub device-identity list --ee --login {}".format(self.connection_string),
            checks=[self.check("length([*])", total_edge_device_count)],
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

        self.cmd(
            "iot hub device-identity update -d {} -n {} -g {} --status-reason {}"
            .format(device_ids[0], LIVE_HUB, LIVE_RG, 'TestStatusReason'),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("statusReason", 'TestStatusReason'),
            ]
        )

        self.cmd(
            "iot hub device-identity update -d {} -n {} -g {} --ee {} --status {}"
            " --status-reason {} --auth-method {} --ptp {} --stp {}"
            .format(device_ids[0], LIVE_HUB, LIVE_RG, False, 'enabled',
                    'StatusReasonUpdated', 'x509_thumbprint', PRIMARY_THUMBPRINT, SECONDARY_THUMBPRINT),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.check("capabilities.iotEdge", False),
                self.check("statusReason", 'StatusReasonUpdated'),
                self.check("authentication.x509Thumbprint.primaryThumbprint", PRIMARY_THUMBPRINT),
                self.check("authentication.x509Thumbprint.secondaryThumbprint", SECONDARY_THUMBPRINT),
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
                device_ids[4], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", device_ids[4]),
                self.check("status", "enabled"),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # With connection string
        self.cmd(
            '''iot hub device-identity update -d {} --login {} --set authentication.symmetricKey.primaryKey=""
                 authentication.symmetricKey.secondaryKey=""'''.format(
                device_ids[4], self.connection_string
            ),
            checks=[
                self.check("deviceId", device_ids[4]),
                self.check("status", "enabled"),
                self.exists("authentication.symmetricKey.primaryKey"),
                self.exists("authentication.symmetricKey.secondaryKey"),
            ],
        )

        # Test 'az iot hub device renew-key'
        device = self.cmd(
            '''iot hub device-identity renew-key -d {} -n {} -g {} --kt primary
                    '''.format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_device_ids[1])
            ]
        ).get_output_in_json()

        # Test swap keys 'az iot hub device renew-key'
        self.cmd(
            '''iot hub device-identity renew-key -d {} -n {} -g {} --kt swap
                    '''.format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("authentication.symmetricKey.primaryKey", device['authentication']['symmetricKey']['secondaryKey']),
                self.check("authentication.symmetricKey.secondaryKey", device['authentication']['symmetricKey']['primaryKey'])
            ],
        )

        # Test 'az iot hub device renew-key' with non sas authentication
        self.cmd("iot hub device-identity renew-key -d {} -n {} -g {} --kt secondary"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG),
                 expect_failure=True)

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
            "iot hub device-identity connection-string show -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check_pattern("connectionString", sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub device-identity connection-string show -d {} -n {} -g {} --kt {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, "secondary"
            ),
            checks=[self.check_pattern("connectionString", sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub device-identity connection-string show -d {} -n {} -g {}".format(
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
                edge_device_ids[0], self.connection_string
            ),
            checks=[self.exists("sas")],
        )

        self.cmd(
            'iot hub generate-sas-token -d {} --login {} --kt "secondary"'.format(
                edge_device_ids[1], self.connection_string
            ),
            checks=[self.exists("sas")],
        )

        self.cmd(
            'iot hub generate-sas-token -d {} --login {} --pn "mypolicy"'.format(
                edge_device_ids[1], self.connection_string
            ),
            expect_failure=True,
        )


class TestIoTHubDeviceTwins(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDeviceTwins, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_hub_device_twins(self):
        self.kwargs["generic_dict"] = {"key": "value"}
        self.kwargs["bad_format"] = "{'key: 'value'}"
        self.kwargs["patch_desired"] = {"patchScenario": {"desiredKey": "desiredValue"}}
        self.kwargs["patch_tags"] = {"patchScenario": {"tagkey": "tagValue"}}

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
                device_ids[0], self.connection_string
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("status", "enabled"),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        # Patch based twin update of desired props
        self.cmd(
            "iot hub device-twin update -d {} -n {} -g {} --desired {}".format(
                device_ids[2],
                LIVE_HUB,
                LIVE_RG,
                '"{patch_desired}"',
            ),
            checks=[
                self.check("deviceId", device_ids[2]),
                self.check(
                    "properties.desired.patchScenario",
                    self.kwargs["patch_desired"]["patchScenario"],
                ),
            ],
        )

        # Patch based twin update of tags with connection string
        self.cmd(
            "iot hub device-twin update -d {} --login {} --tags {}".format(
                device_ids[2], self.connection_string, '"{patch_tags}"'
            ),
            checks=[
                self.check("deviceId", device_ids[2]),
                self.check(
                    "tags.patchScenario", self.kwargs["patch_tags"]["patchScenario"]
                ),
            ],
        )

        # Patch based twin update of desired + tags
        self.cmd(
            "iot hub device-twin update -d {} -n {} --desired {} --tags {}".format(
                device_ids[2],
                LIVE_HUB,
                '"{patch_desired}"',
                '"{patch_tags}"',
            ),
            checks=[
                self.check("deviceId", device_ids[2]),
                self.check(
                    "properties.desired.patchScenario",
                    self.kwargs["patch_desired"]["patchScenario"],
                ),
                self.check(
                    "tags.patchScenario",
                    self.kwargs["patch_tags"]["patchScenario"]
                ),
            ],
        )

        # Deprecated generic update
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
                device_ids[0], self.connection_string, '"{generic_dict}"'
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
                device_ids[1], self.connection_string, "{twin_payload}"
            ),
            checks=[
                self.check("deviceId", device_ids[1]),
                self.check("properties.desired.awesome", 9001),
                self.check("properties.desired.temperature.min", 10),
                self.check("properties.desired.temperature.max", 100),
                self.check("tags.location.region", "US"),
            ],
        )

        # Region specific test
        if self.region not in ["West US 2", "North Europe", "Southeast Asia"]:
            warnings.warn(UserWarning("Skipping distributed-tracing tests. IoT Hub not in supported region!"))
        else:
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
            test_case, LIVE_HUB, LIVE_RG
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
                edge_device_ids[0], self.connection_string, module_ids[0]
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
                edge_device_ids[0], module_ids[1], self.connection_string
            ),
            checks=[self.exists("sas")],
        )

        # sas token for module with mixed case connection string
        mixed_case_cstring = self.connection_string.replace("HostName", "hostname", 1)
        self.cmd(
            "iot hub generate-sas-token -d {} -m {} --login {}".format(
                edge_device_ids[0], module_ids[1], mixed_case_cstring
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
                self.connection_string,
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
                module_ids[0], edge_device_ids[1], self.connection_string
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
                edge_device_ids[0], self.connection_string, module_ids[0]
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
                edge_device_ids[0], self.connection_string
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
                edge_device_ids[0], self.connection_string, module_ids[0]
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
                edge_device_ids[0], self.connection_string, module_ids[0]
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub module-identity show-connection-string -d {} -n {} -g {} -m {} --kt {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], "secondary"
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub module-identity connection-string show -d {} -n {} -g {} -m {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        # With connection string
        self.cmd(
            "iot hub module-identity connection-string show -d {} --login {} -m {}".format(
                edge_device_ids[0], self.connection_string, module_ids[0]
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        self.cmd(
            "iot hub module-identity connection-string show -d {} -n {} -g {} -m {} --kt {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], "secondary"
            ),
            checks=[self.check_pattern("connectionString", mod_sym_conn_str_pattern)],
        )

        for i in module_ids:
            if module_ids.index(i) == (module_count - 1):
                # With connection string
                self.cmd(
                    "iot hub module-identity delete -d {} --login {} --module-id {}".format(
                        edge_device_ids[0], self.connection_string, i
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
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_hub_module_twins(self):
        self.kwargs["generic_dict"] = {"key": "value"}
        self.kwargs["bad_format"] = "{'key: 'value'}"
        self.kwargs["patch_desired"] = {"patchScenario": {"desiredKey": "desiredValue"}}
        self.kwargs["patch_tags"] = {"patchScenario": {"tagkey": "tagValue"}}

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
                edge_device_ids[0], self.connection_string, module_ids[0]
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.exists("properties.desired"),
                self.exists("properties.reported"),
            ],
        )

        # Patch based twin update of desired props
        self.cmd(
            "iot hub module-twin update -d {} -n {} -g {} -m {} --desired {}".format(
                edge_device_ids[0],
                LIVE_HUB,
                LIVE_RG,
                module_ids[0],
                '"{patch_desired}"',
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check(
                    "properties.desired.patchScenario",
                    self.kwargs["patch_desired"]["patchScenario"],
                ),
            ],
        )

        # Patch based twin update of tags with connection string
        self.cmd(
            "iot hub module-twin update -d {} --login {} -m {} --tags {}".format(
                edge_device_ids[0], self.connection_string, module_ids[0], '"{patch_tags}"'
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check(
                    "tags.patchScenario", self.kwargs["patch_tags"]["patchScenario"]
                ),
            ],
        )

        # Patch based twin update of desired + tags
        self.cmd(
            "iot hub module-twin update -d {} -n {} -m {} --desired {} --tags {}".format(
                device_ids[0],
                LIVE_HUB,
                module_ids[0],
                '"{patch_desired}"',
                '"{patch_tags}"',
            ),
            checks=[
                self.check("deviceId", device_ids[0]),
                self.check("moduleId", module_ids[0]),
                self.check(
                    "properties.desired.patchScenario",
                    self.kwargs["patch_desired"]["patchScenario"],
                ),
                self.check(
                    "tags.patchScenario",
                    self.kwargs["patch_tags"]["patchScenario"]
                ),
            ],
        )

        # Deprecated twin update style
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
                edge_device_ids[0], self.connection_string, module_ids[0], '"{generic_dict}"'
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
                edge_device_ids[0], self.connection_string, module_ids[0], '"{bad_format}"'
            ),
            expect_failure=True,
        )

        self.cmd(
            "iot hub module-twin update -d {} --login {} -m {} --set tags={}".format(
                edge_device_ids[0], self.connection_string, module_ids[0], '"{bad_format}"'
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
                edge_device_ids[0], self.connection_string, module_ids[0], content_path
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


class TestIoTStorage(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTStorage, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    @pytest.mark.skipif(
        not LIVE_STORAGE, reason="empty azext_iot_teststorageuri env var"
    )
    def test_storage(self):
        device_count = 1

        content_path = os.path.join(CWD, "test_generic_replace.json")
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
                device_ids[0], self.connection_string, content_path, "application/json"
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

    @pytest.mark.skipif(
        not LIVE_IDENTITY, reason="azext_iot_testidentity env var not set"
    )
    def test_identity_storage(self):
        # identity-based device-identity export
        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {}'.format(
                LIVE_HUB, LIVE_STORAGE, "identity"
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
            test_case, LIVE_HUB, LIVE_RG
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
            checks=self.is_empty(),
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
            expect_failure=True,
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
