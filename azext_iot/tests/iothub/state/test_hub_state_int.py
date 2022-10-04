import random
import pytest
import json
import os
import time
from pathlib import Path
from azext_iot.common.shared import DeviceAuthApiType

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.utility import generate_key, read_file_content
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.iothub import (
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DATAPLANE_AUTH_TYPES,
    DEVICE_TYPES,
)
from azext_iot.common._azure import parse_iot_hub_message_endpoint_connection_string, parse_storage_container_connection_string

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED, opt_env_set=ENV_SET_TEST_IOTHUB_OPTIONAL)
CWD = os.path.dirname(os.path.abspath(__file__))
cli = EmbeddedCLI()

DATAPLANE = "configurations devices"
CONTROLPLANE = "arm"
MAX_RETRIES = 5
# DATAPLANE_AUTH_TYPES = ["cstring"]


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
        device_ids = generate_device_names(device_count, edge=device_type == "edge")
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


# Test with an empty hub to save all, upload all, migrate all - will need to have seperate hubs created

@pytest.fixture()
def setup_hub_states(provisioned_iothubs_module):
    filename = generate_generic_id() + ".json"
    provisioned_iothubs_module[0]["filename"] = filename
    _setup_hub_state(provisioned_iothubs_module[0]["connectionString"])
    time.sleep(5)
    yield provisioned_iothubs_module
    if os.path.isfile(filename):
        os.remove(filename)

@pytest.fixture()
def setup_hub_states_controlplane(setup_hub_controlplane_states):
    filename = generate_generic_id() + ".json"
    setup_hub_controlplane_states[0]["filename"] = filename
    yield setup_hub_controlplane_states
    if os.path.isfile(filename):
        os.remove(filename)


def set_cmd_auth_type(command: str, auth_type: str, cstring: str) -> str:
    if auth_type not in DATAPLANE_AUTH_TYPES:
        raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

    # cstring takes precedence
    if auth_type == "cstring":
        return f"{command} --login {cstring}"

    return f"{command} --auth-type {auth_type}"


def clean_up_hub(hub_name, hub_rg):
    empty_filename = generate_generic_id() + ".json"
    with open(empty_filename, 'w', encoding='utf-8') as f:
        f.write("{}")
    cli.invoke(
        f"iot hub state import -n {hub_name} -f {empty_filename} -g {hub_rg} -r"
    )
    os.remove(empty_filename)


def clean_up_hub_dataplane(cstring):
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
    print(f"found {len(dest_hub_identities)} devices in {cstring}.")
    print([id["deviceId"] for id in dest_hub_identities])

    for id in dest_hub_identities:
        cli.invoke(
            "iot hub device-identity delete -d {} -l {}".format(id["deviceId"], cstring)
        )

    # gives the api enough time to update
    time.sleep(1)


@pytest.mark.hub_infrastructure(count=2, sys_identity=True, user_identity=True)
def test_migrate_controlplane(setup_hub_states_controlplane):
    origin_name = setup_hub_states_controlplane[0]["name"]
    origin_rg = setup_hub_states_controlplane[0]["rg"]
    dest_name = setup_hub_states_controlplane[1]["name"]
    # dest_rg = setup_hub_states_controlplane[1]["rg"]
    # assume origin_rg == dest_rg

    cli.invoke(
        f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
        f"--destination-hub {dest_name} --destination-resource-group {origin_rg} -r --aspects {CONTROLPLANE}"
    )

    time.sleep(1)  # gives the hub time to update before the checks
    compare_hubs_controlplane(origin_name, dest_name, origin_rg)


# TODO figure out better way to force two hubs to be made that wont make this test create
# two hubs if ran by it
@pytest.mark.hub_infrastructure(count=2, sys_identity=True, user_identity=True)
def test_export_import_controlplane(setup_hub_states_controlplane):
    filename = setup_hub_states_controlplane[0]["filename"]
    hub_name = setup_hub_states_controlplane[0]["name"]
    hub_rg = setup_hub_states_controlplane[0]["rg"]

    cli.invoke(
            f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg} --of --aspects {CONTROLPLANE}"
    )
    compare_hub_controlplane_to_file(filename, hub_name, hub_rg)
    clean_up_hub(hub_name, hub_rg)
    # TODO: change this to import empty file
    time.sleep(5)
    cli.invoke(
        f"iot hub state import -n {hub_name} -f {filename} -g {hub_rg} -r --aspects {CONTROLPLANE}"
    )
    time.sleep(10)  # gives the hub time to update before the checks
    compare_hub_controlplane_to_file(filename, hub_name, hub_rg)


