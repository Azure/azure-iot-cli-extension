import random
import json
import os
import time
from azext_iot.common.shared import DeviceAuthApiType

from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.utility import generate_key
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.iothub import (
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)


class TestHubExportImport(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestHubExportImport, self).__init__(test_case)
        self.dest_hub = settings.env.azext_iot_desthub or "test-hub-" + generate_generic_id()
        self.dest_hub_rg = settings.env.azext_iot_destrg or settings.env.azext_iot_testrg

        # create destination hub

        if not settings.env.azext_iot_desthub:
            self.create_hub(self.dest_hub, self.entity_rg)

        self.dest_hub_cstring = self.cmd(
            "iot hub connection-string show -n {} -g {}".format(self.dest_hub, self.dest_hub_rg)
        ).get_output_in_json()["connectionString"]

        self.filename = generate_generic_id() + ".json"

        self.create_hub_state()

    def create_hub_state(self):

        # make a configuration for the hub (applies to 0 devices, this is just to test the configuration settings)

        config_content = {"deviceContent" : {
            "properties.desired.propFromConfig" : generate_generic_id()
        }}
        config_content = json.dumps(config_content)

        labels = {generate_generic_id() : generate_generic_id(), generate_generic_id() : generate_generic_id()}
        labels = json.dumps(labels)

        priority = random.randint(1, 10)

        metrics = {"metrics": {
            "queries": {
                "mymetric": "SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200"
            }
        }}
        metrics = json.dumps(metrics)

        self.kwargs["config_content"] = config_content
        self.kwargs["labels"] = labels
        self.kwargs["metrics"] = metrics

        self.cmd("iot hub configuration create --config-id {} -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' \
            --target-condition {}"
            .format("hubConfig", self.connection_string, "{config_content}", "{labels}", priority, "{metrics}", "tags.bar=12"))

        # populate hub with devices

        for device_type in DEVICE_TYPES:
            device_count = 3
            device_ids = self.generate_device_names(
                device_count, edge=device_type == "edge"
            )
            edge_enabled = "--edge-enabled" if device_type == "edge" else ""

            # Create SAS-auth device
            custom_primary_key = generate_key()
            custom_secondary_key = generate_key()
            self.cmd(
                f"iot hub device-identity create -d {device_ids[0]} -l {self.connection_string} --pk {custom_primary_key} \
                    --sk {custom_secondary_key} {edge_enabled}"
            )

            # create x509_ca device
            self.cmd(
                f"iot hub device-identity create -d {device_ids[1]} -l {self.connection_string} --am x509_ca {edge_enabled}"
            )

            # create x509_thumbprint device
            self.cmd(
                f"iot hub device-identity create -d {device_ids[2]} -l {self.connection_string} --am x509_thumbprint \
                    --ptp {PRIMARY_THUMBPRINT} --stp {SECONDARY_THUMBPRINT} {edge_enabled}"
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

                # make a module for each device, same authentication method as device

                if(i == 0):
                    self.cmd("iot hub module-identity create -d {} -m deviceModule -l {} ".format(device, self.connection_string))

                elif(i == 1):
                    self.cmd("iot hub module-identity create -d {} -m deviceModule -l {} --am x509_ca"
                        .format(device, self.connection_string))

                elif(i == 2):
                    ptp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
                    stp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]

                    self.cmd("iot hub module-identity create -d {} -m deviceModule -l {} --am x509_thumbprint --ptp {} --stp {}"
                        .format(device, self.connection_string, ptp, stp))

                # add a property and a tag to each module's twin

                val = generate_generic_id()
                self.cmd(
                    f"iot hub module-twin update -d {device} -m deviceModule -l {self.connection_string} --set \
                        properties.desired.testProp={val}"
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

    def compare_configs(self, config1, config2):

        assert(config1["id"] == config2["id"])
        assert(config1["content"] == config2["content"])
        assert(config1["metrics"] == config2["metrics"])
        assert(config1["priority"] == config2["priority"])
        assert(config1["systemMetrics"]["queries"] == config2["systemMetrics"]["queries"])
        assert(config1["targetCondition"] == config2["targetCondition"])

    def compare_devices(self, device1, device2):

        assert (device1["authenticationType"] == device2["authenticationType"])
        assert (device1["capabilities"]["iotEdge"] == device2["capabilities"]["iotEdge"])
        assert (device1["connectionState"] == device2["connectionState"])
        assert (device1["status"] == device2["status"])

        if("tags" in device1.keys()):
            assert (device1["tags"] == device2["tags"])

        if(device1["authenticationType"] == DeviceAuthApiType.sas.value):
            id1 = self.cmd("iot hub device-identity show -l {} -d {}".format(self.connection_string, device1['deviceId'])) \
                .get_output_in_json()
            id2 = self.cmd("iot hub device-identity show -l {} -d {}".format(self.dest_hub_cstring, device1['deviceId'])) \
                .get_output_in_json()
            assert (id1["authentication"]["symmetricKey"]["primaryKey"] == id2["authentication"]["symmetricKey"]["primaryKey"])
            assert (id1["authentication"]["symmetricKey"]["secondaryKey"] == \
                id2["authentication"]["symmetricKey"]["secondaryKey"])

        if(device1["authenticationType"] == DeviceAuthApiType.selfSigned.value):
            assert (device1["x509Thumbprint"]["primaryThumbprint"] == device2["x509Thumbprint"]["primaryThumbprint"])
            assert (device1["x509Thumbprint"]["secondaryThumbprint"] == device2["x509Thumbprint"]["secondaryThumbprint"])

        assert (len(device1["properties"]["desired"]) == len(device2["properties"]["desired"]))

        for prop in device1["properties"]["desired"]:
            if(prop != "$metadata" and prop != "$version"):
                assert (prop in device2["properties"]["desired"])
                assert (device1["properties"]["desired"][prop] == device2["properties"]["desired"][prop])

        # compare modules

        orig_modules = self.cmd(
            "iot hub module-identity list -d {} -l {}".format(device1['deviceId'], self.connection_string)
        ).get_output_in_json()
        dest_modules = self.cmd(
            "iot hub module-identity list -d {} -l {}".format(device1['deviceId'], self.dest_hub_cstring)
        ).get_output_in_json()

        if(device1["capabilities"]["iotEdge"]):
            assert (len(orig_modules) == len(dest_modules) == 3)
        else:
            assert (len(orig_modules) == len(dest_modules) == 1)

        for module in orig_modules:
            target_module = None
            for mod in dest_modules:
                if(module["moduleId"] == mod["moduleId"]):
                    target_module = mod
                    break

            assert target_module

            assert (module["authentication"] == target_module["authentication"])

            module_twin = self.cmd(
                f"iot hub module-twin show -m {module['moduleId']} -d {device1['deviceId']} -l {self.connection_string}"
            ).get_output_in_json()
            target_module_twin = self.cmd(
                f"iot hub module-twin show -m {module['moduleId']} -d {device1['deviceId']} -l {self.dest_hub_cstring}"
            ).get_output_in_json()

            assert (len(module_twin["properties"]["desired"]) == len(target_module_twin["properties"]["desired"]))
            for prop in module_twin["properties"]["desired"]:
                if(prop != "$metadata" and prop != "version"):
                    assert (prop in target_module_twin["properties"]["desired"])
                    assert (module_twin["properties"]["desired"][prop] == target_module_twin["properties"]["desired"][prop])

            if("tags" in module_twin.keys()):
                assert (module_twin["tags"] == target_module_twin["tags"])
            assert (module_twin["status"] == target_module_twin["status"])

    def compare_hubs(self):

        # compare configurations (there's only one)

        orig_hub_configs = self.cmd(
            f"iot hub configuration list -l {self.connection_string}"
        ).get_output_in_json()

        dest_hub_configs = self.cmd(
            f"iot hub configuration list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        assert(len(orig_hub_configs) == len(dest_hub_configs) == 1)

        self.compare_configs(orig_hub_configs[0], dest_hub_configs[0])

        # compare devices

        orig_hub_identities = self.cmd(
            f"iot hub device-identity list -l {self.connection_string}"
        ).get_output_in_json()
        dest_hub_identities = self.cmd(
            f"iot hub device-identity list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        for device in orig_hub_identities:
            target = None
            for id in dest_hub_identities:
                if(device["deviceId"] == id["deviceId"]):
                    target = id
                    break

            assert target

            self.compare_devices(device, target)

    def clean_up_dest_hub(self):

        dest_hub_configs = self.cmd(
            f"iot hub configuration list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        for config in dest_hub_configs:
            self.cmd(
                "iot hub configuration delete -c {} -l {}".format(config["id"], self.dest_hub_cstring)
            )

        dest_hub_identities = self.cmd(
            f"iot hub device-identity list -l {self.dest_hub_cstring}"
        ).get_output_in_json()

        for id in dest_hub_identities:
            self.cmd(
                "iot hub device-identity delete -d {} -l {}".format(id["deviceId"], self.dest_hub_cstring)
            )

        # gives the api enough time to update
        time.sleep(1)

    def test_import_export(self):

        # auth-type = key (default)

        self.cmd(
            f"iot hub state export -n {self.entity_name} -f {self.filename} -g {self.entity_rg}"
        )
        self.cmd(
            f"iot hub state import -n {self.dest_hub} -f {self.filename} -g {self.dest_hub_rg} -r"
        )
        self.compare_hubs()
        self.clean_up_dest_hub()

        # auth-type = login

        self.cmd(
            f"iot hub state export -n {self.entity_name} -f {self.filename} -g {self.entity_rg} --auth-type login"
        )
        self.cmd(
            f"iot hub state import -n {self.dest_hub} -f {self.filename} -g {self.dest_hub_rg} --auth-type login -r"
        )
        self.compare_hubs()
        self.clean_up_dest_hub()

        # connection string

        self.cmd(
            f"iot hub state export -f {self.filename} -l {self.connection_string}"
        )
        self.cmd(
            f"iot hub state import -f {self.filename} -l {self.dest_hub_cstring} -r"
        )
        self.compare_hubs()

        os.remove(self.filename)
        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete -n {} -g {}".format(self.dest_hub, self.dest_hub_rg))
        else:
            self.clean_up_dest_hub()

    def test_migrate(self):

        # auth-type = key (default)

        self.cmd(
            f"iot hub state migrate --origin-hub {self.entity_name} --origin-resource-group {self.entity_rg} --destination-hub \
                {self.dest_hub} --destination-resource-group {self.dest_hub_rg} --auth-type login --replace"
        )
        self.compare_hubs()
        self.clean_up_dest_hub()

        # auth-type = login

        self.cmd(
            f"iot hub state migrate --origin-hub {self.entity_name} --origin-resource-group {self.entity_rg} --destination-hub \
                {self.dest_hub} --destination-resource-group {self.dest_hub_rg} --auth-type login -r"
        )
        self.compare_hubs()
        self.clean_up_dest_hub()

        # connection string

        self.cmd(
            f"iot hub state migrate --origin-hub-login {self.connection_string} --destination-hub-login \
                {self.dest_hub_cstring} -r"
        )
        self.compare_hubs()

        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete -n {} -g {}".format(self.dest_hub, self.dest_hub_rg))
        else:
            self.clean_up_dest_hub()