# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.dps.providers.discovery import DPSDiscovery
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.tests.settings import Setting
import os

dps = os.environ.get("azext_iot_testdps")
dps_rg = os.environ.get("azext_iot_testrg")


class TestDPSDiscovery(LiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDiscovery, self).__init__(test_case)
        self.cmd_shell = Setting()
        setattr(self.cmd_shell, "cli_ctx", self.cli_ctx)
        self.desired_policy_name = "provisioningserviceowner"

    def test_iothub_discovery(self):
        discovery = DPSDiscovery(self.cmd_shell)

        iothub = discovery.find_resource(resource_name=dps)
        assert iothub.name == dps

        auto_policy = discovery.find_policy(resource_name=dps, rg=dps_rg).as_dict()
        assert auto_policy

        # Assumption - Test Iothub includes the vanilla iothubowner policy
        desired_policy = discovery.find_policy(
            resource_name=dps, rg=dps_rg, policy_name=self.desired_policy_name
        ).as_dict()
        assert desired_policy["key_name"] == self.desired_policy_name

        policies = discovery.get_policies(resource_name=dps, rg=dps_rg)
        assert len(policies)

        # Example for leveraging discovery to build cstring for every policy on target IotHub
        cstrings = [discovery._build_target(resource=iothub, policy=p)["cs"] for p in policies]
        assert len(cstrings)

        sub_hubs = discovery.get_resources()
        assert sub_hubs

        filtered_sub_hubs = [
            hub for hub in sub_hubs if hub.as_dict()["name"] == dps
        ]
        assert filtered_sub_hubs

        rg_hubs = discovery.get_resources(rg=dps_rg)
        assert rg_hubs

        filtered_rg_hubs = [hub for hub in rg_hubs if hub.as_dict()["name"] == dps]
        assert filtered_rg_hubs

        assert len(rg_hubs) <= len(sub_hubs)

    def test_iothub_targets(self):
        discovery = DPSDiscovery(self.cmd_shell)

        # cs_target1 = discovery.get_target_by_cstring(self.connection_string)
        # assert_target(cs_target1, True)

        # cs_target2 = discovery.get_target(resource_name=None, login=self.connection_string)
        # assert_target(cs_target2, True)

        auto_target = discovery.get_target(resource_name=dps)
        assert_target(auto_target, rg=dps_rg)

        auto_target = discovery.get_target(resource_name=dps, resource_group_name=dps_rg)
        assert_target(auto_target, rg=dps_rg)

        sub_targets = discovery.get_targets()
        [assert_target(tar) for tar in sub_targets]

        rg_targets = discovery.get_targets(resource_group_name=dps_rg)
        [assert_target(tar, rg=dps_rg) for tar in rg_targets]

        assert len(rg_targets) <= len(sub_targets)


def assert_target(target: dict, by_cstring=False, include_events=False, **kwargs):
    assert target["cs"]
    assert target["policy"]
    assert target["primarykey"]
    assert target["entity"]

    if not by_cstring:
        assert target["secondarykey"]
        assert target["subscription"] and target["subscription"] != "unknown"