@pytest.mark.hub_infrastructure(count=2)
def test_migrate_dataplane(setup_hub_states):
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
                f"{dest_cstring} -r --aspects {DATAPLANE}"
            )
        else:
            cli.invoke(
                set_cmd_auth_type(
                    f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
                    f"--destination-hub {dest_name} --destination-resource-group {dest_rg} -r --aspects {DATAPLANE}",
                    auth_type=auth_phase,
                    cstring=None
                )
            )

        time.sleep(1)  # gives the hub time to update before the checks
        compare_hubs_dataplane(origin_cstring, dest_cstring)
        clean_up_hub_dataplane(dest_cstring)


# TODO figure out better way to force two hubs to be made that wont make this test create
# two hubs if ran by it
# Make sure this is just dataplane to split up functionality
@pytest.mark.hub_infrastructure(count=1)
def test_export_import_dataplane(setup_hub_states):
    filename = setup_hub_states[0]["filename"]
    hub_name = setup_hub_states[0]["name"]
    hub_rg = setup_hub_states[0]["rg"]
    hub_cstring = setup_hub_states[0]["connectionString"]
    for auth_phase in DATAPLANE_AUTH_TYPES:
        cli.invoke(
            set_cmd_auth_type(
                f"iot hub state export -n {hub_name} -f {filename} -g {hub_rg} --of --aspects {DATAPLANE}",
                auth_type=auth_phase,
                cstring=hub_cstring
            )
        )
        compare_hub_dataplane_to_file(filename, hub_cstring)

    for auth_phase in DATAPLANE_AUTH_TYPES:
        clean_up_hub_dataplane(hub_cstring)
        # TODO: change this to import empty file
        time.sleep(5)
        cli.invoke(
            set_cmd_auth_type(
                f"iot hub state import -n {hub_name} -f {filename} -g {hub_rg} -r --aspects {DATAPLANE}",
                auth_type=auth_phase,
                cstring=hub_cstring
            )
        )
        time.sleep(10)  # gives the hub time to update before the checks
        compare_hub_dataplane_to_file(filename, hub_cstring)

# Dataplane main compare commands
def compare_hubs_dataplane(origin_cstring: str, dest_cstring: str):
    # compare configurations (there's only one)
    tries = 0
    while tries < MAX_RETRIES:
        try:
            orig_hub_configs = cli.invoke(
                f"iot hub configuration list -l {origin_cstring}"
            ).as_json()
            dest_hub_configs = cli.invoke(
                f"iot hub configuration list -l {dest_cstring}"
            ).as_json()
            compare_configs(orig_hub_configs, dest_hub_configs)
            break
        except AssertionError:
            tries += 1
            time.sleep(1)

    # compare edge deployments
    tries = 0
    while tries < MAX_RETRIES:
        try:
            orig_hub_deploys = cli.invoke(
                f"iot edge deployment list -l {origin_cstring}"
            ).as_json()
            dest_hub_deploys = cli.invoke(
                f"iot edge deployment list -l {dest_cstring}"
            ).as_json()
            compare_configs(orig_hub_deploys, dest_hub_deploys)
            break
        except AssertionError:
            tries += 1
            time.sleep(1)

    # compare devices
    tries = 0
    while tries < MAX_RETRIES:
        orig_hub_identities = cli.invoke(
            f"iot hub device-identity list -l {origin_cstring}"
        ).as_json()
        dest_hub_identities = cli.invoke(
            f"iot hub device-identity list -l {dest_cstring}"
        ).as_json()
        if len(orig_hub_identities) == len(dest_hub_identities):
            break
        tries += 1
        time.sleep(1)

    dest_hub_identities_dict = {}
    for id in dest_hub_identities:
        dest_hub_identities_dict[id["deviceId"]] = id

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
            assert len(orig_modules) == len(dest_modules) == 3
        else:
            assert len(orig_modules) == len(dest_modules) == 1

        for module in orig_modules:
            target_module = None
            for mod in dest_modules:
                if module["moduleId"] == mod["moduleId"]:
                    target_module = mod
                    break

            assert target_module

            assert module["authentication"] == target_module["authentication"]

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

            assert orig_children == dest_children


