# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, NamedTuple, Optional
import pytest
import tarfile
from shutil import rmtree
from os.path import exists
from azext_iot.tests.iothub import IoTLiveScenarioTest


class EdgeDevicesTestConfig(NamedTuple):
    id: str
    parent: str
    deployment: str
    hostname: Optional[str]
    edge_agent: Optional[str]


@pytest.mark.usefixtures("set_cwd")
class TestNestedEdgeHierarchy(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestNestedEdgeHierarchy, self).__init__(test_case)
        self.deployment_top = "./device_configs/deployments/deploymentTopLayer.json"
        self.deployment_lower = "./device_configs/deployments/deploymentLowerLayer.json"

        self.deployment_top_config = "./deployments/deploymentTopLayer.json"
        self.deployment_lower_config = "./deployments/deploymentLowerLayer.json"

    def test_nested_edge_devices_create_nArgs_full(self):
        # ├── device_1 (toplayer)
        # │   ├── device_2
        # │   │   └── device_3 (lowerLayer)
        # │   └── device_4
        # │       ├── device_5 (lowerLayer)
        # │       └── device_6 (lowerLayer)
        # └── device_7 (toplayer)

        devices: List[EdgeDevicesTestConfig] = [
            EdgeDevicesTestConfig("device1", None, self.deployment_top, None, None),
            EdgeDevicesTestConfig("device2", "device1", None, None, None),
            EdgeDevicesTestConfig(
                "device3", "device2", self.deployment_lower, None, None
            ),
            EdgeDevicesTestConfig("device4", "device1", None, None, None),
            EdgeDevicesTestConfig(
                "device5", "device4", self.deployment_lower, None, None
            ),
            EdgeDevicesTestConfig(
                "device6", "device4", self.deployment_lower, None, None
            ),
            EdgeDevicesTestConfig("device7", None, self.deployment_top, None, None),
        ]

        device_arg_string = self._generate_device_arg_string(devices)
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y {device_arg_string} "
            "--out bundles --device-auth x509_thumbprint"
        )

        self._validate_results(devices, "bundles", True)

    def test_nested_edge_devices_create_nArgs_partial(self):
        # Partial 1
        # ├── device1 (toplayer)
        # │   ├── device2
        # │   │   └── device3 (lowerLayer)

        # Partial 2
        # │── device4 (toplayer)
        # │   ├── device5 (lowerLayer)
        # │   └── device6 (lowerLayer)

        partial_devices_primary = [
            EdgeDevicesTestConfig("device1", None, self.deployment_top, None, None),
            EdgeDevicesTestConfig("device2", "device1", None, None, None),
            EdgeDevicesTestConfig(
                "device3", "device2", self.deployment_lower, None, None
            ),
        ]

        partial_devices_secondary = [
            EdgeDevicesTestConfig("device4", None, self.deployment_top, None, None),
            EdgeDevicesTestConfig(
                "device5", "device4", self.deployment_lower, None, None
            ),
            EdgeDevicesTestConfig(
                "device6", "device4", self.deployment_lower, None, None
            ),
        ]

        # Clean on first run
        device_arg_string = self._generate_device_arg_string(partial_devices_primary)
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y {device_arg_string} --out primary"
        )

        self._validate_results(partial_devices_primary, "primary")

        # Second run, no clean
        device_arg_string = self._generate_device_arg_string(partial_devices_secondary)
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} {device_arg_string}"
        )
        # validate results on entire run
        full_device_list = partial_devices_primary + partial_devices_secondary
        self._validate_results(full_device_list, None)

    def test_nested_edge_devices_create_config_full(self):
        # ├── device_1 (toplayer)
        # │   ├── device_2 (lowerLayer)
        # │   │   └── device_3 (lowerLayer)
        # │   └── device_4 (toplayer)
        # │       ├── device_5 (lowerLayer)
        # │       └── device_6 (lowerLayer)
        # └── device_7
        config_path = "./device_configs/nested_edge_config.yml"
        devices: List[EdgeDevicesTestConfig] = [
            EdgeDevicesTestConfig(
                "device_1",
                None,
                self.deployment_top_config,
                "device_1",
                "mcr.microsoft.com/azureiotedge-agent:1.1",
            ),
            EdgeDevicesTestConfig(
                "device_2", "device_1", self.deployment_lower_config, "device_2", None
            ),
            EdgeDevicesTestConfig(
                "device_3", "device_2", self.deployment_lower_config, "device_3", None
            ),
            EdgeDevicesTestConfig(
                "device_4", "device_1", self.deployment_top_config, "device_4", None
            ),
            EdgeDevicesTestConfig(
                "device_5", "device_4", self.deployment_lower_config, "device_5", None
            ),
            EdgeDevicesTestConfig(
                "device_6", "device_4", self.deployment_lower_config, "device_6", None
            ),
            EdgeDevicesTestConfig(
                "device_7",
                None,
                None,
                "device_7",
                "mcr.microsoft.com/azureiotedge-agent:1.2",
            ),
        ]

        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y --cfg {config_path} "
            "--out device_bundles --device-auth x509_thumbprint"
        )

        self._validate_results(devices, "device_bundles", True)

    def test_nested_edge_devices_create_config_partial(self):
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

        primary_config_path = "./device_configs/nested_edge_config.json"
        secondary_config_path = "./device_configs/nested_edge_config_secondary.yaml"
        devices_primary = [
            EdgeDevicesTestConfig(
                "device_1", None, self.deployment_top_config, None, None
            ),
            EdgeDevicesTestConfig(
                "device_2", "device_1", self.deployment_lower_config, None, None
            ),
            EdgeDevicesTestConfig(
                "device_3", "device_2", self.deployment_lower_config, None, None
            ),
            EdgeDevicesTestConfig(
                "device_4", "device_1", self.deployment_top_config, None, None
            ),
            EdgeDevicesTestConfig(
                "device_5", "device_4", self.deployment_lower_config, None, None
            ),
            EdgeDevicesTestConfig(
                "device_6", "device_4", self.deployment_lower_config, None, None
            ),
            EdgeDevicesTestConfig("device_7", None, None, None, None),
        ]
        devices_secondary = [
            EdgeDevicesTestConfig(
                "device_100", None, self.deployment_top_config, None, None
            ),
            EdgeDevicesTestConfig("device_200", "device_100", None, None, None),
            EdgeDevicesTestConfig("device_300", "device_200", None, None, None),
            EdgeDevicesTestConfig(
                "device_400", "device_300", self.deployment_lower_config, None, None
            ),
        ]
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y --cfg {primary_config_path} --out output"
        )

        self._validate_results(devices_primary, "output")

        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} --cfg {secondary_config_path}"
        )

        self._validate_results(devices_primary + devices_secondary, None)

    def test_edge_devices_nArgs_flat_no_output(self):
        devices: List[EdgeDevicesTestConfig] = [
            EdgeDevicesTestConfig("device1", None, self.deployment_top, None, None),
            EdgeDevicesTestConfig("device2", None, None, None, None),
            EdgeDevicesTestConfig("device3", None, self.deployment_lower, None, None),
            EdgeDevicesTestConfig("device4", None, None, None, None),
            EdgeDevicesTestConfig("device5", None, self.deployment_lower, None, None),
            EdgeDevicesTestConfig("device6", None, self.deployment_lower, None, None),
            EdgeDevicesTestConfig("device7", None, self.deployment_top, None, None),
        ]

        device_arg_string = self._generate_device_arg_string(devices)
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y {device_arg_string}"
        )

        self._validate_results(devices, None)

    def test_edge_devices_create_config_overrides(self):
        config_path = "./device_configs/edge_devices_min_config.yml"
        override_auth_type = "shared_private_key"
        default_edge_agent = "mcr.microsoft.com/azureiotedge-agent:1.3"
        config_template = "./device_configs/device_config.toml"
        devices: List[EdgeDevicesTestConfig] = [
            EdgeDevicesTestConfig(
                "device_1", None, None, None, "mcr.microsoft.com/azureiotedge-agent:1.2"
            ),
            EdgeDevicesTestConfig(
                "device_2", "device_1", None, None, default_edge_agent
            ),
            EdgeDevicesTestConfig(
                "device_3",
                "device_1",
                None,
                None,
                "mcr.microsoft.com/azureiotedge-agent:1.4",
            ),
            EdgeDevicesTestConfig("device_4", None, None, None, default_edge_agent),
        ]

        # file has cert auth, call with overrides: keyAuth, custom config path, default edge agent
        self.cmd(
            f"iot edge devices create -n {self.entity_name} -g {self.entity_rg} -c -y --cfg {config_path} --dct {config_template}"
            f" --out device_bundles --device-auth {override_auth_type} --default-edge-agent {default_edge_agent}"
        )

        self._validate_results(
            devices, "device_bundles", cert_auth=False, custom_device_template=True
        )

    def _validate_results(
        self,
        devices: List[EdgeDevicesTestConfig],
        output_path: str,
        cert_auth: bool = False,
        custom_device_template: bool = False,
    ):
        # get all devices in hub
        device_list = self.cmd(
            f"iot hub device-identity list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()
        # make sure all devices were created
        assert len(device_list) == len(devices)
        # validate each device
        for device_tuple in devices:
            device_id = device_tuple.id
            device = self.cmd(
                f"iot hub device-identity show -d {device_id} -n {self.entity_name} -g {self.entity_rg}"
            ).get_output_in_json()
            assert device
            parent = device_tuple.parent
            if parent:
                # validate each device's parent is correct
                assert f"ms-azure-iot-edge://{parent}-" in device["parentScopes"][0]
            deployment = device_tuple.deployment
            if deployment:
                checks = []

                if deployment in [self.deployment_top, self.deployment_top_config]:
                    checks.extend(
                        (
                            self.exists("properties.desired.modules.IoTEdgeAPIProxy"),
                            self.check(
                                "properties.desired.modules.IoTEdgeAPIProxy.env.BLOB_UPLOAD_ROUTE_ADDRESS.value",
                                "AzureBlobStorageonIoTEdge:11002",
                            ),
                        )
                    )
                if deployment in [self.deployment_lower, self.deployment_lower_config]:
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
            # check output if specified
            if output_path:
                # untar target device bundle
                bundle_file = f"{output_path}/{device_id}.tgz"
                assert exists(bundle_file)
                with tarfile.open(bundle_file, "r:gz") as device_tar:

                    # check device bundle files
                    file_names = device_tar.getnames()
                    for item in [
                        f"{device_id}.cert.pem",
                        f"{device_id}.key.pem",
                        f"{device_id}.full-chain.cert.pem",
                        "iotedge_config_cli_root.pem",
                        "config.toml",
                        "install.sh",
                        "README.md",
                    ]:
                        assert item in file_names
                    assert cert_auth == (f"{device_id}.hub-auth-cert.pem" in file_names)
                    assert cert_auth == (f"{device_id}.hub-auth-key.pem" in file_names)
                    # check config values
                    config_toml = device_tar.extractfile("config.toml")
                    import tomli

                    config = tomli.load(config_toml)

                    # auth type
                    assert config["provisioning"]["authentication"]["method"] == (
                        "x509" if cert_auth else "sas"
                    )
                    # hub hostname
                    assert (
                        config["provisioning"]["iothub_hostname"]
                        == f"{self.entity_name}.azure-devices.net"
                    )
                    # device_id
                    assert config["provisioning"]["device_id"] == device_id
                    # device hostname
                    hostname = getattr(device_tuple, "hostname", None)
                    if hostname:
                        assert config["hostname"] == hostname
                    # edge agent
                    agent = getattr(device_tuple, "edge_agent", None)
                    if agent:
                        assert config["agent"]["config"]["image"] == agent
                    # hacky way to ensure we're loading config from file
                    if custom_device_template:
                        assert config["test"]["foo"] == "bar"

        if output_path:
            rmtree(output_path)

    def _generate_device_arg_string(self, devices: List[EdgeDevicesTestConfig]):
        device_arg_string = ""
        for device_tuple in devices:
            device_id = device_tuple.id
            parent_id = device_tuple.parent
            deployment = device_tuple.deployment
            hostname = getattr(device_tuple, "hostname", None)
            edge_agent = getattr(device_tuple, "edge_agent", None)
            args = [f"id={device_id}"]
            if parent_id:
                args.append(f"parent={parent_id}")
            if deployment:
                args.append(f"deployment={deployment}")
            if hostname:
                args.append(f"hostname={hostname}")
            if edge_agent:
                args.append(f"edgeAgent={edge_agent}")
            device_arg_string = f"{device_arg_string} --device {' '.join(args)}"
        return device_arg_string
