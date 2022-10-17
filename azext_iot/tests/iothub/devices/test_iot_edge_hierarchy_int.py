# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.tests.iothub import IoTLiveScenarioTest


@pytest.mark.usefixtures("set_cwd")
class TestNestedEdgeHierarchy(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestNestedEdgeHierarchy, self).__init__(test_case)
        self.deployment_top = "./hierarchy_configs/deploymentTopLayer.json"
        self.deployment_lower = "./hierarchy_configs/deploymentLowerLayer.json"

    def test_nested_edge_hierarchy_nArgs_full(self):
        # ├── device_1 (toplayer)
        # │   ├── device_2
        # │   │   └── device_3 (lowerLayer)
        # │   └── device_4
        # │       ├── device_5 (lowerLayer)
        # │       └── device_6 (lowerLayer)
        # └── device_7 (toplayer)

        devices = [
            ("device1", None, self.deployment_top),
            ("device2", "device1", None),
            ("device3", "device2", self.deployment_lower),
            ("device4", "device1", None),
            ("device5", "device4", self.deployment_lower),
            ("device6", "device4", self.deployment_lower),
            ("device7", None, self.deployment_top),
        ]

        device_arg_string = self._generate_device_arg_string(devices)
        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} -c {device_arg_string}"
        )

        self._validate_results(devices)

    def test_nested_edge_hierarchy_nArgs_partial(self):
        # Partial 1
        # ├── device1 (toplayer)
        # │   ├── device2
        # │   │   └── device3 (lowerLayer)

        # Partial 2
        # │── device4 (toplayer)
        # │   ├── device5 (lowerLayer)
        # │   └── device6 (lowerLayer)

        partial_devices_primary = [
            ("device1", None, self.deployment_top),
            ("device2", "device1", None),
            ("device3", "device2", self.deployment_lower),
        ]

        partial_devices_secondary = [
            ("device4", None, self.deployment_top),
            ("device5", "device4", self.deployment_lower),
            ("device6", "device4", self.deployment_lower),
        ]

        # Clean on first run
        device_arg_string = self._generate_device_arg_string(partial_devices_primary)
        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} -c {device_arg_string}"
        )

        self._validate_results(partial_devices_primary)

        # Second run, no clean
        device_arg_string = self._generate_device_arg_string(partial_devices_secondary)
        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} {device_arg_string}"
        )
        # validate results on entire run
        full_device_list = partial_devices_primary + partial_devices_secondary
        self._validate_results(full_device_list)

    def test_nested_edge_hierarchy_config_full(self):
        # ├── device_1 (toplayer)
        # │   ├── device_2 (lowerLayer)
        # │   │   └── device_3 (lowerLayer)
        # │   └── device_4 (toplayer)
        # │       ├── device_5 (lowerLayer)
        # │       └── device_6 (lowerLayer)
        # └── device_7
        config_path = "./hierarchy_configs/nested_edge_config.yml"
        devices = [
            ("device_1", None, self.deployment_top),
            ("device_2", "device_1", self.deployment_lower),
            ("device_3", "device_2", self.deployment_lower),
            ("device_4", "device_1", self.deployment_top),
            ("device_5", "device_4", self.deployment_lower),
            ("device_6", "device_4", self.deployment_lower),
            ("device_7", None, None),
        ]

        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} -c --cfg {config_path}"
        )

        self._validate_results(devices)

    def test_nested_edge_hierarchy_config_partial(self):
        # Partial 1
        # ├── device_1 (toplayer)
        # │   ├── device_2 (lowerLayer)
        # │   │   └── device_3 (lowerLayer)
        # │   └── device_4 (toplayer)
        # │       ├── device_5 (lowerLayer)
        # │       └── device_6 (lowerLayer)
        # └── device_7

        # Partial 2
        # └── device_100 (toplayer)
        #     └── device_200
        #         └── device_300
        #             └── device_400 (lowerLayer)

        primary_config_path = "./hierarchy_configs/nested_edge_config.json"
        secondary_config_path = "./hierarchy_configs/nested_edge_config_secondary.yaml"
        devices_primary = [
            ("device_1", None, self.deployment_top),
            ("device_2", "device_1", self.deployment_lower),
            ("device_3", "device_2", self.deployment_lower),
            ("device_4", "device_1", self.deployment_top),
            ("device_5", "device_4", self.deployment_lower),
            ("device_6", "device_4", self.deployment_lower),
            ("device_7", None, None),
        ]
        devices_secondary = [
            ("device_100", None, self.deployment_top),
            ("device_200", "device_100", None),
            ("device_300", "device_200", None),
            ("device_400", "device_300", self.deployment_lower),
        ]
        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} -c --cfg {primary_config_path}"
        )

        self._validate_results(devices_primary)

        self.cmd(
            f"iot edge hierarchy create -n {self.entity_name} -g {self.entity_rg} --cfg {secondary_config_path}"
        )

        self._validate_results(devices_primary + devices_secondary)

    def _validate_results(self, devices):
        # get all devices in hub
        device_list = self.cmd(
            f"iot hub device-identity list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()
        # make sure all devices were created
        assert len(device_list) == len(devices)
        # validate each device
        for device_tuple in devices:
            device_id = device_tuple[0]
            device = self.cmd(
                f"iot hub device-identity show -d {device_id} -n {self.entity_name} -g {self.entity_rg}"
            ).get_output_in_json()
            assert device
            parent = device_tuple[1]
            if parent:
                # validate each device's parent is correct
                assert f"ms-azure-iot-edge://{parent}-" in device["parentScopes"][0]
            deployment = device_tuple[2]
            if deployment:
                checks = []

                if deployment == self.deployment_top:
                    checks.extend(
                        (
                            self.exists("properties.desired.modules.IoTEdgeAPIProxy"),
                            self.check(
                                "properties.desired.modules.IoTEdgeAPIProxy.env.BLOB_UPLOAD_ROUTE_ADDRESS.value",
                                "AzureBlobStorageonIoTEdge:11002",
                            ),
                        )
                    )
                if deployment == self.deployment_lower:
                    checks.extend(
                        (
                            self.exists(
                                "properties.desired.modules.simulatedTemperatureSensor"
                            ),
                            self.check(
                                "properties.desired.modules.simulatedTemperatureSensor.settings.image",
                                "$upstream:443/azureiotedge-simulated-temperature-sensor:1.0",
                            ),
                        )
                    )
                # get edgeAgent properties to check module configs
                self.cmd(
                    f"iot hub module-twin show -d {device_id} -n {self.entity_name} -g {self.entity_rg} -m $edgeAgent",
                    checks=checks,
                )

    def _generate_device_arg_string(self, devices):
        device_arg_string = ""
        for device_tuple in devices:
            device_id = device_tuple[0]
            parent_id = device_tuple[1]
            deployment = device_tuple[2]
            args = [f"id={device_id}"]
            if parent_id:
                args.append(f"parent={parent_id}")
            if deployment:
                args.append(f"deployment={deployment}")
            device_arg_string = f"{device_arg_string} --device {' '.join(args)}"
        return device_arg_string