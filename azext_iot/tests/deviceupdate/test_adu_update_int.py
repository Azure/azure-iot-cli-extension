# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import pytest
from knack.log import get_logger
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import process_json_arg
from azext_iot.tests.conftest import get_context_path
from azext_iot.tests.deviceupdate.conftest import DEFAULT_ADU_RBAC_SLEEP_SEC, ADU_CLIENT_DTMI, ACCOUNT_RG
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import assign_role_assignment
from azext_iot.tests.settings import DynamoSettings
from datetime import datetime, timedelta, timezone
from typing import Dict, List

cli = EmbeddedCLI()

logger = get_logger(__name__)


settings = DynamoSettings(opt_env_set=["azext_iot_adu_it_skip_logcollection"])
SKIP_LOG_COLLECTION = settings.env.azext_iot_adu_it_skip_logcollection


#  Instance creation and manipulation takes an extra long time overhead.
#  Therefore we are aiming to provision instance resources conservatively.


pytestmark = pytest.mark.adu_infrastructure(
    location="westus2",
    instance_count=1,
    instance_diagnostics=True,
    instance_diagnostics_user_storage=True)


def test_instance_update_lifecycle(provisioned_instances_module: Dict[str, dict]):
    account_name = list(provisioned_instances_module.keys())[0]
    instance_name = list(provisioned_instances_module[account_name].keys())[0]
    storage_account_id = provisioned_instances_module[
        account_name][instance_name]["diagnosticStorageProperties"]["resourceId"]
    _assign_rbac_if_needed(account_name)
    # Upload simple manifest to storage blob
    simple_manifest_file = "simple_apt_manifest_v5.json"
    simple_manifest_artifact1 = "libcurl4-doc-apt-manifest.json"

    file_paths = []
    for name in [simple_manifest_file, simple_manifest_artifact1]:
        file_paths.append(get_context_path(__file__, "manifests", name))
    file_uris = _stage_update_assets(file_paths, storage_account_id=storage_account_id)
    simple_manifest_id = process_json_arg(file_paths[0])["updateId"]

    # No object is returned upon successful import.
    simple_manifest_friendly_name = f"simple_{generate_generic_id()}"
    assert cli.invoke(
        f"iot du update import -n {account_name} -i {instance_name} --friendly-name {simple_manifest_friendly_name} "
        f"--url {file_uris[0]} --file filename={simple_manifest_artifact1} url={file_uris[1]}"
    ).success()
    show_simple_update = cli.invoke(
        f"iot du update show -n {account_name} -i {instance_name} --update-name {simple_manifest_id['name']} "
        f"--update-provider {simple_manifest_id['provider']} --update-version {simple_manifest_id['version']} "
    ).as_json()
    assert show_simple_update["updateId"]["name"] == simple_manifest_id["name"]
    assert show_simple_update["updateId"]["provider"] == simple_manifest_id["provider"]
    assert show_simple_update["updateId"]["version"] == simple_manifest_id["version"]
    assert show_simple_update["friendlyName"] == simple_manifest_friendly_name

    list_updates = cli.invoke(f"iot du update list -n {account_name} -i {instance_name}").as_json()
    assert len(list_updates) == 1
    assert list_updates[0]["updateId"]["name"] == simple_manifest_id["name"]
    list_updates_by_provider = cli.invoke(
        f"iot du update list -n {account_name} -i {instance_name} --by-provider"
    ).as_json()
    assert simple_manifest_id["provider"] in list_updates_by_provider
    list_updates_by_name_cmd = (
        f"iot du update list -n {account_name} -i {instance_name} "
        f"--update-provider {simple_manifest_id['provider']}"
    )
    list_updates_by_name = cli.invoke(list_updates_by_name_cmd).as_json()
    assert simple_manifest_id["name"] in list_updates_by_name
    list_updates_by_version_cmd = (
        f"iot du update list -n {account_name} -i {instance_name} "
        f"--update-provider {simple_manifest_id['provider']} --update-name {simple_manifest_id['name']}"
    )
    list_updates_by_version = cli.invoke(list_updates_by_version_cmd).as_json()
    assert simple_manifest_id["version"] in list_updates_by_version

    list_update_files = cli.invoke(
        f"iot du update file list -n {account_name} -i {instance_name} --update-name {simple_manifest_id['name']} "
        f"--update-provider {simple_manifest_id['provider']} --update-version {simple_manifest_id['version']} "
    ).as_json()
    for update_file_id in list_update_files:
        assert (
            cli.invoke(
                f"iot du update file show -n {account_name} -i {instance_name} --un {simple_manifest_id['name']} "
                f"--up {simple_manifest_id['provider']} --uv {simple_manifest_id['version']} --ufid {update_file_id}"
            ).as_json()["fileId"]
            == update_file_id
        )

    # Device segment #

    # Fetch backing IoT Hub
    iothub_resource_id = cli.invoke(f"iot du instance show -n {account_name} -i {instance_name}").as_json()[
        "iotHubs"
    ][0]["resourceId"]
    iothub_name = iothub_resource_id.split("/")[-1]
    device_id = f"du_{generate_generic_id()}"
    device_group_id = f"cli_{generate_generic_id()}"
    device_manufacturer = "Contoso"
    assert cli.invoke(f"iot hub device-identity create -n {iothub_name} -d {device_id}").success()
    assert cli.invoke(
        f"iot hub device-twin update -n {iothub_name} -d {device_id} --tags '{json.dumps({'ADUGroup': device_group_id})}'"
    ).success()
    adu_device_state = {
        "deviceInformation": {
            "__t": "c",
            "manufacturer": device_manufacturer,
            "model": "Radio",
            "osName": "Linux",
            "swVersion": "0.0.0.0",
            "processorArchitecture": "x86-64",
            "processorManufacturer": "GenuineIntel",
            "totalMemory": 256000,
            "totalStorage": 2048000,
        },
        "deviceUpdate": {
            "__t": "c",
            "agent": {
                "state": 0,
                "deviceProperties": {
                    "manufacturer": device_manufacturer,
                    "model": "Radio",
                    "interfaceId": "dtmi:azure:iot:deviceUpdate;1",
                    "aduVer": "DU;agent/0.8.0-public-preview+20220202-182848",
                    "doVer": "DU;lib/v0.6.0+20211001.174458.c8c4051,DU;"
                    "agent/v0.6.0+20211001.174418.c8c4051,DU;plugin-apt/v0.4.0+20211001.174454.c8c4051",
                },
                "compatPropertyNames": "manufacturer,model",
            },
        },
    }

    assert cli.invoke(
        f"iot device simulate -n {iothub_name} -d {device_id} --irp '{json.dumps(adu_device_state)}' "
        f"--mi 1 --mc 1 --dtmi {ADU_CLIENT_DTMI}"
    ).success()
    assert cli.invoke(f"iot du device import -n {account_name} -i {instance_name}").success()
    list_devices = cli.invoke(f"iot du device list -n {account_name} -i {instance_name}").as_json()
    assert len(list_devices) == 1
    assert list_devices[0]["deviceId"] == device_id and list_devices[0]["groupId"] == device_group_id
    list_devices_filter = cli.invoke(
        f"iot du device list -n {account_name} -i {instance_name} --filter \"groupId eq '{device_group_id}'\""
    ).as_json()
    assert len(list_devices_filter) == 1 and list_devices_filter[0] == list_devices[0]
    show_device = cli.invoke(
        f"iot du device show -n {account_name} -i {instance_name} -d {device_id}"
    ).as_json()
    assert list_devices[0] == show_device
    device_class_id = show_device["deviceClassId"]

    show_compliance = cli.invoke(
        f"iot du device compliance show -n {account_name} -i {instance_name}"
    ).as_json()
    assert show_compliance["newUpdatesAvailableDeviceCount"] == 1
    assert show_compliance["totalDeviceCount"] == 1
    assert show_compliance["updatesInProgressDeviceCount"] == 0
    assert show_compliance["onLatestUpdateDeviceCount"] == 0

    # List device health requires --filter >:|
    list_device_health = cli.invoke(
        f"iot du device health list -n {account_name} -i {instance_name} "
        f"--filter \"deviceId eq '{device_id}'\""
    ).as_json()
    assert len(list_device_health) == 1
    assert list_device_health[0]["deviceId"] == device_id
    assert list_device_health[0]["digitalTwinModelId"] == ADU_CLIENT_DTMI
    assert len(list_device_health[0]["healthChecks"]) > 0

    # Device Classes

    list_device_classes = cli.invoke(
        f"iot du device class list -n {account_name} -i {instance_name}"
    ).as_json()
    assert len(list_device_classes) == 1
    assert list_device_classes[0]["deviceClassId"] == device_class_id
    assert list_device_classes[0]["bestCompatibleUpdate"]["updateId"]["name"] == show_simple_update["updateId"]["name"]
    assert list_device_classes[0]["bestCompatibleUpdate"]["updateId"]["provider"] == show_simple_update["updateId"]["provider"]
    assert list_device_classes[0]["bestCompatibleUpdate"]["updateId"]["version"] == show_simple_update["updateId"]["version"]
    assert list_device_classes[0]["bestCompatibleUpdate"]["friendlyName"] == show_simple_update["friendlyName"]

    list_device_class_subgroups = cli.invoke(
        f"iot du device class list -n {account_name} -i {instance_name} --group-id {device_group_id}"
    ).as_json()
    assert len(list_device_class_subgroups) == 1
    assert list_device_class_subgroups[0]["deviceClassId"] == device_class_id
    assert list_device_class_subgroups[0]["deviceCount"] == 1
    assert list_device_class_subgroups[0]["groupId"] == device_group_id

    list_device_class_subgroups_filter = cli.invoke(
        f"iot du device class list -n {account_name} -i {instance_name} --group-id {device_group_id} "
        f"--filter \"compatProperties/manufacturer eq '{device_manufacturer}'\""
    ).as_json()
    assert len(list_device_class_subgroups) == 1
    assert list_device_class_subgroups_filter[0] == list_device_class_subgroups[0]

    show_device_class = cli.invoke(
        f"iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id}"
    ).as_json()
    assert show_device_class == list_device_classes[0]
    class_friendly_name = generate_generic_id()
    update_device_class = cli.invoke(
        f"iot du device class update -n {account_name} -i {instance_name} --class-id {device_class_id} "
        f"--friendly-name {class_friendly_name}"
    ).as_json()
    assert update_device_class["friendlyName"] == class_friendly_name
    # Currently only friendlyName can be filtered on.
    list_device_class_filter = cli.invoke(
        f"iot du device class list -n {account_name} -i {instance_name} "
        f"--filter \"friendlyName eq '{class_friendly_name}'\""
    ).as_json()
    assert len(list_device_class_filter) == 1
    assert list_device_class_filter[0]["friendlyName"] == class_friendly_name

    device_class_subgroup_show_flags = ["--best-update", "--update-compliance"]
    show_device_class_template_cmd = (
        f"iot du device class show -n {account_name} -i {instance_name} --class-id {device_class_id} "
        f"# --group-id {device_group_id}"
    )

    for show_flag in device_class_subgroup_show_flags:
        # Error - flags for class requires group (device class subgroup op).
        assert not cli.invoke(show_device_class_template_cmd.replace("#", show_flag).split("--group-id")[0]).success()

    show_device_class_best_update = cli.invoke(
        show_device_class_template_cmd.replace("#", device_class_subgroup_show_flags[0])).as_json()
    show_device_class_best_update["deviceClassId"] == device_class_id
    show_device_class_best_update["update"]["updateId"]["name"] == show_simple_update["updateId"]["name"]
    show_device_class_best_update["update"]["updateId"]["provider"] == show_simple_update["updateId"]["provider"]
    show_device_class_best_update["update"]["updateId"]["version"] == show_simple_update["updateId"]["version"]
    show_device_class_best_update["update"]["friendlyName"] == show_simple_update["friendlyName"]

    show_device_class_installable_updates = cli.invoke(
        show_device_class_template_cmd.replace("#", "--installable-updates")).as_json()
    assert len(show_device_class_installable_updates) == 1
    assert show_device_class_installable_updates[0]["updateId"]["name"] == show_simple_update["updateId"]["name"]
    assert show_device_class_installable_updates[0]["updateId"]["provider"] == show_simple_update["updateId"]["provider"]
    assert show_device_class_installable_updates[0]["updateId"]["version"] == show_simple_update["updateId"]["version"]
    assert show_device_class_installable_updates[0]["friendlyName"] == show_simple_update["friendlyName"]

    show_device_class_update_compliance = cli.invoke(
        show_device_class_template_cmd.replace("#", device_class_subgroup_show_flags[1])).as_json()
    assert show_device_class_update_compliance["totalDeviceCount"] == 1
    assert show_device_class_update_compliance["newUpdatesAvailableDeviceCount"] == 1

    list_device_groups = cli.invoke(
        f"iot du device group list -n {account_name} -i {instance_name}"
    ).as_json()
    assert len(list_device_groups) == 1
    assert list_device_groups[0]["groupId"] == device_group_id
    assert list_device_groups[0]["groupType"] == "IoTHubTag"
    assert list_device_groups[0]["subgroupsWithNewUpdatesAvailableCount"] == 1
    assert list_device_groups[0]["subgroupsWithOnLatestUpdateCount"] == 0
    assert list_device_groups[0]["subgroupsWithUpdatesInProgressCount"] == 0

    list_device_groups_order_by = cli.invoke(
        f"iot du device group list -n {account_name} -i {instance_name} --order-by deviceCount"
    ).as_json()
    assert list_device_groups == list_device_groups_order_by

    device_group_show_flags = ["", "--best-updates", "--update-compliance"]
    show_device_group_template_cmd = (
        f"iot du device group show -n {account_name} -i {instance_name} --group-id {device_group_id} #"
    )
    show_device_group = cli.invoke(
        show_device_group_template_cmd.replace("#", device_group_show_flags[0])).as_json()
    assert list_device_groups[0] == show_device_group

    show_device_group_best_updates = cli.invoke(
        show_device_group_template_cmd.replace("#", device_group_show_flags[1])).as_json()
    assert len(show_device_group_best_updates) == 1
    assert show_device_group_best_updates[0]["deviceClassId"] == device_class_id
    assert show_device_group_best_updates[0]["groupId"] == device_group_id
    assert show_device_group_best_updates[0]["update"]["updateId"] == show_simple_update["updateId"]

    show_device_group_update_compliance = cli.invoke(
        show_device_group_template_cmd.replace("#", device_group_show_flags[2])).as_json()
    assert show_device_group_update_compliance == show_device_class_update_compliance

    if not SKIP_LOG_COLLECTION:
        log_collection_desc = generate_generic_id()
        log_collection_id = generate_generic_id()
        create_diagnostic_log_collect = cli.invoke(
            f"iot du device log collect -n {account_name} -i {instance_name} --log-collection-id {log_collection_id} "
            f"--description {log_collection_desc} --agent-id deviceId={device_id}").as_json()
        assert create_diagnostic_log_collect["logCollectionId"] == log_collection_id
        assert create_diagnostic_log_collect["description"] == log_collection_desc
        assert create_diagnostic_log_collect["deviceList"][0]["deviceId"] == device_id
        assert create_diagnostic_log_collect["status"] == "NotStarted"

        list_diagnostic_log = cli.invoke(
            f"iot du device log list -n {account_name} -i {instance_name}"
        ).as_json()
        assert len(list_diagnostic_log) == 1
        assert list_diagnostic_log[0]["logCollectionId"] == log_collection_id
        assert "status" in list_diagnostic_log[0]

        show_diagnostic_log_flags = ["", "--detailed"]
        for flag in show_diagnostic_log_flags:
            show_diagnostic_log = cli.invoke(
                f"iot du device log show -n {account_name} -i {instance_name} --log-collection-id {log_collection_id} "
                f"{flag}"
            ).as_json()
            show_diagnostic_log["logCollectionId"] == log_collection_id
            assert "status" in show_diagnostic_log
            if flag == "--detailed":
                # TODO: Not consistently working from the service
                # assert show_diagnostic_log["deviceStatus"][0]["deviceId"] == device_id
                # assert "logLocation" in show_diagnostic_log["deviceStatus"][0]
                pass

    start_date_time = datetime.now(tz=timezone.utc) + timedelta(hours=8)
    start_date_time_iso = start_date_time.isoformat()
    basic_deployment_id = f"deploy_{generate_generic_id()}"
    basic_create_deployment = cli.invoke(
        f"iot du device deployment create -n {account_name} -i {instance_name} --deployment-id {basic_deployment_id} "
        f"--group-id {device_group_id} --start-time {start_date_time_iso} --update-name {simple_manifest_id['name']} "
        f"--update-provider {simple_manifest_id['provider']} --update-version {simple_manifest_id['version']}").as_json()
    assert basic_create_deployment["deploymentId"] == basic_deployment_id

    assert basic_create_deployment["update"]["updateId"]
    for update_kpi in ["name", "provider", "version"]:
        assert (
            update_kpi in basic_create_deployment["update"]["updateId"]
            and basic_create_deployment["update"]["updateId"][update_kpi] == simple_manifest_id[update_kpi]
        )

    assert device_class_id in basic_create_deployment["deviceClassSubgroups"]
    assert basic_create_deployment["groupId"] == device_group_id
    assert basic_create_deployment["isRetried"] is None
    assert basic_create_deployment["isCanceled"] is None
    assert basic_create_deployment["startDateTime"] == start_date_time_iso

    list_deployment_class_id_opt = ["", f"--class-id {device_class_id}"]
    for class_id_opt in list_deployment_class_id_opt:
        list_deployments = cli.invoke(
            f"iot du device deployment list -n {account_name} -i {instance_name} "
            f"--group-id {device_group_id} {class_id_opt}").as_json()
        assert len(list_deployments) == 1
        assert list_deployments[0] == basic_create_deployment

    show_deployment_class_id_opt = ["", f"--class-id {device_class_id}"]
    show_deployment_status_opt = ["", "--status"]
    for class_id_opt in show_deployment_class_id_opt:
        for status_opt in show_deployment_status_opt:
            show_deployment = cli.invoke(
                f"iot du device deployment show -n {account_name} -i {instance_name} "
                f"--deployment-id {basic_deployment_id} "
                f"--group-id {device_group_id} {class_id_opt} {status_opt}").as_json()
            if not status_opt:
                assert show_deployment == list_deployments[0]
            else:
                assert show_deployment["groupId"] == device_group_id
                status_payload = show_deployment
                if not class_id_opt:
                    status_payload = status_payload["subgroupStatus"][0]
                assert status_payload["deploymentState"]
                assert status_payload["deviceClassId"] == device_class_id

    list_deployment_devices_flags = ["", f"--filter \"deviceId eq '{device_id}' and deviceState eq 'InProgress'\""]
    for flag in list_deployment_devices_flags:
        # Appears ADU agent is required to get results for this operation.
        # For now we will assert success vs returned attributes.
        assert cli.invoke(
            f"iot du device deployment list-devices -n {account_name} -i {instance_name} "
            f"--deployment-id {basic_deployment_id} --group-id {device_group_id} --class-id {device_class_id} {flag}").success()

    # Retry by class subgroup
    retry_deployment = cli.invoke(
        f"iot du device deployment retry -n {account_name} -i {instance_name} --deployment-id {basic_deployment_id} "
        f"--group-id {device_group_id} --class-id {device_class_id}").as_json()
    assert retry_deployment["deploymentId"] == basic_deployment_id
    assert retry_deployment["isRetried"] is True

    # Cancel by class subgroup
    cancel_deployment = cli.invoke(
        f"iot du device deployment cancel -n {account_name} -i {instance_name} --deployment-id {basic_deployment_id} "
        f"--group-id {device_group_id} --class-id {device_class_id}").as_json()
    assert cancel_deployment["deploymentId"] == basic_deployment_id
    assert cancel_deployment["isCanceled"] is True

    # Delete by group Id
    assert cli.invoke(
        f"iot du device deployment delete -n {account_name} -i {instance_name} --deployment-id {basic_deployment_id} "
        f"--group-id {device_group_id} -y").success()

    # Create deployment with cloud-initiated rollback policy and JIT start-time
    rollback_deployment_id = f"deployrollback_{generate_generic_id()}"
    failed_count = 10
    failed_percentage = 5
    rollback_create_deployment = cli.invoke(
        f"iot du device deployment create -n {account_name} -i {instance_name} "
        f"--deployment-id {rollback_deployment_id} --group-id {device_group_id} --update-name {simple_manifest_id['name']} "
        f"--update-provider {simple_manifest_id['provider']} --update-version {simple_manifest_id['version']} "
        f"--failed-count {failed_count} --failed-percentage {failed_percentage} "
        f"--rollback-update-name {simple_manifest_id['name']} "
        f"--rollback-update-provider {simple_manifest_id['provider']} "
        f"--rollback-update-version {simple_manifest_id['version']}").as_json()
    assert rollback_create_deployment["deploymentId"] == rollback_deployment_id
    assert rollback_create_deployment["startDateTime"]
    assert rollback_create_deployment["rollbackPolicy"]["failure"]["devicesFailedCount"] == failed_count
    assert rollback_create_deployment["rollbackPolicy"]["failure"]["devicesFailedPercentage"] == failed_percentage
    assert rollback_create_deployment["rollbackPolicy"]["update"]["updateId"] == simple_manifest_id

    assert cli.invoke(
        f"iot du device deployment cancel -n {account_name} -i {instance_name} "
        f"--deployment-id {rollback_deployment_id} --group-id {device_group_id} --class-id {device_class_id}").success()

    # Delete deployment by class subgroup.
    assert cli.invoke(
        f"iot du device deployment delete -n {account_name} -i {instance_name} "
        f"--deployment-id {rollback_deployment_id} --group-id {device_group_id} --class-id {device_class_id} -y").success()

    # Clean-up device class subgroup and group
    # TODO : Deleting a class Id does not work today, but you are able to delete a class subgroup.

    # First reset device state
    assert cli.invoke(
        f"iot hub device-twin update -n {iothub_name} -d {device_id} --tags '{json.dumps({'ADUGroup': None})}'"
    ).success()
    reset_device_state = {"deviceUpdate": None, "deviceInformation": None}
    assert cli.invoke(
        f"iot device simulate -n {iothub_name} -d {device_id} --irp '{json.dumps(reset_device_state)}' --mi 1 --mc 1"
    ).success()

    # Re-import device state
    assert cli.invoke(f"iot du device import -n {account_name} -i {instance_name}").success()

    # Delete device class subgroup
    assert cli.invoke(
        f"iot du device class delete -n {account_name} -i {instance_name} "
        f"--class-id {device_class_id} --group-id {device_group_id} -y"
    ).success()

    # Delete device group, assert fallback to $default
    assert cli.invoke(
        f"iot du device group delete -n {account_name} -i {instance_name} --group-id {device_group_id} -y").success()
    list_device_groups = cli.invoke(
        f"iot du device group list -n {account_name} -i {instance_name}"
    ).as_json()
    if list_device_groups:
        assert len(list_device_groups) == 1
        assert list_device_groups[0]["groupId"] == "$default"

    assert cli.invoke(
        f"iot du update delete -n {account_name} -i {instance_name} --update-name {simple_manifest_id['name']} "
        f"--update-provider {simple_manifest_id['provider']} --update-version {simple_manifest_id['version']} -y"
    ).success()
    list_updates = cli.invoke(f"iot du update list -n {account_name} -i {instance_name} -g {ACCOUNT_RG}").as_json()
    friendly_name_map = [r["friendlyName"] for r in list_updates]
    assert simple_manifest_friendly_name not in friendly_name_map