def compare_hub_dataplane_to_file(filename: str, cstring: str):
    with open(filename, 'r', encoding='utf-8') as f:
        hub_info = json.load(f)

    # compare configurations
    file_configs = list(hub_info["configurations"]["admConfigurations"].values())
    tries = 0
    while tries < MAX_RETRIES:
        try:
            hub_configs = cli.invoke(
                f"iot hub configuration list -l {cstring}"
            ).as_json()
            compare_configs(file_configs, hub_configs)
            break
        except AssertionError:
            tries += 1
            time.sleep(1)

    # compare edge deployments
    file_deploys = list(hub_info["configurations"]["edgeDeployments"].values())
    tries = 0
    while tries < MAX_RETRIES:
        try:
            hub_deploys = cli.invoke(
                f"iot edge deployment list -l {cstring}"
            ).as_json()
            compare_configs(file_deploys, hub_deploys)
            break
        except AssertionError:
            tries += 1
            time.sleep(1)

    # compare devices
    file_devices = hub_info["devices"]
    hub_devices = cli.invoke(
        f"iot hub device-identity list -l {cstring}"
    ).as_json()

    tries = 0
    while tries < MAX_RETRIES:
        hub_devices = cli.invoke(
            f"iot hub device-identity list -l {cstring}"
        ).as_json()
        if len(file_devices) == len(hub_devices):
            break
        tries += 1
        time.sleep(1)

    assert len(file_devices) == len(hub_devices)

    # file_modules_list = hub_info["modules"]
    # file_modules_dict = {}
    # for module in file_modules_list:
    #     if module[0]["device_id"] in file_modules_dict:
    #         file_modules_dict[module[0]["device_id"]].append(module)
    #     else:
    #         file_modules_dict[module[0]["device_id"]] = [module]

    for device in hub_devices:
        id = cli.invoke(
            f"iot hub device-identity show -l {cstring} -d {device['deviceId']}"
        ).as_json()
        device["symmetricKey"] = id["authentication"]["symmetricKey"]

        file_device = file_devices[device["deviceId"]]
        file_device_identity = {**file_device["identity"], **file_device["twin"]}
        # convert auth type to twin style for easier comparisons
        file_device_identity["authenticationType"] = file_device_identity["authentication"]["type"]
        if file_device_identity["authenticationType"] == DeviceAuthApiType.sas.value:
            file_device_identity["symmetricKey"] = file_device_identity["authentication"]["symmetricKey"]
        elif file_device_identity["authenticationType"] == DeviceAuthApiType.selfSigned.value:
            file_device_identity["x509Thumbprint"] = file_device_identity["authentication"]["x509Thumbprint"]

        assert file_device_identity

        for key in ["$metadata", "$version"]:
                device["properties"]["desired"].pop(key)

        compare_devices(device, file_device_identity)
        # try:
        #     compare_devices(device, file_device)
        # except AssertionError:
        #     # device retrieved was not updated correctly
        #     print(f" fetch device {device['deviceId']} again.")
        #     time.sleep(1)
        #     hub_devices = cli.invoke(
        #         f"iot hub device-identity list -l {cstring}"
        #     ).as_json()


        file_modules = file_device.get("modules", {})
        hub_modules = cli.invoke(
            "iot hub module-identity list -d {} -l {}".format(device["deviceId"], cstring)
        ).as_json()

        assert len(file_modules) == len(hub_modules)

        for module in hub_modules:

            module_twin = cli.invoke(
                f"iot hub module-twin show -m {module['moduleId']} -d {device['deviceId']} -l {cstring}"
            ).as_json()

            target_module = file_modules[module["moduleId"]]["identity"]
            target_module_twin = file_modules[module["moduleId"]]["twin"]

            assert target_module
            assert module["authentication"] == target_module["authentication"]
            for key in ["$metadata", "$version"]:
                module_twin["properties"]["desired"].pop(key)

            compare_module_twins(module_twin, target_module_twin)

        # compare parent
        if device.get("parentScopes"):
            device_parent = device["parentScopes"][0].split("://")[1]
            assert file_device["parent"] == device_parent[:device_parent.rfind("-")]


