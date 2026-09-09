# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
)
from azext_iot.tests.generators import generate_generic_id


@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceWorkflow(
    ADRFullInfraHelper, CaptureOutputLiveScenarioTest
):
    def test_namespace_setup_tagged_plan_is_read_only(self):
        namespace_name = generate_adr_namespace_name()
        plan = self.cmd(
            "iot adr ns setup "
            f"-n {namespace_name} -g {TEST_RG} -l {TEST_LOCATION} "
            "--tags env=integration owner=adr-workflow "
            "--namespace-outbound-identity system-assigned "
            "--plan-only"
        ).get_output_in_json()
        namespace = next(
            item for item in plan["items"] if item["id"] == "namespace"
        )
        assert namespace["state"] == "Planned"
        assert namespace["details"]["tags"] == {
            "env": "integration",
            "owner": "adr-workflow",
        }

    def test_namespace_setup_check_and_resume(self):
        namespace_name = generate_adr_namespace_name()
        setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned"
        )
        try:
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            assert any(
                item["id"] == "namespace" and item["state"] == "Planned"
                for item in plan["items"]
            )

            applied = self.cmd(f"{setup} --yes").get_output_in_json()
            assert applied["state"] == "Succeeded"

            checked = self.cmd(
                f"iot adr ns check -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert checked["state"] == "Succeeded"
            assert checked["summary"]["NotConfigured"] == 3

            resumed = self.cmd(f"{setup} --yes").get_output_in_json()
            assert resumed["state"] == "Succeeded"
            assert any(
                item["id"] == "namespace"
                and item["state"] == "Satisfied"
                for item in resumed["items"]
            )
        finally:
            self.cmd(
                f"iot adr ns delete -n {namespace_name} -g {TEST_RG} --yes",
                checks=[],
            )

    def test_namespace_setup_links_dps(self):
        namespace_name = generate_adr_namespace_name()
        dps_name = generate_dps_name()
        dps = self.cmd(
            f"iot dps create -n {dps_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} --system-assigned-mi"
        ).get_output_in_json()
        setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned "
            f"--dps endpoint=dps-primary resource-id={dps['id']} "
            "identity=system-assigned"
        )
        try:
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            applied = self.cmd(f"{setup} --yes").get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link dps show -n dps-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()["linkingState"] == "Succeeded"
            assert linked

            checked = self.cmd(
                f"iot adr ns check -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert checked["state"] == "Succeeded"
        finally:
            self.cleanup_full_infra(
                resource_group=TEST_RG,
                namespace_name=namespace_name,
                dps_name=dps_name,
            )

    def test_namespace_setup_links_hub_after_dps(self):
        namespace_name = generate_adr_namespace_name()
        dps_name = generate_dps_name()
        hub_name = generate_hub_name()
        dps = self.cmd(
            f"iot dps create -n {dps_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} --system-assigned-mi"
        ).get_output_in_json()
        hub = self.cmd(
            f"iot hub create -n {hub_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} --sku S1 --system-assigned-mi "
            "--disable-local-auth true"
        ).get_output_in_json()
        dps_setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned "
            f"--dps endpoint=dps-primary resource-id={dps['id']} "
            "identity=system-assigned"
        )
        hub_setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"--hub endpoint=hub-primary resource-id={hub['id']} "
            "identity=system-assigned"
        )
        try:
            assert self.cmd(
                f"{dps_setup} --yes"
            ).get_output_in_json()["state"] == "Succeeded"
            plan = self.cmd(
                f"{hub_setup} --plan-only"
            ).get_output_in_json()
            assert plan["state"] == "Planned"
            applied = self.cmd(f"{hub_setup} --yes").get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link hub show -n hub-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert linked["linkingState"] == "Succeeded"
        finally:
            self.cleanup_full_infra(
                resource_group=TEST_RG,
                hub_name=hub_name,
                namespace_name=namespace_name,
                dps_name=dps_name,
            )

    def test_namespace_setup_links_software_updates(self):
        namespace_name = generate_adr_namespace_name()
        update_instance_name = f"testsu{generate_generic_id()[:8]}"
        subscription_id = self.get_subscription_id()
        update_instance_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{TEST_RG}"
            "/providers/Microsoft.DeviceUpdate/updateInstances/"
            f"{update_instance_name}"
        )
        setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned "
            "--software-updates endpoint=su-primary "
            f"resource-id={update_instance_id} identity=system-assigned "
            "create-if-missing=true"
        )
        try:
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            applied = self.cmd(f"{setup} --yes").get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link su show -n su-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert linked["linkingState"] == "Succeeded"
        finally:
            try:
                links = self.cmd(
                    f"iot adr ns link su list --ns {namespace_name} "
                    f"-g {TEST_RG}"
                ).get_output_in_json()
                if "su-primary" in {
                    item.get("name") for item in links or []
                }:
                    self.cmd(
                        f"iot adr ns link su delete -n su-primary "
                        f"--ns {namespace_name} -g {TEST_RG} --yes"
                    )
                else:
                    self.cmd(
                        "iot adr ns su instance delete "
                        f"-n {update_instance_name} -g {TEST_RG} --yes"
                    )
            except Exception:  # noqa: BLE001 - continue namespace cleanup
                pass
            self.cleanup_namespace(namespace_name, TEST_RG)