def test_instance_update_nested(provisioned_instances_module: Dict[str, dict]):
    account_name = list(provisioned_instances_module.keys())[0]
    instance_name = list(provisioned_instances_module[account_name].keys())[0]
    storage_account_id = provisioned_instances_module[
        account_name][instance_name]["diagnosticStorageProperties"]["resourceId"]
    _assign_rbac_if_needed(account_name)

    # Upload multi-reference update to storage blob
    surface15_root = "parent.importmanifest.json"
    surface15_script = "install.sh"
    surface15_leaf1 = "leaf1.importmanifest.json"
    surface15_leaf2 = "leaf2.importmanifest.json"
    surface15_action = "action.sh"

    cli = EmbeddedCLI()

    file_paths = []
    for name in [surface15_root, surface15_script, surface15_leaf1, surface15_leaf2, surface15_action]:
        file_paths.append(get_context_path(__file__, "manifests", "surface15", name))
    file_uris = _stage_update_assets(file_paths, storage_account_id=storage_account_id)
    complex_manifest_id = process_json_arg(file_paths[0])["updateId"]

    # No object is returned upon successful import.
    root_friendly_name = f"complex_{generate_generic_id()}"
    assert cli.invoke(
        f"iot du update import -n {account_name} -i {instance_name} --friendly-name {root_friendly_name} "
        f"--url {file_uris[0]} --file filename={surface15_script} url={file_uris[1]} --defer"
    ).success()
    leaf1_friendly_name = f"complex_{generate_generic_id()}"
    assert cli.invoke(
        f"iot du update import -n {account_name} -i {instance_name} --friendly-name {leaf1_friendly_name} "
        f"--url {file_uris[2]} --file filename={surface15_action} url={file_uris[-1]} --defer"
    ).success()
    # Omitting --defer will combine cached objects and send the combined payload to Azure.
    # We also have to re-init the embedded CLI because using `--defer` once maintains a to-cache state.
    cli = EmbeddedCLI()
    leaf2_friendly_name = f"complex_{generate_generic_id()}"
    assert cli.invoke(
        f"iot du update import -n {account_name} -i {instance_name} --friendly-name {leaf2_friendly_name} "
        f"--url {file_uris[3]} --file filename={surface15_action} url={file_uris[-1]}"
    ).success()
    list_updates = cli.invoke(f"iot du update list -n {account_name} -i {instance_name}").as_json()
    friendly_name_map = [r["friendlyName"] for r in list_updates]
    for friendly_name in [root_friendly_name, leaf1_friendly_name, leaf2_friendly_name]:
        assert friendly_name in friendly_name_map
    assert cli.invoke(
        f"iot du update delete -n {account_name} -i {instance_name} --update-name {complex_manifest_id['name']} "
        f"--update-provider {complex_manifest_id['provider']} --update-version {complex_manifest_id['version']} -y"
    ).success()
    list_updates = cli.invoke(f"iot du update list -n {account_name} -i {instance_name}").as_json()
    friendly_name_map = [r["friendlyName"] for r in list_updates]
    for friendly_name in [root_friendly_name, leaf1_friendly_name, leaf2_friendly_name]:
        assert friendly_name not in friendly_name_map