def compare_hub_controlplane_to_file(filename: str, hub_name: str, rg: str):
    with open(filename, 'r', encoding='utf-8') as f:
        hub_info = json.load(f)

    # compare certificates
    file_certs = hub_info["certificates"]
    hub_certs = cli.invoke(
        "iot hub certificate list --hub-name {} -g {}".format(hub_name, rg)
    ).as_json()["value"]
    assert (len(file_certs) == len(hub_certs) == 1)
    for i in range(len(file_certs)):
        compare_certs(file_certs[i], hub_certs[i])

    # compare endpoints
    file_endpoints = hub_info["endpoints"]
    hub_endpoints = cli.invoke(
        f"iot hub routing-endpoint list --hub-name {hub_name} -g {rg}"
    ).as_json()
    for ep_type in ["eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"]:
        assert len(file_endpoints[ep_type]) == len(hub_endpoints[ep_type])
        compare_endpoints(file_endpoints[ep_type], hub_endpoints[ep_type], ep_type)

    # compare routes
    file_routes = hub_info["routes"]
    hub_routes = cli.invoke(f"iot hub route list --hub-name {hub_name} -g {rg}").as_json()
    compare_routes(file_routes, hub_routes)


def compare_hubs_controlplane(origin_hub_name: str, dest_hub_name: str, rg: str):
    # compare certificates
    orig_hub_certs = cli.invoke(
        "iot hub certificate list --hub-name {} -g {}".format(origin_hub_name, rg)
    ).as_json()["value"]
    dest_hub_certs = cli.invoke(
        "iot hub certificate list --hub-name {} -g {}".format(dest_hub_name, rg)
    ).as_json()["value"]
    assert (len(orig_hub_certs) == len(dest_hub_certs))
    for i in range(len(orig_hub_certs)):
        compare_certs(orig_hub_certs[i], dest_hub_certs[i])

    # compare endpoints
    orig_hub_endpoints = cli.invoke(
        f"iot hub routing-endpoint list --hub-name {origin_hub_name} -g {rg}"
    ).as_json()
    dest_hub_endpoints = cli.invoke(
        f"iot hub routing-endpoint list --hub-name {dest_hub_name} -g {rg}"
    ).as_json()
    for ep_type in ["eventHubs", "serviceBusQueues", "serviceBusTopics", "storageContainers"]:
        assert len(orig_hub_endpoints[ep_type]) == len(dest_hub_endpoints[ep_type])
        compare_endpoints(orig_hub_endpoints[ep_type], dest_hub_endpoints[ep_type], ep_type)

    # compare routes
    orig_hub_routes = cli.invoke(f"iot hub route list --hub-name {origin_hub_name} -g {rg}").as_json()
    dest_hub_routes = cli.invoke(f"iot hub route list --hub-name {dest_hub_name} -g {rg}").as_json()
    compare_routes(orig_hub_routes, dest_hub_routes)


# Compare specific parts
def compare_configs(configlist1, configlist2):
    assert len(configlist1) == len(configlist2)

    for config in configlist1:
        target = None
        for c in configlist2:
            if c["id"] == config["id"]:
                target = c
                break
        assert target

        assert config["id"] == target["id"]
        assert config["content"] == target["content"]
        assert config["metrics"] == target["metrics"]
        assert config["priority"] == target["priority"]
        assert config["systemMetrics"]["queries"] == target["systemMetrics"]["queries"]
        assert config["targetCondition"] == target["targetCondition"]


def compare_devices(device1, device2):
    # Shared and identity only props
    assert device1["authenticationType"] == device2["authenticationType"]
    assert device1["capabilities"]["iotEdge"] == device2["capabilities"]["iotEdge"]
    assert device1["connectionState"] == device2["connectionState"]
    assert device1["status"] == device2["status"]

    if device1["authenticationType"] == DeviceAuthApiType.sas.value:
        assert device1["symmetricKey"]["primaryKey"] == device2["symmetricKey"]["primaryKey"]
        assert device1["symmetricKey"]["secondaryKey"] == device2["symmetricKey"]["secondaryKey"]

    if device1["authenticationType"] == DeviceAuthApiType.selfSigned.value:
        assert device1["x509Thumbprint"]["primaryThumbprint"] == device2["x509Thumbprint"]["primaryThumbprint"]
        assert device1["x509Thumbprint"]["secondaryThumbprint"] == device2["x509Thumbprint"]["secondaryThumbprint"]

    # Twin only props
    if "tags" in device1:
        assert device1["tags"] == device2["tags"]

    assert len(device1["properties"]["desired"]) == len(device2["properties"]["desired"])

    for prop in device1["properties"]["desired"]:
        if prop not in ["$metadata", "$version"]:
            assert prop in device2["properties"]["desired"]
            assert device1["properties"]["desired"][prop] == device2["properties"]["desired"][prop]


