import pytest
import random
import json
import os
from azext_iot.common.shared import DeviceAuthApiType

from azext_iot.iothub.providers.state import StateProvider

from azext_iot.operations.hub import iot_device_twin_update
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.utility import generate_key
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.iothub import (
    DATAPLANE_AUTH_TYPES,
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)

class TestHubExportImport(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestHubExportImport, self).__init__(test_case)
        self.dest_hub = settings.env.azext_iot_desthub or "test-hub-" + generate_generic_id()
        self.dest_hub_rg = settings.env.azext_iot_destrg
        self.filename = "/project/files/" + generate_generic_id() + ".json" # change this

    def create_hub_state(self):

        # create destination hub

        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub create --name {} --resource-group {} --sku S1 ".format(self.dest_hub, self.entity_rg))

        # make a configuration for the hub (applies to 0 devices, this is just to test the configuration settings)

        config_content = {"deviceContent" : 
            {"properties.desired.propFromConfig" : generate_generic_id()}
        }
        config_content = json.dumps(config_content)

        labels = {generate_generic_id():generate_generic_id(), 
            generate_generic_id():generate_generic_id()}
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

        self.cmd("iot hub configuration create --config-id {} -n {} -g {} --content '{}' --labels '{}' --priority {} --metrics '{}' --target-condition {}" \
            .format("hubConfig", self.entity_name, self.entity_rg, "{config_content}", "{labels}", priority, "{metrics}", "tags.bar=12"))

        # populate hub with devices
        
        for auth_phase in DATAPLANE_AUTH_TYPES:

            if auth_phase == "cstring":
                # TODO
                continue

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
                    f"iot hub device-identity create -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} --pk {custom_primary_key} \
                        --sk {custom_secondary_key} {edge_enabled} --auth-type={auth_phase}"
                )

                # create x509_ca device
                self.cmd(
                    f"iot hub device-identity create -d {device_ids[1]} -n {self.entity_name} -g {self.entity_rg} --am x509_ca {edge_enabled} --auth-type={auth_phase}"
                )

                # create x509_thumbprint device
                self.cmd(
                    f"iot hub device-identity create -d {device_ids[2]} -n {self.entity_name} -g {self.entity_rg} --am x509_thumbprint \
                        --ptp {PRIMARY_THUMBPRINT} --stp {SECONDARY_THUMBPRINT} {edge_enabled} --auth-type={auth_phase}"
                )

                # add a property and a tag to each device's twin
                for i in range(len(device_ids)):
                    device = device_ids[i]

                    val = generate_generic_id()
                    self.cmd(
                        f"iot hub device-twin update -d {device} -n {self.entity_name} -g {self.entity_rg} --auth-type={auth_phase} --set properties.desired.testProp={val}"
                    )

                    patch_tags = {
                        generate_generic_id(): generate_generic_id(),
                        generate_generic_id(): generate_generic_id(),
                    }

                    self.kwargs["patch_tags"] = json.dumps(patch_tags)
      
                    self.cmd(
                        f"iot hub device-twin update -d {device} -n {self.entity_name} -g {self.entity_rg} --auth-type={auth_phase}"
                        " --tags '{patch_tags}'"
                    )
                    
                    # make a module for each device, same authentication method as device

                    if(i == 0):
                        self.cmd("iot hub module-identity create -d {} -m deviceModule -n {} -g {} --auth-type={}".format(device, self.entity_name, self.entity_rg, auth_phase))

                    elif(i == 1):
                        self.cmd("iot hub module-identity create -d {} -m deviceModule -n {} -g {} --auth-type={} --am x509_ca".format(device, self.entity_name, self.entity_rg, auth_phase))

                    elif(i == 2):
                        ptp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
                        stp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]

                        self.cmd("iot hub module-identity create -d {} -m deviceModule -n {} -g {} --auth-type={} --am x509_thumbprint --ptp {} --stp {}" \
                            .format(device, self.entity_name, self.entity_rg, auth_phase, ptp, stp))
                        
                    # add a property and a tag to each module's twin

                    val = generate_generic_id()
                    self.cmd(
                        f"iot hub module-twin update -d {device} -m deviceModule -n {self.entity_name} -g {self.entity_rg} --auth-type={auth_phase} --set properties.desired.testProp={val}"
                    )

                    patch_tags = {
                        generate_generic_id(): generate_generic_id(),
                        generate_generic_id(): generate_generic_id(),
                    }
                    self.kwargs["patch_tags"] = json.dumps(patch_tags)

                    self.cmd(
                        f"iot hub module-twin update -d {device} -m deviceModule -n {self.entity_name} -g {self.entity_rg} --auth-type={auth_phase}"
                        " --tags '{patch_tags}'"
                    )

    def compare_hubs(self):

        # compare configurations (there's only one)

        orig_hub_configs = self.cmd(
            f"iot hub configuration list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        dest_hub_configs = self.cmd(
            f"iot hub configuration list -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).get_output_in_json()

        assert(len(orig_hub_configs) == 1 and len(dest_hub_configs) == 1)

        assert(orig_hub_configs[0]["id"] == dest_hub_configs[0]["id"])
        assert(orig_hub_configs[0]["content"] == dest_hub_configs[0]["content"])
        assert(orig_hub_configs[0]["metrics"] == dest_hub_configs[0]["metrics"])
        assert(orig_hub_configs[0]["priority"] == dest_hub_configs[0]["priority"])
        assert(orig_hub_configs[0]["systemMetrics"]["queries"] == dest_hub_configs[0]["systemMetrics"]["queries"])
        assert(orig_hub_configs[0]["targetCondition"] == dest_hub_configs[0]["targetCondition"])

        # compare devices

        orig_hub_identities = self.cmd(
            f"iot hub device-identity list -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()
        dest_hub_identities = self.cmd(
            f"iot hub device-identity list -n {self.dest_hub} -g {self.dest_hub_rg}"
        ).get_output_in_json()

        for device in orig_hub_identities:
            target = None
            for id in dest_hub_identities:
                if(device["deviceId"] == id["deviceId"]):
                    target = id
                    break

            assert target

            assert (device["authenticationType"] == target["authenticationType"])
            assert (device["capabilities"]["iotEdge"] == target["capabilities"]["iotEdge"])
            assert (device["connectionState"] == target["connectionState"])
            assert (device["status"] == target["status"])

            if("tags" in device.keys()):
                assert (device["tags"] == target["tags"])

            if(device["authenticationType"] == DeviceAuthApiType.sas.value):
                id1 = self.cmd("iot hub device-identity show -n {} -g {} -d {}".format(self.entity_name, self.entity_rg, device['deviceId'])).get_output_in_json()
                id2 = self.cmd("iot hub device-identity show -n {} -g {} -d {}".format(self.dest_hub, self.dest_hub_rg, device['deviceId'])).get_output_in_json()
                assert (id1["authentication"]["symmetricKey"]["primaryKey"] == id2["authentication"]["symmetricKey"]["primaryKey"])
                assert (id1["authentication"]["symmetricKey"]["secondaryKey"] == id2["authentication"]["symmetricKey"]["secondaryKey"])
                
            if(device["authenticationType"] == DeviceAuthApiType.selfSigned.value):
                assert (device["x509Thumbprint"]["primaryThumbprint"] == target["x509Thumbprint"]["primaryThumbprint"])
                assert (device["x509Thumbprint"]["secondaryThumbprint"] == target["x509Thumbprint"]["secondaryThumbprint"])

            assert (len(device["properties"]["desired"]) == len(target["properties"]["desired"]))

            for prop in device["properties"]["desired"]:
                if(prop != "$metadata" and prop != "$version"):
                    assert (prop in target["properties"]["desired"])
                    assert (device["properties"]["desired"][prop] == target["properties"]["desired"][prop])

            # compare modules

            orig_modules = self.cmd(
                "iot hub module-identity list -d {} -n {} -g {}".format(device['deviceId'], self.entity_name, self.entity_rg)
            ).get_output_in_json()
            dest_modules = self.cmd(
                "iot hub module-identity list -d {} -n {} -g {}".format(device['deviceId'], self.dest_hub, self.dest_hub_rg)
            ).get_output_in_json()

            if(device["capabilities"]["iotEdge"]):
                assert (len(orig_modules) == 3)
                assert (len(dest_modules) == 3)
            else:
                assert (len(orig_modules) == 1)
                assert (len(dest_modules) == 1)

            for module in orig_modules:
                target_module = None
                for mod in dest_modules:
                    if(module["moduleId"] == mod["moduleId"]):
                        target_module = mod
                        break

                assert target_module

                assert (module["authentication"] == target_module["authentication"])

                module_twin = self.cmd(
                    f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -n {self.entity_name} -g {self.entity_rg}"
                ).get_output_in_json()  
                target_module_twin = self.cmd(
                    f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -n {self.dest_hub} -g {self.dest_hub_rg}"
                ).get_output_in_json()   
                
                assert (len(module_twin["properties"]["desired"]) == len(target_module_twin["properties"]["desired"]))
                for prop in module_twin["properties"]["desired"]:
                    if(prop != "$metadata" and prop != "version"):
                        assert (prop in target_module_twin["properties"]["desired"])
                        assert (module_twin["properties"]["desired"][prop] == target_module_twin["properties"]["desired"][prop])
                
                if("tags" in module_twin.keys()):
                    assert (module_twin["tags"] == target_module_twin["tags"])
                assert (module_twin["status"] == target_module_twin["status"])

    def clean_up_dest_hub(self):

        if not settings.env.azext_iot_desthub:
            self.cmd("iot hub delete --name {} --resource-group {}".format(self.dest_hub, self.entity_rg))
        else: 
            dest_hub_configs = self.cmd(
                f"iot hub configuration list -n {self.dest_hub} -g {self.dest_hub_rg}"
            ).get_output_in_json()

            for config in dest_hub_configs:
                self.cmd(
                    "iot hub configuration delete -c {} -n {} -g {}".format(config["id"], self.dest_hub, self.dest_hub_rg)
                )

            dest_hub_identities = self.cmd(
                f"iot hub device-identity list -n {self.dest_hub} -g {self.dest_hub_rg}"
            ).get_output_in_json()
            
            for id in dest_hub_identities:
                self.cmd(
                    "iot hub device-identity delete -d {} -n {} -g {}".format(id["deviceId"], self.dest_hub, self.dest_hub_rg)
                )

    def test_import_export(self):

        self.create_hub_state()

        self.cmd(
            f"iot hub state export -n {self.entity_name} -f {self.filename} -g {self.entity_rg}"
        )

        self.cmd(
            f"iot hub state import -n {self.dest_hub} -f {self.filename} -g {self.dest_hub_rg} --overwrite"
        )

        self.compare_hubs()
        self.clean_up_dest_hub()
        
        os.remove(self.filename)

    def test_migrate(self):

        self.create_hub_state()

        self.cmd(
            f"iot hub state migrate --origin-hub {self.entity_name} --origin-resource-group {self.entity_rg} --destination-hub {self.dest_hub} \
                --destination-resource-group {self.dest_hub_rg} --overwrite"
        )

        self.compare_hubs()
        self.clean_up_dest_hub()