def test_instance_update_stage(provisioned_instances_module: Dict[str, dict]):
    from msrestazure.tools import parse_resource_id
    account_name = list(provisioned_instances_module.keys())[0]
    instance_name = list(provisioned_instances_module[account_name].keys())[0]
    storage_account_id = provisioned_instances_module[
        account_name][instance_name]["diagnosticStorageProperties"]["resourceId"]
    _assign_rbac_if_needed(account_name)
    parsed_storage_id = parse_resource_id(storage_account_id)

    # Stage & import simple update
    simple_manifest_file = "simple_apt_manifest_v5.json"
    simple_update_path = get_context_path(__file__, "manifests", simple_manifest_file)
    simple_update_id = process_json_arg(simple_update_path)["updateId"]
    simple_friendly_name = f"simple_{generate_generic_id()}"

    assert cli.invoke(
        f"iot du update stage -n {account_name} -i {instance_name} --friendly-name {simple_friendly_name} "
        f"--manifest-path '{simple_update_path}' --storage-account {parsed_storage_id['name']} --storage-container staged "
        f"--then-import").success()
    assert cli.invoke(
        f"iot du update show -n {account_name} -i {instance_name} --up {simple_update_id['provider']} "
        f"--un {simple_update_id['name']} --uv {simple_update_id['version']}").as_json()['friendlyName'] == simple_friendly_name

    # Stage & import multi-reference update
    surface15_root = "parent.importmanifest.json"
    surface15_leaf1 = "leaf1.importmanifest.json"
    surface15_leaf2 = "leaf2.importmanifest.json"
    complex_friendly_name = f"complex_{generate_generic_id()}"

    file_paths = []
    for name in [surface15_root, surface15_leaf1, surface15_leaf2]:
        file_paths.append(get_context_path(__file__, "manifests", "surface15", name))
    complex_update_parent_id = process_json_arg(file_paths[0])["updateId"]

    assert cli.invoke(
        f"iot du update stage -n {account_name} -i {instance_name} --friendly-name {complex_friendly_name} "
        f"--storage-account {parsed_storage_id['name']} --storage-container staged "
        f"--manifest-path '{file_paths[0]}' --manifest-path '{file_paths[1]}' --manifest-path '{file_paths[2]}' "
        f"--then-import"
    ).success()
    assert cli.invoke(
        f"iot du update show -n {account_name} -i {instance_name} --up {complex_update_parent_id['provider']} "
        f"--un {complex_update_parent_id['name']} --uv {complex_update_parent_id['version']}"
    ).as_json()['friendlyName'] == complex_friendly_name

    # Stage & import related files update but popen commands
    delta_manifest_file = "delta-related-files-manifest.json"
    delta_update_path = get_context_path(__file__, "manifests", "delta", delta_manifest_file)
    delta_update_id = process_json_arg(delta_update_path)["updateId"]
    delta_friendly_name = f"delta_{generate_generic_id()}"
    target_sub = cli.invoke("account show").as_json()["id"]

    # Also set explicit subscription & overwrite.
    command_payload = cli.invoke(
        f"iot du update stage -n {account_name} -i {instance_name} --friendly-name {delta_friendly_name} "
        f"--manifest-path '{delta_update_path}' --storage-account {parsed_storage_id['name']} --storage-container staged "
        f"--storage-subscription {target_sub} --overwrite"
    ).as_json()

    from subprocess import run, CalledProcessError
    try:
        run(command_payload["importCommand"], check=True, shell=True)
    except CalledProcessError as e:
        logger.error(e)

    assert cli.invoke(
        f"iot du update show -n {account_name} -i {instance_name} --up {delta_update_id['provider']} "
        f"--un {delta_update_id['name']} --uv {delta_update_id['version']}").as_json()['friendlyName'] == delta_friendly_name


