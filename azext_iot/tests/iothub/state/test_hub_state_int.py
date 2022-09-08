import random
import pytest
import json
import os
import time
from pathlib import Path
from azext_iot.common.shared import DeviceAuthApiType

from azext_iot.common.embedded_cli import EmbeddedCLI
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
    DATAPLANE_AUTH_TYPES,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
CWD = os.path.dirname(os.path.abspath(__file__))
cli = EmbeddedCLI()


def generate_device_names(count, edge=False):
    prefix = "d" if not edge else "e"
    names = [
        prefix + generate_generic_id()
        for i in range(count)
    ]
    return names


def _setup_hub_state(cstring):
    # make a configuration for the hub (applies to 0 devices, this is just to test the configuration settings)
    labels = {generate_generic_id() : generate_generic_id(), generate_generic_id() : generate_generic_id()}
    labels = json.dumps(labels)

    metrics_path = os.path.join(Path(CWD), "..", "configurations", "test_config_generic_metrics.json")
    content_path = os.path.join(Path(CWD), "..", "configurations", "test_adm_device_content.json")

    config_content = read_file_content(content_path)
    metrics = read_file_content(metrics_path)
    target_condition = "tags.bar=12"

    cli.invoke(
        "iot hub configuration create --config-id {} -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' "
        "--target-condition {}".format(
            generate_generic_id()[:10], cstring, config_content, labels, random.randint(1, 10), metrics, target_condition
        )
    )

    # make a regular edge deployment
    deployment1_path = os.path.join(Path(CWD), "..", "configurations", "test_edge_deployment.json")
    edge_content1 = read_file_content(deployment1_path)
    cli.invoke(
        "iot edge deployment create -d deployment1 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' "
        "--target-condition {}".format(
            cstring, edge_content1, labels, random.randint(1, 10), metrics, target_condition
        )
    )

    # make a layered edge deployment
    deployment2_path = os.path.join(Path(CWD), "..", "configurations", "test_edge_deployment_layered.json")
    edge_content2 = read_file_content(deployment2_path)
    cli.invoke(
        "iot edge deployment create -d deployment2 -l {} --content '{}' --labels '{}' --priority {} --metrics '{}' "
        "--target-condition {} --layered".format(
            cstring, edge_content2, labels, random.randint(1, 10), metrics, target_condition
        )
    )

    # populate hub with devices

    for device_type in DEVICE_TYPES:
        device_count = 3
        device_ids = generate_device_names(
            device_count, edge=device_type == "edge"
        )
        edge_enabled = "--edge-enabled" if device_type == "edge" else ""

        # Create SAS-auth device and module
        custom_primary_key = generate_key()
        custom_secondary_key = generate_key()
        cli.invoke(
            f"iot hub device-identity create -d {device_ids[0]} -l {cstring} --pk {custom_primary_key} "
            f"--sk {custom_secondary_key} {edge_enabled}"
        )
        cli.invoke(
            f"iot hub module-identity create -m deviceModule -d {device_ids[0]} -l {cstring}"
        )

        # create x509_ca device and module
        cli.invoke(
            f"iot hub device-identity create -d {device_ids[1]} -l {cstring} --am x509_ca {edge_enabled}"
        )
        cli.invoke(
            f"iot hub module-identity create -m deviceModule -d {device_ids[1]} -l {cstring} --am x509_ca"
        )

        # create x509_thumbprint device and module
        cli.invoke(
            f"iot hub device-identity create -d {device_ids[2]} -l {cstring} --am x509_thumbprint "
            f"--ptp {PRIMARY_THUMBPRINT} --stp {SECONDARY_THUMBPRINT} {edge_enabled}"
        )
        ptp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
        stp = create_self_signed_certificate(subject="aziotcli", valid_days=1, cert_output_dir=None)["thumbprint"]
        cli.invoke(
            f"iot hub module-identity create -m deviceModule -d {device_ids[2]} -l {cstring} "
            f"--am x509_thumbprint --ptp {ptp} --stp {stp}"
        )

        # add some children
        if edge_enabled:
            cli.invoke(
                f"iot hub device-identity children add -l {cstring} -d {device_ids[0]} --cl {device_ids[1]}"
            )
            cli.invoke(
                f"iot hub device-identity children add -l {cstring} -d {device_ids[1]} --cl {device_ids[2]}"
            )

        # add a property and a tag to each device's twin
        for i in range(len(device_ids)):
            device = device_ids[i]

            val = generate_generic_id()
            cli.invoke(
                f"iot hub device-twin update -d {device} -l {cstring} --set properties.desired.testProp={val}"
            )

            patch_tags = json.dumps({
                generate_generic_id(): generate_generic_id(),
                generate_generic_id(): generate_generic_id(),
            })

            cli.invoke(
                f"iot hub device-twin update -d {device} -l {cstring}"
                f" --tags '{patch_tags}'"
            )

            val = generate_generic_id()
            cli.invoke(
                f"iot hub module-twin update -d {device} -m deviceModule -l {cstring} --set "
                f"properties.desired.testProp={val}"
            )

            patch_tags = json.dumps({
                generate_generic_id(): generate_generic_id(),
                generate_generic_id(): generate_generic_id(),
            })

            cli.invoke(
                f"iot hub module-twin update -d {device} -m deviceModule -l {cstring}"
                f" --tags '{patch_tags}'"
            )


