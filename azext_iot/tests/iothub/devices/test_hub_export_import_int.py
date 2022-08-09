import random
import pytest
import json
import os
import time
from pathlib import Path
from azext_iot.common.shared import DeviceAuthApiType

from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.test_constants import ResourceTypes
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.utility import generate_key, read_file_content
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.helpers import add_test_tag
from azext_iot.tests.iothub import (
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
CWD = os.path.dirname(os.path.abspath(__file__))

# changing the order so the final exported file can be used for all import tests
# (the cstring output doesn't include the keys for the control plane features)
DATAPLANE_AUTH_TYPES = ["cstring", "key", "login"]


class TestHubExportImport(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestHubExportImport, self).__init__(test_case)
        self.dest_hub = settings.env.azext_iot_desthub or "test-hub-" + generate_generic_id()
        self.dest_hub_rg = settings.env.azext_iot_destrg or settings.env.azext_iot_testrg

        # create destination hub

        if not settings.env.azext_iot_desthub:
            self.create_hub(self.dest_hub, self.dest_hub_rg)

        add_test_tag(
            cmd=self.cmd,
            name=self.dest_hub,
            rg=self.dest_hub_rg,
            rtype=ResourceTypes.hub.value,
            test_tag=test_case
        )

        self.dest_hub_cstring = self.cmd(
            f"iot hub connection-string show -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).get_output_in_json()["connectionString"]

        self.filename = generate_generic_id() + ".json"

        self.create_hub_state()

    def create_hub_state(self):

        self.clean_up_hub(self.connection_string)

        # make an adm device configuration for the hub (applies to 0 devices, this is just to test the configuration settings)

        labels = {generate_generic_id() : generate_generic_id(), generate_generic_id() : generate_generic_id()}
        labels = json.dumps(labels)

        metrics_path = os.path.join(Path(CWD), "..", "configurations", "test_config_generic_metrics.json")
        content_path = os.path.join(Path(CWD), "..", "configurations", "test_adm_device_content.json")

        self.kwargs["config_content"] = read_file_content(content_path)
        self.kwargs["labels"] = labels
        self.kwargs["metrics"] = read_file_content(metrics_path)
        self.kwargs["target_condition"] = "tags.bar=12"

        self.cmd(
            "iot hub configuration create --config-id hubConfig1 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}'"
            " --target-condition '{}'".format(
                self.connection_string, "{config_content}", "{labels}", random.randint(1, 10), "{metrics}", "{target_condition}"
            )
        )

        # make an adm module configuration

        content_path = os.path.join(Path(CWD), "..", "configurations", "test_adm_module_content.json")
        self.kwargs["config_content"] = read_file_content(content_path)
        target_condition = "from devices.modules where tags.bar=12"

        self.cmd(
            "iot hub configuration create --config-id hubConfig2 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}'"
            " --target-condition '{}'".format(
                self.connection_string, "{config_content}", "{labels}", random.randint(1, 10), "{metrics}", target_condition
            )
        )

        # make a regular edge deployment

        deployment1_path = os.path.join(Path(CWD), "..", "configurations", "test_edge_deployment.json")
        self.kwargs["edge_content1"] = read_file_content(deployment1_path)
        self.cmd(
            "iot edge deployment create -d deployment1 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' "
            "--target-condition {}".format(
                self.connection_string, "{edge_content1}", "{labels}", random.randint(1, 10), "{metrics}", "{target_condition}"
            )
        )

        # make a layered edge deployment
        deployment2_path = os.path.join(Path(CWD), "..", "configurations", "test_edge_deployment_layered.json")
        self.kwargs["edge_content2"] = read_file_content(deployment2_path)
        self.cmd(
            "iot edge deployment create -d deployment2 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' "
            "--target-condition {} --layered".format(
                self.connection_string, "{edge_content1}", "{labels}", random.randint(1, 10), "{metrics}", "{target_condition}"
            )
        )

        # populate hub with devices

        for device_type in DEVICE_TYPES:
            device_count = 3
            device_ids = self.generate_device_names(
                device_count, edge=device_type == "edge"
            )
            edge_enabled = "--edge-enabled" if device_type == "edge" else ""

            # Create SAS-auth device and module
            custom_primary_key = generate_key()
            custom_secondary_key = generate_key()
            self.cmd(
                f"iot hub device-identity create -d {device_ids[0]} -l {self.connection_string} --pk {custom_primary_key} "
                f"--sk {custom_secondary_key} {edge_enabled}"
            )
            self.cmd(
                f"iot hub module-identity create -m deviceModule -d {device_ids[0]} -l {self.connection_string}"
            )

            # create x509_ca device and module
            self.cmd(
                f"iot hub device-identity create -d {device_ids[1]} -l {self.connection_string} --am x509_ca {edge_enabled}"
            )
            self.cmd(
                f"iot hub module-identity create -m deviceModule -d {device_ids[1]} -l {self.connection_string} --am x509_ca"
            )

            # create x509_thumbprint device and module
            self.cmd(
                f"iot hub device-identity create -d {device_ids[2]} -l {self.connection_string} --am x509_thumbprint "
                f"--ptp {PRIMARY_THUMBPRINT} --stp {SECONDARY_THUMBPRINT} {edge_enabled}"
            )
            ptp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
            stp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
            self.cmd(
                f"iot hub module-identity create -m deviceModule -d {device_ids[2]} -l {self.connection_string} "
                f"--am x509_thumbprint --ptp {ptp} --stp {stp}"
            )

            # add some children
            if edge_enabled:
                self.cmd(
                    f"iot hub device-identity children add -l {self.connection_string} -d {device_ids[0]} --cl {device_ids[1]}"
                )
                self.cmd(
                    f"iot hub device-identity children add -l {self.connection_string} -d {device_ids[1]} --cl {device_ids[2]}"
                )

            # add a property and a tag to each device's twin
            for i in range(len(device_ids)):
                device = device_ids[i]

                val = generate_generic_id()
                self.cmd(
                    f"iot hub device-twin update -d {device} -l {self.connection_string} --set properties.desired.testProp={val}"
                )

                patch_tags = {
                    generate_generic_id(): generate_generic_id(),
                    generate_generic_id(): generate_generic_id(),
                }

                self.kwargs["patch_tags"] = json.dumps(patch_tags)

                self.cmd(
                    f"iot hub device-twin update -d {device} -l {self.connection_string}"
                    " --tags '{patch_tags}'"
                )

                val = generate_generic_id()
                self.cmd(
                    f"iot hub module-twin update -d {device} -m deviceModule -l {self.connection_string} --set "
                    f"properties.desired.testProp={val}"
                )

                patch_tags = {
                    generate_generic_id(): generate_generic_id(),
                    generate_generic_id(): generate_generic_id(),
                }
                self.kwargs["patch_tags"] = json.dumps(patch_tags)

                self.cmd(
                    f"iot hub module-twin update -d {device} -m deviceModule -l {self.connection_string}"
                    " --tags '{patch_tags}'"
                )

    def compare_configs(self, configlist1, configlist2):
        assert(len(configlist1) == len(configlist2))

        for config in configlist1:
            target = None
            for c in configlist2:
                if c["id"] == config["id"]:
                    target = c
                    break

            assert target

            assert(config["id"] == target["id"])
            assert(config["content"] == target["content"])
            assert(config["metrics"] == target["metrics"])
            assert(config["priority"] == target["priority"])
            assert(config["systemMetrics"]["queries"] == target["systemMetrics"]["queries"])
            assert(config["targetCondition"] == target["targetCondition"])

    def compare_devices(self, device1, device2):

        assert(device1["authenticationType"] == device2["authenticationType"])
        assert(device1["capabilities"]["iotEdge"] == device2["capabilities"]["iotEdge"])
        assert(device1["connectionState"] == device2["connectionState"])
        assert(device1["status"] == device2["status"])

        if "tags" in device1:
            assert(device1["tags"] == device2["tags"])

        if device1["authenticationType"] == DeviceAuthApiType.sas.value:
            assert(device1["symmetricKey"]["primaryKey"] ==
                   device2["symmetricKey"]["primaryKey"])
            assert(device1["symmetricKey"]["secondaryKey"] ==
                   device2["symmetricKey"]["secondaryKey"])

        if device1["authenticationType"] == DeviceAuthApiType.selfSigned.value:
            assert(device1["x509Thumbprint"]["primaryThumbprint"] == device2["x509Thumbprint"]["primaryThumbprint"])
            assert(device1["x509Thumbprint"]["secondaryThumbprint"] == device2["x509Thumbprint"]["secondaryThumbprint"])

        assert(len(device1["properties"]["desired"]) == len(device2["properties"]["desired"]))

        for prop in device1["properties"]["desired"]:
            if prop not in ["$metadata", "$version"]:
                assert(prop in device2["properties"]["desired"])
                assert(device1["properties"]["desired"][prop] == device2["properties"]["desired"][prop])

    def compare_module_twins(self, twin1, twin2):
        assert(len(twin1["properties"]["desired"]) == len(twin2["properties"]["desired"]))
        for prop in twin1["properties"]["desired"]:
            if prop not in ["$metadata", "$version"]:
                assert(prop in twin2["properties"]["desired"])
                assert(twin1["properties"]["desired"][prop] == twin2["properties"]["desired"][prop])

        if "tags" in twin1:
            assert(twin1["tags"] == twin2["tags"])
        assert(twin1["status"] == twin2["status"])

    def compare_hubs(self):

        # compare configurations (there's only one)

        orig_hub_configs = self.cmd(
            f"iot hub configuration list -l {self.connection_string}"
        ).get_output_in_json()
        dest_hub_configs = self.cmd(
            f"iot hub configuration list -l {self.dest_hub_cstring}"
        ).get_output_in_json()
        self.compare_configs(orig_hub_configs, dest_hub_configs)

        # compare edge deployments

        orig_hub_deploys = self.cmd(
            f"iot edge deployment list -l {self.connection_string}"
        ).get_output_in_json()
        dest_hub_deploys = self.cmd(
            f"iot edge deployment list -l {self.dest_hub_cstring}"
        ).get_output_in_json()
        self.compare_configs(orig_hub_deploys, dest_hub_deploys)

        # compare devices

        orig_hub_identities = self.cmd(
            f"iot hub device-identity list -l {self.connection_string}"
        ).get_output_in_json()
        dest_hub_identities = self.cmd(
            f"iot hub device-identity list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        dest_hub_identities_dict = {}
        for id in dest_hub_identities:
            dest_hub_identities_dict[id["deviceId"]] = id

        assert(len(orig_hub_identities) == len(dest_hub_identities))

        for device in orig_hub_identities:
            assert device["deviceId"] in dest_hub_identities_dict
            target = dest_hub_identities_dict[device["deviceId"]]

            if device["authenticationType"] == DeviceAuthApiType.sas.value:
                id1 = self.cmd(
                    "iot hub device-identity show -l {} -d {}".format(self.connection_string, device['deviceId'])
                ).get_output_in_json()
                id2 = self.cmd(
                    "iot hub device-identity show -l {} -d {}".format(self.dest_hub_cstring, device['deviceId'])
                ).get_output_in_json()

                device["symmetricKey"] = id1["authentication"]["symmetricKey"]
                target["symmetricKey"] = id2["authentication"]["symmetricKey"]

            self.compare_devices(device, target)

            # compare modules

            orig_modules = self.cmd(
                "iot hub module-identity list -d {} -l {}".format(device['deviceId'], self.connection_string)
            ).get_output_in_json()
            dest_modules = self.cmd(
                "iot hub module-identity list -d {} -l {}".format(device['deviceId'], self.dest_hub_cstring)
            ).get_output_in_json()

            if device["capabilities"]["iotEdge"]:
                assert(len(orig_modules) == len(dest_modules) == 3)
            else:
                assert(len(orig_modules) == len(dest_modules) == 1)

            for module in orig_modules:
                target_module = None
                for mod in dest_modules:
                    if module["moduleId"] == mod["moduleId"]:
                        target_module = mod
                        break

                assert target_module

                assert(module["authentication"] == target_module["authentication"])

                module_twin = self.cmd(
                    f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {self.connection_string}"
                ).get_output_in_json()
                target_module_twin = self.cmd(
                    f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {self.dest_hub_cstring}"
                ).get_output_in_json()

                self.compare_module_twins(module_twin, target_module_twin)

            # compare children

            if device["capabilities"]["iotEdge"]:
                orig_children = self.cmd(
                    f"iot hub device-identity children list -d {device['deviceId']} -l {self.connection_string}"
                ).get_output_in_json()
                dest_children = self.cmd(
                    f"iot hub device-identity children list -d {device['deviceId']} -l {self.dest_hub_cstring}"
                ).get_output_in_json()

                assert(orig_children == dest_children)

    def compare_hub_to_file(self):
        with open(self.filename, 'r', encoding='utf-8') as f:
            hub_info = json.load(f)

        # compare configurations

        file_configs = hub_info["configurations"]
        hub_configs = self.cmd(
            f"iot hub configuration list -l {self.connection_string}"
        ).get_output_in_json()
        self.compare_configs(file_configs, hub_configs)

        # compare edge deployments

        file_deploys = hub_info["edgeDeployments"]
        hub_deploys = self.cmd(
            f"iot edge deployment list -l {self.connection_string}"
        ).get_output_in_json()
        self.compare_configs(file_deploys, hub_deploys)

        # compare devices

        file_devices = hub_info["devices"]["identities"]
        hub_devices = self.cmd(
            f"iot hub device-identity list -l {self.connection_string}"
        ).get_output_in_json()

        assert(len(file_devices) == len(hub_devices))
        for device in hub_devices:
            id = self.cmd(
                "iot hub device-identity show -l {} -d {}".format(self.connection_string, device['deviceId'])
            ).get_output_in_json()
            device["symmetricKey"] = id["authentication"]["symmetricKey"]

            target_device = None
            for d in file_devices:
                if device["deviceId"] == d["deviceId"]:
                    target_device = d
                    break

            assert target_device

            [device["properties"]["desired"].pop(key) for key in ["$metadata", "$version"]]
            self.compare_devices(device, target_device)

            file_modules = hub_info["modules"][device["deviceId"]]
            hub_modules = self.cmd(
                "iot hub module-identity list -d {} -l {}".format(device["deviceId"], self.connection_string)
            ).get_output_in_json()

            # edge devices have two default modules that aren't saved to the file
            if device["capabilities"]["iotEdge"]:
                assert(len(file_modules) == len(hub_modules) - 2)
            else:
                assert(len(file_modules) == len(hub_modules))

            for module in hub_modules:
                if module['moduleId'] in ["$edgeAgent", "$edgeHub"]:
                    continue

                module_twin = self.cmd(
                    f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {self.connection_string}"
                ).get_output_in_json()

                target_module = None
                for mod in file_modules:
                    if module["moduleId"] == mod[0]["module_id"]:
                        target_module = mod[0]
                        target_module_twin = mod[1]
                        break

                assert target_module

                assert(module["authentication"] == target_module["authentication"])

                [module_twin["properties"]["desired"].pop(key) for key in ["$metadata", "$version"]]
                self.compare_module_twins(module_twin, target_module_twin)

            # compare children
            if device["capabilities"]["iotEdge"]:
                file_children = hub_info["devices"]["children"][device["deviceId"]]
                dest_children = self.cmd(
                    f"iot hub device-identity children list -d {device['deviceId']} -l {self.connection_string}"
                ).get_output_in_json()

                assert(file_children == dest_children)

    def clean_up_hub(self, cstring):

        dest_hub_configs = self.cmd(
            f"iot hub configuration list -l {cstring}"
        ).get_output_in_json()

        dest_hub_deploys = self.cmd(
            f"iot edge deployment list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        for config in dest_hub_configs + dest_hub_deploys:
            self.cmd(
                "iot hub configuration delete -c {} -l {}".format(config["id"], cstring)
            )

        dest_hub_identities = self.cmd(
            f"iot hub device-identity list -l {cstring}"
        ).get_output_in_json()

        for id in dest_hub_identities:
            self.cmd(
                "iot hub device-identity delete -d {} -l {}".format(id["deviceId"], cstring)
            )

        # gives the api enough time to update
        time.sleep(1)

    @pytest.fixture(scope="class", autouse=True)
    def teardown_module(self):
        yield

        if os.path.isfile(self.filename):
            os.remove(self.filename)

        # tears down destination hub
        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete -n {} -g {}".format(self.dest_hub, self.dest_hub_rg))
        else:
            self.clean_up_hub(self.dest_hub_cstring)

    # @pytest.mark.skip(reason="no way of currently testing this")
    def test_export_import(self):

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub state export -n {self.entity_name} -f {self.filename} -g {self.entity_rg} --force",
                    auth_type=auth_phase
                )
            )
            time.sleep(2)
            self.compare_hub_to_file()

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.clean_up_hub(self.connection_string)
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub state import -n {self.entity_name} -f {self.filename} -g {self.entity_rg} -r",
                    auth_type=auth_phase
                )
            )
            time.sleep(2)  # gives the hub time to update before the checks
            self.compare_hub_to_file()

    # @pytest.mark.skip(reason="no way of currently testing this")
    def test_migrate(self):

        for auth_phase in DATAPLANE_AUTH_TYPES:
            if auth_phase == "cstring":
                self.cmd(
                    f"iot hub state migrate --origin-hub-login {self.connection_string} --destination-hub-login "
                    f"{self.dest_hub_cstring} -r"
                )
            else:
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub state migrate --origin-hub {self.entity_name} --origin-resource-group {self.entity_rg} "
                        f"--destination-hub {self.dest_hub} --destination-resource-group {self.dest_hub_rg} -r",
                        auth_type=auth_phase
                    )
                )

            time.sleep(2)  # gives the hub time to update before the checks
            self.compare_hubs()
            self.clean_up_hub(self.dest_hub_cstring)