def _stage_update_assets(file_paths: List[str], storage_account_id: str, storage_container: str = "updates") -> List[str]:
    from os import sep
    storage_account_cstring = cli.invoke(
        f"storage account show-connection-string --ids {storage_account_id}"
    ).as_json()["connectionString"]
    assert cli.invoke(
        f"storage container create --name {storage_container} --connection-string {storage_account_cstring}"
    ).success()

    file_sas_result = []
    for file_path in file_paths:
        file_name = file_path.split(sep)[-1]
        assert cli.invoke(
            f"storage blob upload -f '{file_path}' -c {storage_container} "
            f"--connection-string '{storage_account_cstring}' -n {file_name}"
        ).success()

        target_datetime_expiry = (datetime.utcnow() + timedelta(hours=3.0)).strftime("%Y-%m-%dT%H:%M:%SZ")
        file_sas_uri = cli.invoke(
            f"storage blob generate-sas --connection-string '{storage_account_cstring}' --container {storage_container} "
            f"--name {file_name} --permissions r --expiry {target_datetime_expiry} "
            f"--https-only --full-uri"
        ).as_json()
        file_sas_result.append(file_sas_uri)

    return file_sas_result


def _assign_rbac_if_needed(account_name: str):
    target_role = "Device Update Administrator"
    principal = cli.invoke("account show").as_json()
    account = cli.invoke(f"iot du account show -n {account_name}").as_json()
    assign_role_assignment(
        role=target_role,
        scope=account['id'],
        assignee=principal['user']['name'],
        wait=DEFAULT_ADU_RBAC_SLEEP_SEC)


def test_adu_set_config_defaults(provisioned_instances_module: Dict[str, dict]):
    account_name = list(provisioned_instances_module.keys())[0]
    instance_name = list(provisioned_instances_module[account_name].keys())[0]
    _assign_rbac_if_needed(account_name)

    # Set defaults.
    assert cli.invoke(f"config set defaults.adu_account={account_name} defaults.adu_instance={instance_name}").success()

    # Assert prior required params use defaults.
    account_result = cli.invoke("iot du account show").as_json()
    assert account_result["name"] == account_name
    assert cli.invoke("iot du device group list").success()
    assert cli.invoke(f"config set defaults.adu_group={ACCOUNT_RG}").success()
    assert cli.invoke("iot du device class list").success()

    # Unset defaults
    assert cli.invoke("config set defaults.adu_account='' defaults.adu_instance='' defaults.adu_group=''").success()

    # Expect failure due to missing required param value.
    assert not cli.invoke("iot du account show").success()
    assert not cli.invoke("iot du device group list").success()
