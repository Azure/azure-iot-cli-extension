# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR client-side validation negatives (cross-surface).

Every scenario in this module exercises argument validation that the providers
perform *before* issuing any service round trip — required-argument guards,
mutually-exclusive identity flags, and discriminator-specific requirements.

Because these commands fail client-side, they require neither pre-provisioned
ADR resources nor backend readiness: each ``self.cmd(...)`` is expected to fail
during command processing. They complement the lifecycle suites (happy paths)
by driving the rejection branches end-to-end through the CLI, mirroring the
provider unit tests at the command surface so the same lines are also covered
under integration.
"""

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import TEST_LOCATION, TEST_RG


_UAMI_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
)


@pytest.mark.usefixtures("set_cwd")
class TestADRValidationNegatives(ADRLiveScenarioTest):
    """Command-surface coverage of provider validation guards (no backend needed)."""

    def test_adr_validation_negatives(self):
        _log(LogKind.TEST, "test_adr_validation_negatives")
        rg = TEST_RG
        # Names need not resolve to real resources: each command fails during
        # argument validation, before the provider issues any service call.
        ns = "validation-ns-does-not-matter"

        # --- Namespace: outbound identity guards (resolved before the LRO) ---
        with timed_step("ns create ❯ outbound SAMI + UAMI together rejected"):
            self.cmd(
                f"iot adr ns create -n {ns} -g {rg} --location {TEST_LOCATION} "
                f"--omi-sa --omi-ua {_UAMI_ID}",
                expect_failure=True,
            )
        with timed_step("ns migrate ❯ non-asset resource ID rejected"):
            self.cmd(
                f"iot adr ns migrate -n {ns} -g {rg} "
                f"--resource-ids {_UAMI_ID}",
                expect_failure=True,
            )
        with timed_step("ns device ❯ removed alias is not registered"):
            self.cmd(
                f"iot adr ns device show -n mydev --ns {ns} -g {rg}",
                expect_failure=True,
            )

        # --- Certificate authority: update requires --tags ---
        with timed_step("ca update ❯ nothing-to-update rejected"):
            self.cmd(
                f"iot adr ns ca update -n myca --ns {ns} -g {rg}",
                expect_failure=True,
            )

        # --- Certificate policy: update requires tags or certificate validity ---
        with timed_step("ca policy update ❯ nothing-to-update rejected"):
            self.cmd(
                f"iot adr ns ca policy update -n mypolicy --ca myca --ns {ns} -g {rg}",
                expect_failure=True,
            )

        # --- Namespace resources: empty updates are rejected client-side ---
        with timed_step("namespace update ❯ nothing-to-update rejected"):
            self.cmd(
                f"iot adr ns update -n {ns} -g {rg}",
                expect_failure=True,
            )
        with timed_step("registry-device update ❯ nothing-to-update rejected"):
            self.cmd(
                f"iot adr ns registry-device update -n mydev --ns {ns} -g {rg}",
                expect_failure=True,
            )
        with timed_step("group update ❯ nothing-to-update rejected"):
            self.cmd(
                f"iot adr ns group update -n mygroup --ns {ns} -g {rg}",
                expect_failure=True,
            )

        with timed_step("group report ❯ group name required"):
            self.cmd(
                f"iot adr ns report generate --ns {ns} -g {rg} "
                "--report-type GroupBestUpdatesComplianceReport",
                expect_failure=True,
            )

        # --- Job: guards that fire before any service call ---
        # (The job_int suite covers the same guards, but only after a real
        # namespace+group setup; these run with no backend.)
        with timed_step("job create ❯ missing --target-group-name rejected"):
            self.cmd(
                f"iot adr ns job create -n myjob --ns {ns} -g {rg} "
                f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0",
                expect_failure=True,
            )
        with timed_step("job update ❯ nothing-to-update (no --tags) rejected"):
            self.cmd(
                f"iot adr ns job update -n myjob --ns {ns} -g {rg}",
                expect_failure=True,
            )
        with timed_step("job run create ❯ not a command; use job schedule"):
            self.cmd(
                f"iot adr ns job run create --job-name myjob --ns {ns} -g {rg}",
                expect_failure=True,
            )
        with timed_step("job schedule ❯ invalid ISO 8601 --scheduled-time rejected"):
            self.cmd(
                f"iot adr ns job schedule -n myjob --ns {ns} -g {rg} "
                f"--scheduled-time not-a-datetime",
                expect_failure=True,
            )
        with timed_step("job schedule ❯ timezone-naive --scheduled-time rejected"):
            self.cmd(
                f"iot adr ns job schedule -n myjob --ns {ns} -g {rg} "
                f"--scheduled-time 2026-11-02T12:00:00",
                expect_failure=True,
            )
        with timed_step("job run results ❯ unsupported --order-by option rejected"):
            self.cmd(
                f"iot adr ns job run results --job-name myjob --run-name myrun "
                f"--ns {ns} -g {rg} --order-by \"name asc\"",
                expect_failure=True,
            )

        # --- Group: query filter is required at create time ---
        with timed_step("group create ❯ missing --query-string rejected"):
            self.cmd(
                f"iot adr ns group create -n mygroup --ns {ns} -g {rg}",
                expect_failure=True,
            )

        _log(LogKind.OK, "All cross-surface validation negatives rejected client-side as designed")
