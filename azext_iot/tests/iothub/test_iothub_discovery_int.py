# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.discovery import (
    IotHubDiscovery,
    PRIVILEDGED_ACCESS_RIGHTS_SET,
)
from azext_iot.tests import IoTLiveScenarioTest
from ..settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC, Setting

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg


class TestIoTHubDiscovery(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDiscovery, self).__init__(test_case, LIVE_HUB, LIVE_RG)
        self.cmd_shell = Setting()
        setattr(self.cmd_shell, "cli_ctx", self.cli_ctx)
        self.desired_policy_name = "iothubowner"

    def test_iothub_discovery(self):
        discovery = IotHubDiscovery(self.cmd_shell)

        iothub = discovery.find_iothub(hub_name=LIVE_HUB)
        assert iothub.name == LIVE_HUB

        auto_policy = discovery.find_policy(hub_name=LIVE_HUB, rg=LIVE_RG).as_dict()
        rights_set = set(auto_policy["rights"].split(", "))
        assert rights_set == PRIVILEDGED_ACCESS_RIGHTS_SET

        # Assumption - Test Iothub includes the vanilla iothubowner policy
        desired_policy = discovery.find_policy(
            hub_name=LIVE_HUB, rg=LIVE_RG, policy_name=self.desired_policy_name
        ).as_dict()
        assert desired_policy["key_name"] == self.desired_policy_name

        policies = discovery.get_policies(hub_name=LIVE_HUB, rg=LIVE_RG)
        assert len(policies)

        # Example for leveraging discovery to build cstring for every policy on target IotHub
        cstrings = [discovery._build_target(iothub=iothub, policy=p)["cs"] for p in policies]
        assert len(cstrings)

        sub_hubs = discovery.get_iothubs()
        assert sub_hubs

        filtered_sub_hubs = [
            hub for hub in sub_hubs if hub.as_dict()["name"] == LIVE_HUB
        ]
        assert filtered_sub_hubs

        rg_hubs = discovery.get_iothubs(rg=LIVE_RG)
        assert rg_hubs

        filtered_rg_hubs = [hub for hub in rg_hubs if hub.as_dict()["name"] == LIVE_HUB]
        assert filtered_rg_hubs

        assert len(rg_hubs) <= len(sub_hubs)

    def test_iothub_targets(self):
        discovery = IotHubDiscovery(self.cmd_shell)

        cs_target1 = discovery.get_target_by_cstring(self.connection_string)
        assert_target(cs_target1, True)

        cs_target2 = discovery.get_target(hub_name=None, login=self.connection_string)
        assert_target(cs_target2, True)

        auto_target = discovery.get_target(hub_name=LIVE_HUB)
        assert_target(auto_target, rg=LIVE_RG)

        auto_target = discovery.get_target(hub_name=LIVE_HUB, rg=LIVE_RG)
        assert_target(auto_target, rg=LIVE_RG)

        desired_target = discovery.get_target(
            hub_name=LIVE_HUB, policy_name=self.desired_policy_name, include_events=True
        )
        assert_target(desired_target, rg=LIVE_RG, include_events=True)

        sub_targets = discovery.get_targets()
        [assert_target(tar) for tar in sub_targets]

        rg_targets = discovery.get_targets(rg=LIVE_RG, include_events=True)
        [assert_target(tar, rg=LIVE_RG, include_events=True) for tar in rg_targets]

        assert len(rg_targets) <= len(sub_targets)


def assert_target(target: dict, by_cstring=False, include_events=False, **kwargs):
    assert target["cs"]
    assert target["policy"]
    assert target["primarykey"]
    assert target["entity"]

    if not by_cstring:
        assert target["secondarykey"]
        assert target["subscription"]

        if "rg" in kwargs:
            assert target["resourcegroup"] == kwargs["rg"]

        assert target["location"]
        assert target["sku_tier"]
        assert target["secondarykey"]

        if include_events:
            assert target["events"]
            events = target["events"]
            assert events["endpoint"]
            assert events["partition_count"]
            assert events["path"]
            assert events["partition_ids"]
            assert isinstance(events["partition_ids"], list)