@pytest.fixture()
def setup_hub_states(provisioned_iothubs_module):
    filename = generate_generic_id() + ".json"
    provisioned_iothubs_module[0]["filename"] = filename
    _setup_hub_state(provisioned_iothubs_module[0]["connectionString"])
    yield provisioned_iothubs_module
    if os.path.isfile(filename):
        os.remove(filename)


def set_cmd_auth_type(command: str, auth_type: str, cstring: str) -> str:
    if auth_type not in DATAPLANE_AUTH_TYPES:
        raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

    # cstring takes precedence
    if auth_type == "cstring":
        return f"{command} --login {cstring}"

    return f"{command} --auth-type {auth_type}"

def clean_up_hub(cstring):
    dest_hub_configs = cli.invoke(
        f"iot hub configuration list -l {cstring}"
    ).as_json()

    dest_hub_deploys = cli.invoke(
        f"iot edge deployment list -l {cstring}"
    ).as_json()

    for config in dest_hub_configs + dest_hub_deploys:
        cli.invoke(
            "iot hub configuration delete -c {} -l {}".format(config["id"], cstring)
        )

    dest_hub_identities = cli.invoke(
        f"iot hub device-identity list -l {cstring}"
    ).as_json()

    for id in dest_hub_identities:
        cli.invoke(
            "iot hub device-identity delete -d {} -l {}".format(id["deviceId"], cstring)
        )

    # gives the api enough time to update
    time.sleep(1)

@pytest.mark.hub_infrastructure()
def test_export_import(setup_hub_states):
    filename = setup_hub_states[0]["filename"]
    hub_name = setup_hub_states[0]["name"]
    hub_rg = setup_hub_states[0]["rg"]
    hub_cstring = setup_hub_states[0]["connectionString"]
    for auth_phase in DATAPLANE_AUTH_TYPES:
        cli.invoke(
            set_cmd_auth_type(
                f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg} --of",
                auth_type=auth_phase,
                cstring=hub_cstring
            )
        )
        compare_hub_to_file(filename, hub_cstring)

    for auth_phase in DATAPLANE_AUTH_TYPES:
        clean_up_hub(hub_cstring)
        cli.invoke(
            set_cmd_auth_type(
                f"iot hub state import -n {hub_name} -f {filename} -g {hub_rg} -r",
                auth_type=auth_phase,
                cstring=hub_cstring
            )
        )
        time.sleep(1)  # gives the hub time to update before the checks
        compare_hub_to_file(filename, hub_cstring)


@pytest.mark.hub_infrastructure(count=2)
def test_migrate(setup_hub_states):
    origin_name = setup_hub_states[0]["name"]
    origin_rg = setup_hub_states[0]["rg"]
    origin_cstring = setup_hub_states[0]["connectionString"]
    dest_name = setup_hub_states[1]["name"]
    dest_rg = setup_hub_states[1]["rg"]
    dest_cstring = setup_hub_states[1]["connectionString"]
    for auth_phase in DATAPLANE_AUTH_TYPES:
        if auth_phase == "cstring":
            cli.invoke(
                f"iot hub state migrate --origin-hub-login {origin_cstring} --destination-hub-login "
                f"{dest_cstring} -r"
            )
        else:
            cli.invoke(
                set_cmd_auth_type(
                    f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
                    f"--destination-hub {dest_name} --destination-resource-group {dest_rg} -r",
                    auth_type=auth_phase,
                    cstring=None
                )
            )

        time.sleep(1)  # gives the hub time to update before the checks
        compare_hubs(origin_cstring, dest_cstring)
        clean_up_hub(dest_cstring)


