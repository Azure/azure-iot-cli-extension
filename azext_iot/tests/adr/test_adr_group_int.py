# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""ADR group lifecycle integration tests."""

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id


def _generate_group_name() -> str:
    return f"testgrp{generate_generic_id()[:8]}"


@pytest.mark.usefixtures("set_cwd")
class TestADRGroupLifecycle(ADRFullInfraHelper, CaptureOutputLiveScenarioTest):
    def test_adr_group_lifecycle(self):
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        group_created = False

        try:
            with timed_step("Setup ❯ Create namespace"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} "
                    f"--location {TEST_LOCATION}"
                )

            with timed_step("Step 1 ❯ Create and inspect group"):
                group_created = True
                created = self.cmd(
                    f"iot adr ns group create -n {group_name} "
                    f"--ns {namespace_name} -g {rg} "
                    '--query-string "*"'
                ).get_output_in_json()
                assert created["name"] == group_name
                assert created["properties"]["groupType"] == "RegistryDevice"
                assert created["properties"]["queryFilter"] == "*"
                # Group is a plain TrackedResource in 2026-11-02-preview: no identity.
                assert "identity" not in created
                # Create starts the initial membership calculation.
                self.cmd(
                    f"iot adr ns group wait -n {group_name} "
                    f"--ns {namespace_name} -g {rg}"
                )

                shown = self.cmd(
                    f"iot adr ns group show -n {group_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert shown["name"] == group_name
                listed = self.cmd(
                    f"iot adr ns group list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert group_name in [group["name"] for group in listed]

            with timed_step("Step 2 ❯ List members and count after initial calculation"):
                members = self.cmd(
                    f"iot adr ns group list-members -n {group_name} "
                    f"--ns {namespace_name} -g {rg} --page-size 1"
                ).get_output_in_json()
                assert isinstance(members, list)

                count = self.cmd(
                    f"iot adr ns group count -n {group_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert int(count or 0) == len(members)

            with timed_step("Step 3 ❯ Immediate manual refresh is rate-limited"):
                refresh_failure = self.cmd(
                    f"iot adr ns group refresh -n {group_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                assert refresh_failure.exit_code == 1

            with timed_step("Step 4 ❯ Update group"):
                updated = self.cmd(
                    f"iot adr ns group update -n {group_name} "
                    f"--ns {namespace_name} -g {rg} "
                    "--display-name 'Test group' --description 'integration test' "
                    "--tags env=ci"
                ).get_output_in_json()
                assert updated["properties"]["displayName"] == "Test group"
                assert updated["properties"]["description"] == "integration test"
                assert updated["tags"]["env"] == "ci"
                assert "identity" not in updated

            with timed_step("Step 5 ❯ Reject empty update"):
                self.cmd(
                    f"iot adr ns group update -n {group_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )

            with timed_step("Step 6 ❯ Delete group directly"):
                self.cmd(
                    f"iot adr ns group delete -n {group_name} "
                    f"--ns {namespace_name} -g {rg} -y"
                )
                group_created = False
                self.cmd(
                    f"iot adr ns group show -n {group_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                for action in ("refresh", "list-members", "count"):
                    self.cmd(
                        f"iot adr ns group {action} -n {group_name} "
                        f"--ns {namespace_name} -g {rg}",
                        expect_failure=True,
                    )
                _log(LogKind.OK, "Group lifecycle passed")
        finally:
            if group_created:
                _log(LogKind.STEP, "Cleanup ❯ Delete group")
                try:
                    self.cmd(
                        f"iot adr ns group delete -n {group_name} "
                        f"--ns {namespace_name} -g {rg} -y"
                    )
                except Exception as error:  # noqa: BLE001 - cleanup is best-effort
                    _log(LogKind.WARN, "Group cleanup failed: %s", error)
            self.cleanup_namespace(namespace_name, rg)
