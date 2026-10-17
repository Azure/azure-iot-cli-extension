# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import policy_snapshot
from azext_iot.tests.iothub import IoTLiveScenarioTest


class TestHubCommandHappyPaths(IoTLiveScenarioTest):
    def _command(self, operation, *, output=True):
        name_option = "--hub-name" if operation.split()[0] in ("policy", "consumer-group") else "--name"
        result = self.cmd(
            f"iot hub {operation} {name_option} {self.entity_name} -g {self.entity_rg}"
        )
        return result.get_output_in_json() if output else None

    def _enrichments(self):
        routing = self._command("show")["properties"]["routing"]
        return {item["key"]: item for item in routing.get("enrichments") or []}

    def test_policy_lifecycle(self):
        name = generate_generic_id()
        baseline = policy_snapshot(self._command("policy list"))
        try:
            self._command(f"policy create --name {name} --permissions RegistryRead ServiceConnect", output=False)
            created = policy_snapshot(self._command("policy list"))
            assert set(created) == set(baseline) | {name}
            assert {key: value for key, value in created.items() if key != name} == baseline
            assert created[name][0] == {"RegistryRead", "ServiceConnect"}
            initial = policy_snapshot([self._command(f"policy show --name {name}")])
            assert initial[name] == created[name]
            assert policy_snapshot(self._command("policy list")) == created

            renewed = policy_snapshot([self._command(f"policy renew-key --name {name} --renew-key primary")])
            assert renewed[name][0] == initial[name][0]
            assert renewed[name][1] != initial[name][1]
            assert renewed[name][2] == initial[name][2]
            assert policy_snapshot([self._command(f"policy show --name {name}")]) == renewed
            assert policy_snapshot(self._command("policy list")) == {**baseline, **renewed}
            self._command(f"policy delete --name {name}", output=False)
            assert policy_snapshot(self._command("policy list")) == baseline
            assert self._command("show")["properties"]["disableLocalAuth"] is True
        finally:
            if name in policy_snapshot(self._command("policy list")):
                self._command(f"policy delete --name {name}", output=False)

    def test_consumer_group_reads(self):
        name = generate_generic_id()
        baseline = {item["name"] for item in self._command("consumer-group list")}
        try:
            created = self._command(f"consumer-group create --name {name}")
            shown = self._command(f"consumer-group show --name {name}")
            assert shown["name"] == name
            assert shown["id"] == created["id"]
            listed = self._command("consumer-group list")
            assert {item["name"] for item in listed} == baseline | {name}
            assert [item["id"] for item in listed if item["name"] == name] == [created["id"]]
            self._command(f"consumer-group delete --name {name}", output=False)
            assert {item["name"] for item in self._command("consumer-group list")} == baseline
        finally:
            if name in {item["name"] for item in self._command("consumer-group list")}:
                self._command(f"consumer-group delete --name {name}", output=False)

    def test_enrichment_update_delete(self):
        key = generate_generic_id()
        baseline = self._enrichments()
        try:
            self._command(f"message-enrichment create --key {key} --value initial --endpoints events", output=False)
            updated = self._command(f"message-enrichment update --key {key} --value replacement --endpoints events")
            expected = {"key": key, "value": "replacement", "endpointNames": ["events"]}
            returned = {item["key"]: item for item in updated["properties"]["routing"]["enrichments"]}
            assert returned == {**baseline, key: expected}
            readback = {item["key"]: item for item in self._command("message-enrichment list")}
            assert readback == returned
            self._command(f"message-enrichment delete --key {key}", output=False)
            assert self._enrichments() == baseline
            assert self._command("show")["properties"]["disableLocalAuth"] is True
        finally:
            if key in self._enrichments():
                self._command(f"message-enrichment delete --key {key}", output=False)

    def test_skus_quota_and_stats(self):
        skus = self._command("list-skus")
        standard = [item for item in skus if item["sku"]["name"] == "S1"]
        assert len(standard) == 1
        assert standard[0]["capacity"]["minimum"] <= 1 <= standard[0]["capacity"]["maximum"]
        metrics = {item["name"]: item for item in self._command("show-quota-metrics")}
        assert metrics["TotalDeviceCount"]["maxValue"] == "Unlimited"
        assert metrics["TotalDeviceCount"]["currentValue"] >= 0
        stats = self._command("show-stats")
        assert stats["totalDeviceCount"] == stats["enabledDeviceCount"] + stats["disabledDeviceCount"]
        assert stats["enabledDeviceCount"] >= 0 and stats["disabledDeviceCount"] >= 0

    @pytest.mark.timeout(3600, func_only=False)
    @pytest.mark.usefixtures("fixture_isolated_hub")
    def test_manual_failover(self):
        before = self._command("show")
        locations = before["properties"]["locations"]
        primary = [item["location"] for item in locations if item["role"].lower() == "primary"]
        secondary = [item["location"] for item in locations if item["role"].lower() == "secondary"]
        assert len(primary) == len(secondary) == 1, "The admitted region has no configured Hub failover pair."
        assert primary[0] != secondary[0]
        failed_over = self._command("manual-failover")
        readback = self._command("show")
        for result in (failed_over, readback):
            assert result["id"] == before["id"]
            assert result["properties"]["hostName"] == before["properties"]["hostName"]
            assert result["properties"]["disableLocalAuth"] is True
            roles = {item["role"].lower(): item["location"] for item in result["properties"]["locations"]}
            assert roles == {"primary": secondary[0], "secondary": primary[0]}