def compare_hubs(origin_cstring, dest_cstring):
    # compare configurations (there's only one)
    orig_hub_configs = cli.invoke(
        f"iot hub configuration list -l {origin_cstring}"
    ).as_json()
    dest_hub_configs = cli.invoke(
        f"iot hub configuration list -l {dest_cstring}"
    ).as_json()
    compare_configs(orig_hub_configs, dest_hub_configs)

    # compare edge deployments
    orig_hub_deploys = cli.invoke(
        f"iot edge deployment list -l {origin_cstring}"
    ).as_json()
    dest_hub_deploys = cli.invoke(
        f"iot edge deployment list -l {dest_cstring}"
    ).as_json()
    compare_configs(orig_hub_deploys, dest_hub_deploys)

    # compare devices
    orig_hub_identities = cli.invoke(
        f"iot hub device-identity list -l {origin_cstring}"
    ).as_json()
    dest_hub_identities = cli.invoke(
        f"iot hub device-identity list -l {dest_cstring}"
    ).as_json()

    dest_hub_identities_dict = {}
    for id in dest_hub_identities:
        dest_hub_identities_dict[id["deviceId"]] = id
    assert(len(orig_hub_identities) == len(dest_hub_identities))

    for device in orig_hub_identities:
        assert device["deviceId"] in dest_hub_identities_dict
        target = dest_hub_identities_dict[device["deviceId"]]

        if device["authenticationType"] == DeviceAuthApiType.sas.value:
            id1 = cli.invoke(
                "iot hub device-identity show -l {} -d {}".format(origin_cstring, device['deviceId'])
            ).as_json()
            id2 = cli.invoke(
                "iot hub device-identity show -l {} -d {}".format(dest_cstring, device['deviceId'])
            ).as_json()

            device["symmetricKey"] = id1["authentication"]["symmetricKey"]
            target["symmetricKey"] = id2["authentication"]["symmetricKey"]

        compare_devices(device, target)

        # compare modules

        orig_modules = cli.invoke(
            "iot hub module-identity list -d {} -l {}".format(device['deviceId'], origin_cstring)
        ).as_json()
        dest_modules = cli.invoke(
            "iot hub module-identity list -d {} -l {}".format(device['deviceId'], dest_cstring)
        ).as_json()

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

            module_twin = cli.invoke(
                f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {origin_cstring}"
            ).as_json()
            target_module_twin = cli.invoke(
                f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {dest_cstring}"
            ).as_json()

            compare_module_twins(module_twin, target_module_twin)

        # compare children
        if device["capabilities"]["iotEdge"]:
            orig_children = cli.invoke(
                f"iot hub device-identity children list -d {device['deviceId']} -l {origin_cstring}"
            ).as_json()
            dest_children = cli.invoke(
                f"iot hub device-identity children list -d {device['deviceId']} -l {dest_cstring}"
            ).as_json()

            assert(orig_children == dest_children)

def compare_hub_to_file(filename, cstring):
    with open(filename, 'r', encoding='utf-8') as f:
        hub_info = json.load(f)

    # compare configurations

    file_configs = hub_info["configurations"]
    hub_configs = cli.invoke(
        f"iot hub configuration list -l {cstring}"
    ).as_json()
    compare_configs(file_configs, hub_configs)

    # compare edge deployments

    file_deploys = hub_info["edgeDeployments"]
    hub_deploys = cli.invoke(
        f"iot edge deployment list -l {cstring}"
    ).as_json()
    compare_configs(file_deploys, hub_deploys)

    # compare devices

    file_devices = hub_info["devices"]
    hub_devices = cli.invoke(
        f"iot hub device-identity list -l {cstring}"
    ).as_json()

    assert(len(file_devices) == len(hub_devices))
    for device in hub_devices:
        id = cli.invoke(
            "iot hub device-identity show -l {} -d {}".format(cstring, device['deviceId'])
        ).as_json()
        device["symmetricKey"] = id["authentication"]["symmetricKey"]

        assert device["deviceId"] in file_devices

        target_device = file_devices[device["deviceId"]]

        compare_devices(device, target_device)

        file_modules = hub_info["modules"][device["deviceId"]]
        hub_modules = cli.invoke(
            "iot hub module-identity list -d {} -l {}".format(device["deviceId"], cstring)
        ).as_json()

        # edge devices have two default modules that aren't saved to the file
        if device["capabilities"]["iotEdge"]:
            assert(len(file_modules) == len(hub_modules) - 2)
        else:
            assert(len(file_modules) == len(hub_modules))

        for module in hub_modules:
            if module['moduleId'] in ["$edgeAgent", "$edgeHub"]:
                continue

            module_twin = cli.invoke(
                f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {cstring}"
            ).as_json()

            target_module = None
            for mod in file_modules:
                if module["moduleId"] == mod[0]["module_id"]:
                    target_module = mod[0]
                    target_module_twin = mod[1]
                    break

            assert target_module

            assert(module["authentication"] == target_module["authentication"])

            compare_module_twins(module_twin, target_module_twin)

        # compare children
        if device["capabilities"]["iotEdge"]:
            file_children = hub_info["children"][device["deviceId"]]
            dest_children = cli.invoke(
                f"iot hub device-identity children list -d {device['deviceId']} -l {cstring}"
            ).as_json()

            assert(file_children == dest_children)


def compare_configs(configlist1, configlist2):
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


def compare_devices(device1, device2):
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


def compare_module_twins(twin1, twin2):
    assert(len(twin1["properties"]["desired"]) == len(twin2["properties"]["desired"]))
    for prop in twin1["properties"]["desired"]:
        if prop not in ["$metadata", "$version"]:
            assert(prop in twin2["properties"]["desired"])
            assert(twin1["properties"]["desired"][prop] == twin2["properties"]["desired"][prop])

    if "tags" in twin1:
        assert(twin1["tags"] == twin2["tags"])
    assert(twin1["status"] == twin2["status"])
