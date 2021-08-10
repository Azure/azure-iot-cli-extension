# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from time import sleep

# TODO: assert device scope format in device twin.
# from azext_iot.constants import DEVICE_DEVICESCOPE_PREFIX


class TestIoTHubNestedEdge(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubNestedEdge, self).__init__(test_case)

    def test_iothub_nested_edge(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            device_count = 3
            device_ids = self.generate_device_names(device_count)
            edge_device_count = 2
            edge_device_ids = self.generate_device_names(edge_device_count)

            for edge_device_id in edge_device_ids:
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create -d {edge_device_id} -n {self.entity_name} -g {self.entity_rg} --ee",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("capabilities.iotEdge", True),
                        self.exists("deviceScope"),
                    ],
                )

            for device_id in device_ids:
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create -d {device_id} -n {self.entity_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("capabilities.iotEdge", False),
                        self.check("deviceScope", None),
                    ],
                )

            # Error - Get parent of edge device with no initial parent
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent show -d {edge_device_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - Get parent of device which does not have any parent set
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent show -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - Set non-edge device as a parent of a non-edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent set "
                    f"-d {device_ids[0]} --pd {device_ids[1]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Set edge device as a parent of an edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent set -d {edge_device_ids[0]} --pd {edge_device_ids[1]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # Error - Add device as a child of a non-edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children add -d {device_ids[0]} --child-list {device_ids[1]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Add a space separated list of devices as children of an edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children add -d {edge_device_ids[0]} --child-list {' '.join(device_ids)} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # Error - setting edge device as a parent of non-edge device which already having different parent device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent set "
                    f"-d {device_ids[2]} --pd {edge_device_ids[1]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Setting edge device as a parent of non-edge device which already having different parent device by force
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent set -d {device_ids[2]} --pd {edge_device_ids[1]} "
                    f"-n {self.entity_name} -g {self.entity_rg} --force",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # Get parent of device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity parent show -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("deviceId", edge_device_ids[0]),
                    self.exists("deviceScope"),
                ],
            )

            # Error - add same device as a child of same parent device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children add -d {edge_device_ids[0]} --child-list {device_ids[0]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - add same device as a child of another edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children add -d {edge_device_ids[1]} --child-list {device_ids[0]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Add same device as a child of another edge device by force
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children add -d {edge_device_ids[1]} --child-list {device_ids[0]} "
                    f"-n {self.entity_name} -g {self.entity_rg} --force",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # List child devices of edge device
            output = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children list -d {edge_device_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                )
            )
            assert output.get_output_in_json() == [device_ids[1]]

            # Error - Remove all child devices of non-edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove "
                    f"-d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} --remove-all",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Remove all child devices from edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove "
                    f"-d {edge_device_ids[1]} -n {self.entity_name} -g {self.entity_rg} --remove-all",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # Wait for child devices to be removed to prevent failures
            sleep(30)

            # Error - remove all child devices of edge device which does not have any child devices
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove "
                    f"-d {edge_device_ids[1]} -n {self.entity_name} -g {self.entity_rg} --remove-all",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - remove child device of edge device neither passing child devices list nor remove-all parameter
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove -d {edge_device_ids[1]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - remove edge device from edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove -d {edge_device_ids[1]} --child-list {edge_device_ids[0]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Error - remove device from edge device but device is a child of another edge device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove -d {edge_device_ids[1]} --child-list {device_ids[1]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # Remove device
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove -d {edge_device_ids[0]} --child-list {device_ids[1]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=self.is_empty(),
            )

            # Error - remove device which does not have any parent set
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children remove -d {edge_device_ids[0]} --child-list {device_ids[0]} "
                    f"-n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            # List child devices of edge device which doesn't have any children
            output = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity children list -d {edge_device_ids[1]} -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                )
            )
            assert output.get_output_in_json() == []
