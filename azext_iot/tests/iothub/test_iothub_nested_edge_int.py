# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests import IoTLiveScenarioTest
from ..settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg


class TestIoTNestedEdge(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTNestedEdge, self).__init__(
            test_case, LIVE_HUB, LIVE_RG
        )

    def test_nested_edge(self):
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

        # get parent of edge device
        self.cmd(
            "iot hub device-identity parent show -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # get parent of device which doesn't have any parent set
        self.cmd(
            "iot hub device-identity parent show -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting non-edge device as a parent of non-edge device
        self.cmd(
            "iot hub device-identity parent set -d {} --pd {} -n {} -g {}".format(
                device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting edge device as a parent of edge device
        self.cmd(
            "iot hub device-identity parent set -d {} --pd {} -n {} -g {}".format(
                edge_device_ids[0], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # add device as a child of non-edge device
        self.cmd(
            "iot hub device-identity children add -d {} --child-list {} -n {} -g {}".format(
                device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add device list as children of edge device
        self.cmd(
            "iot hub device-identity children add -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], " ".join(device_ids), LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # setting edge device as a parent of non-edge device which already having different parent device
        self.cmd(
            "iot hub device-identity parent set -d {} --pd {} -n {} -g {}".format(
                device_ids[2], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # setting edge device as a parent of non-edge device which already having different parent device by force
        self.cmd(
            "iot hub device-identity parent set -d {} --pd {} -n {} -g {} --force".format(
                device_ids[2], edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # get parent of device
        self.cmd(
            "iot hub device-identity parent show -d {} -n {} -g {}".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[
                self.check("deviceId", edge_device_ids[0]),
                self.exists("deviceScope"),
            ],
        )

        # add same device as a child of same parent device
        self.cmd(
            "iot hub device-identity children add -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add same device as a child of another edge device
        self.cmd(
            "iot hub device-identity children add -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # add same device as a child of another edge device by force
        self.cmd(
            "iot hub device-identity children add -d {} --child-list {} -n {} -g {} --force".format(
                edge_device_ids[1], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # list child devices of edge device
        output = self.cmd(
            "iot hub device-identity children list -d {} -n {} -g {}".format(
                edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=False,
        )

        assert output.get_output_in_json() == [device_ids[1]]

        # removing all child devices of non-edge device
        self.cmd(
            "iot hub device-identity children remove -d {} -n {} -g {} --remove-all".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove all child devices from edge device
        self.cmd(
            "iot hub device-identity children remove -d {} -n {} -g {} --remove-all".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # removing all child devices of edge device which doesn't have any child devices
        self.cmd(
            "iot hub device-identity children remove -d {} -n {} -g {} --remove-all".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # removing child devices of edge device neither passing child devices list nor remove-all parameter
        self.cmd(
            "iot hub device-identity children remove -d {} -n {} -g {}".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove edge device from edge device
        self.cmd(
            "iot hub device-identity children remove -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], edge_device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove device from edge device but device is a child of another edge device
        self.cmd(
            "iot hub device-identity children remove -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[1], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # remove device
        self.cmd(
            "iot hub device-identity children remove -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[1], LIVE_HUB, LIVE_RG
            ),
            checks=self.is_empty(),
        )

        # remove device which doesn't have any parent set
        self.cmd(
            "iot hub device-identity children remove -d {} --child-list {} -n {} -g {}".format(
                edge_device_ids[0], device_ids[0], LIVE_HUB, LIVE_RG
            ),
            expect_failure=True,
        )

        # list child devices of edge device which doesn't have any children
        output = self.cmd(
            "iot hub device-identity children list -d {} -n {} -g {}".format(
                edge_device_ids[1], LIVE_HUB, LIVE_RG
            ),
            expect_failure=False,
        )

        assert output.get_output_in_json() == []
