# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.testsdk.reverse_dependency import get_dummy_cli
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.tests.settings import Setting


def test_dps_discovery(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module["name"]
    dps_rg = provisioned_iot_dps_no_hub_module["resourceGroup"]
    cmd_shell = Setting()
    setattr(cmd_shell, "cli_ctx", get_dummy_cli())
    desired_policy_name = "provisioningserviceowner"
    discovery = DPSDiscovery(cmd_shell)

    resource = discovery.find_resource(resource_name=dps_name)
    assert resource.name == dps_name

    auto_policy = discovery.find_policy(resource_name=dps_name, rg=dps_rg).as_dict()
    assert auto_policy

    # Assumption - Test DPS includes the vanilla provisioningserviceowner policy
    desired_policy = discovery.find_policy(
        resource_name=dps_name, rg=dps_rg, policy_name=desired_policy_name
    ).as_dict()
    assert desired_policy["key_name"] == desired_policy_name

    policies = discovery.get_policies(resource_name=dps_name, rg=dps_rg)
    assert len(policies)

    # Example for leveraging discovery to build cstring for every policy on target DPS
    cstrings = [discovery._build_target(resource=resource, policy=p)["cs"] for p in policies]
    assert len(cstrings)

    sub_dps = discovery.get_resources()
    assert sub_dps

    filtered_sub_dps = [
        dps for dps in sub_dps if dps.as_dict()["name"] == dps_name
    ]
    assert filtered_sub_dps

    rg_dpss = discovery.get_resources(rg=dps_rg)
    assert rg_dpss

    filtered_rg_dpss = [dps for dps in rg_dpss if dps.as_dict()["name"] == dps_name]
    assert filtered_rg_dpss

    assert len(rg_dpss) <= len(sub_dps)


def test_dps_targets(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module["name"]
    dps_rg = provisioned_iot_dps_no_hub_module["resourceGroup"]
    dps_host_name = provisioned_iot_dps_no_hub_module['dps']['properties']['serviceOperationsHostName']
    cmd_shell = Setting()
    setattr(cmd_shell, "cli_ctx", get_dummy_cli())
    discovery = DPSDiscovery(cmd_shell)

    auto_target = discovery.get_target(resource_name=dps_name)
    assert_target(auto_target, rg=dps_rg)
    connection_string = auto_target["cs"]

    cs_target1 = discovery.get_target_by_cstring(connection_string)
    assert_target(cs_target1, True)

    cs_target2 = discovery.get_target(resource_name=None, login=connection_string)
    assert_target(cs_target2, True)

    cs_target1 = discovery.get_target_by_host_name(dps_host_name)
    assert_target(cs_target1, True)

    cs_target2 = discovery.get_target(resource_name=dps_host_name)
    assert_target(cs_target2, True)

    auto_target = discovery.get_target(resource_name=dps_name, resource_group_name=dps_rg)
    assert_target(auto_target, rg=dps_rg)

    sub_targets = discovery.get_targets()
    [assert_target(tar) for tar in sub_targets]

    rg_targets = discovery.get_targets(resource_group_name=dps_rg)
    [assert_target(tar, rg=dps_rg) for tar in rg_targets]

    assert len(rg_targets) <= len(sub_targets)


def assert_target(target: dict, by_cstring=False, **kwargs):
    assert target["cs"]
    assert target["policy"]
    assert target["primarykey"]
    assert target["entity"]

    if not by_cstring:
        assert target["secondarykey"]
        assert target["subscription"] and target["subscription"] != "unknown"
