# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from unittest.mock import patch

from azext_iot.common.base_discovery import ResourceDiscoveryError
from azext_iot.iothub.providers.discovery import (
    IotHubDiscovery,
    PRIVILEDGED_ACCESS_RIGHTS_SET,
)
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.settings import Setting
from azext_iot.tests.iothub._integration_helpers import skip_hub_list_provider_error


class TestIoTHubDiscovery(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDiscovery, self).__init__(test_case)
        self.cmd_shell = Setting()
        setattr(self.cmd_shell, "cli_ctx", self.cli_ctx)
        self.desired_policy_name = "iothubowner"

    def test_iothub_discovery(self):
        discovery = IotHubDiscovery(self.cmd_shell)

        iothub = discovery.find_resource(resource_name=self.entity_name, rg=self.entity_rg)
        assert iothub["name"] == self.entity_name

        auto_policy = discovery.find_policy(resource_name=self.entity_name, rg=self.entity_rg)
        rights_set = set(auto_policy["rights"].split(", "))
        assert rights_set == PRIVILEDGED_ACCESS_RIGHTS_SET

        # Assumption - Test Iothub includes the vanilla iothubowner policy
        desired_policy = discovery.find_policy(
            resource_name=self.entity_name, rg=self.entity_rg, policy_name=self.desired_policy_name
        )
        assert desired_policy["keyName"] == self.desired_policy_name

        policies = discovery.get_policies(resource_name=self.entity_name, rg=self.entity_rg)
        assert len(policies)

        # Example for leveraging discovery to build cstring for every policy on target IotHub
        cstrings = [discovery._build_target(resource=iothub, policy=p)["cs"] for p in policies]
        assert len(cstrings)

    def test_iothub_discovery_lists(self):
        discovery = IotHubDiscovery(self.cmd_shell)
        with skip_hub_list_provider_error():
            sub_hubs = discovery.get_resources()
            rg_hubs = discovery.get_resources(rg=self.entity_rg)
        assert sub_hubs

        filtered_sub_hubs = [
            hub for hub in sub_hubs if hub["name"] == self.entity_name
        ]
        assert filtered_sub_hubs

        assert rg_hubs

        filtered_rg_hubs = [hub for hub in rg_hubs if hub["name"] == self.entity_name]
        assert filtered_rg_hubs

    def test_iothub_targets(self):
        discovery = IotHubDiscovery(self.cmd_shell)

        cs_target1 = discovery.get_target_by_cstring(self.connection_string)
        assert_target(cs_target1, True)

        cs_target2 = discovery.get_target(resource_name=None, login=self.connection_string)
        assert_target(cs_target2, True)

        cs_target2 = discovery.get_target(resource_name=self.host_name, resource_group_name=self.entity_rg)
        assert_target(cs_target2, True)

        auto_target = discovery.get_target(resource_name=self.entity_name, resource_group_name=self.entity_rg)
        assert_target(auto_target, rg=self.entity_rg)

        auto_target = discovery.get_target(resource_name=self.entity_name, resource_group_name=self.entity_rg)
        assert_target(auto_target, rg=self.entity_rg)

        desired_target = discovery.get_target(
            resource_name=self.entity_name, resource_group_name=self.entity_rg,
            policy_name=self.desired_policy_name, include_events=True
        )
        assert_target(desired_target, rg=self.entity_rg, include_events=True)

    def test_iothub_target_lists(self):
        discovery = IotHubDiscovery(self.cmd_shell)
        with skip_hub_list_provider_error():
            sub_targets = discovery.get_targets()
            rg_targets = discovery.get_targets(resource_group_name=self.entity_rg, include_events=True)
        [assert_target(tar) for tar in sub_targets]

        [assert_target(tar, rg=self.entity_rg, include_events=True) for tar in rg_targets]

        assert any(target["name"] == self.entity_name for target in sub_targets)
        assert any(target["name"] == self.entity_name for target in rg_targets)
        self._assert_missing_hostname_handling(discovery)

    def _assert_missing_hostname_handling(self, discovery):
        resource = discovery.find_resource(self.entity_name, rg=self.entity_rg)
        incomplete = deepcopy(resource)
        for field in ("hostName", "serviceHostName", "deviceHostName"):
            incomplete["properties"].pop(field, None)

        # Inject incomplete ARM metadata without racing actual Hub provisioning.
        with patch.object(IotHubDiscovery, "find_resource", return_value=incomplete):
            with self.assertRaises(ResourceDiscoveryError):
                self.cmd(
                    f"iot hub generate-sas-token --hub-name {self.entity_name} --resource-group {self.entity_rg}"
                )
            with self.assertRaises(ResourceDiscoveryError):
                discovery.get_target(self.entity_name, self.entity_rg, auth_type="login")
            with patch.object(discovery, "get_resources", return_value=[resource]):
                with self.assertLogs("cli.azext_iot.common.base_discovery", level="WARNING") as logs:
                    assert discovery.get_targets(resource_group_name=self.entity_rg, auth_type="login") == []
                assert any("No usable hostname" in message and self.entity_name in message for message in logs.output)

        assert_target(
            discovery.get_target(self.entity_name, self.entity_rg, auth_type="login"), rg=self.entity_rg
        )


def assert_target(target: dict, by_cstring=False, include_events=False, **kwargs):
    assert target["cs"]
    assert target["policy"]
    assert target["primarykey"]
    assert target["entity"]

    if not by_cstring:
        assert target["secondarykey"]
        assert target["subscription"] and target["subscription"] != "unknown"

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