def compare_module_identities(module1, module2):
    """Focus on shared props and identity only props"""
    assert module1["managedBy"] == module2["managedBy"]
    assert module1["connectionState"] == module2["connectionState"]

    assert module1["authentication"]["type"] == module2["authentication"]["type"]

    if module1["authentication"]["type"] == DeviceAuthApiType.sas.value:
        assert module1["authentication"]["symmetricKey"]["primaryKey"] == module2["authentication"]["symmetricKey"]["primaryKey"]
        assert module1["authentication"]["symmetricKey"]["secondaryKey"] == module2["authentication"]["symmetricKey"]["secondaryKey"]

    if module1["authentication"]["type"] == DeviceAuthApiType.selfSigned.value:
        assert module1["authentication"]["x509Thumbprint"]["primaryThumbprint"] == module2["authentication"]["x509Thumbprint"]["primaryThumbprint"]
        assert module1["authentication"]["x509Thumbprint"]["secondaryThumbprint"] == module2["authentication"]["x509Thumbprint"]["secondaryThumbprint"]


def compare_module_twins(twin1, twin2):
    """Focus only on twin only props"""
    assert twin1["modelId"] == twin2["modelId"]
    assert len(twin1["properties"]["desired"]) == len(twin2["properties"]["desired"])
    for prop in twin1["properties"]["desired"]:
        if prop not in ["$metadata", "$version"]:
            assert prop in twin2["properties"]["desired"]
            assert twin1["properties"]["desired"][prop] == twin2["properties"]["desired"][prop]

    if "tags" in twin1:
        assert twin1["tags"] == twin2["tags"]


def compare_certs(cert1, cert2):
    assert cert1["name"] == cert2["name"]
    assert cert1["properties"]["certificate"] == cert2["properties"]["certificate"]
    assert cert1["properties"]["isVerified"] == cert2["properties"]["isVerified"]


def compare_endpoints(endpoints1, endpoints2, endpoint_type):
    for endpoint in endpoints1:
        target = None
        for ep in endpoints2:
            if endpoint["name"] == ep["name"]:
                target = ep
                break

        assert target
        assert endpoint["authenticationType"] == target["authenticationType"]
        assert endpoint["identity"] == target["identity"]
        assert endpoint["resourceGroup"] == target["resourceGroup"]
        assert endpoint["subscriptionId"] == target["subscriptionId"]

        # Ignore keys for connection string
        if endpoint.get("connectionString"):
            if endpoint_type == "storageContainers":
                cstring_props = parse_storage_container_connection_string(endpoint["connectionString"])
                target_props = parse_storage_container_connection_string(target["connectionString"])
                cstring_props.pop("AccountKey")
                target_props.pop("AccountKey")
                assert cstring_props == target_props
            else:
                cstring_props = parse_iot_hub_message_endpoint_connection_string(endpoint["connectionString"])
                target_props = parse_iot_hub_message_endpoint_connection_string(target["connectionString"])
                cstring_props.pop("SharedAccessKey")
                target_props.pop("SharedAccessKey")
                assert cstring_props == target_props

        if "entityPath" in endpoint:
            assert endpoint["entityPath"] == target["entityPath"]

        if endpoint_type == "storageContainers":
            assert endpoint["maxChunkSizeInBytes"] == target["maxChunkSizeInBytes"]
            assert endpoint["batchFrequencyInSeconds"] == target["batchFrequencyInSeconds"]
            assert endpoint["containerName"] == target["containerName"]
            assert endpoint["encoding"] == target["encoding"]
            assert endpoint["fileNameFormat"] == target["fileNameFormat"]


def compare_routes(routes1, routes2):
    assert len(routes1) == len(routes2)

    for route in routes1:
        target = None
        for r in routes2:
            if route["name"] == r["name"]:
                target = r
                break

        assert target
        assert route["condition"] == target["condition"]
        assert route["endpointNames"] == target["endpointNames"]
        assert route["isEnabled"] == target["isEnabled"]
        assert route["source"] == target["source"]