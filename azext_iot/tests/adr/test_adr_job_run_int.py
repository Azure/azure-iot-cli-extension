# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR job run integration tests (P7).

Covers the ``iot adr ns job run`` surface:

* ``run list``    — by job or namespace, with optional filtering
* ``run show``    — single run by name
* ``run results`` — per-device target results, paginated manually via nextLink
* ``run cancel``  — cancellation LRO when an active run is available

Job runs are produced by the backend after a job is *scheduled* and the
scheduling window opens. Without a real software-update target deployed to a
real device population, the backend will typically not spawn any runs for a
test job. So the integration coverage here is intentionally minimal:

* Verify ``run list`` returns an **empty list** (not an error) for a
  freshly-scheduled job with no matching devices.
* Verify ``run show`` on a non-existent run returns a clean error.
* Verify ``run results`` on a non-existent run returns a clean error.
* Verify ``run cancel`` on a non-existent run returns a clean error.

The full results-pagination behavior (single page, nextLink follow-through,
HTTP error propagation, lazy generator) is covered exhaustively by
:mod:`azext_iot.tests.adr.test_adr_job_run_unit`.

Set all of ``azext_iot_adr_job_run_resource_group``,
``azext_iot_adr_job_run_namespace``, ``azext_iot_adr_job_run_job``, and
``azext_iot_adr_job_run_name`` to enable the pre-provisioned positive test.
The supplied run must be active and safe for the test to cancel.
"""

import os

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
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


def _generate_job_name() -> str:
    return f"testjob{generate_generic_id()[:8]}"


_PREPROVISIONED_RUN_ENV_VARS = (
    "azext_iot_adr_job_run_resource_group",
    "azext_iot_adr_job_run_namespace",
    "azext_iot_adr_job_run_job",
    "azext_iot_adr_job_run_name",
)
_PREPROVISIONED_RUN = {
    variable: os.getenv(variable, "").strip()
    for variable in _PREPROVISIONED_RUN_ENV_VARS
}


@pytest.mark.usefixtures("set_cwd")
class TestADRJobRunSurface(ADRFullInfraHelper, ADRLiveScenarioTest):

    def test_adr_job_run_surface_smoke(self):
        _log(LogKind.TEST, "test_adr_job_run_surface_smoke")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        job_name = _generate_job_name()

        try:
            with timed_step("Setup ❯ Namespace + Group + Job"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                )
                self.cmd(
                    f"iot adr ns group create -n {group_name} --ns {namespace_name} -g {rg} "
                    f'--query-string "*"'
                )
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--type SoftwareUpdate "
                    f"--target-group-name {group_name} "
                    f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0"
                )

            with timed_step("Step 1 ❯ Schedule the job (immediate)"):
                # Immediate schedule (no --scheduled-time) opens the window
                # right away. With zero devices in the group, backend will
                # typically produce zero runs.
                generated = self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                # --run-name is optional; a UTC-timestamped name is generated.
                assert generated["name"].startswith("run-")
                self.cmd(
                    "iot adr ns job run wait "
                    f"-n {generated['name']} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg} "
                    "--timeout 300 --interval 10"
                )
                _log(LogKind.OK, "generated run name=%s", generated["name"])

            with timed_step("Step 1b ❯ Explicit run name, summary, results, delete"):
                explicit_run = f"run-explicit-{generate_generic_id()[:8]}"
                created_run = self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg} --run-name {explicit_run}"
                ).get_output_in_json()
                assert created_run["name"] == explicit_run

                summary = self.cmd(
                    f"iot adr ns job run summary -n {explicit_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert isinstance(summary, dict)

                results = self.cmd(
                    f"iot adr ns job run results --jn {job_name} --rn {explicit_run} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert isinstance(results, list)

                self.cmd(
                    f"iot adr ns job run delete -n {explicit_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg} -y"
                )
                self.cmd(
                    f"iot adr ns job run show -n {explicit_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "explicit run lifecycle complete")

            with timed_step("Step 2 ❯ job run list returns a list (likely empty)"):
                runs = self.cmd(
                    f"iot adr ns job run list --ns {namespace_name} -g {rg} "
                    f"--jn {job_name} --order-by \"status asc\""
                ).get_output_in_json()
                assert isinstance(runs, list), (
                    f"job run list should return list, got {type(runs)}"
                )
                _log(LogKind.RESULT, "runs returned=%d", len(runs))

                namespace_runs = self.cmd(
                    f"iot adr ns job run list --ns {namespace_name} -g {rg} "
                    f"--filter \"status in ('Active', 'Succeeded')\""
                ).get_output_in_json()
                assert isinstance(namespace_runs, list)

            with timed_step("Neg ❯ run show on non-existent run fails cleanly"):
                self.cmd(
                    f"iot adr ns job run show --ns {namespace_name} -g {rg} "
                    f"--jn {job_name} -n does-not-exist-{generate_generic_id()[:8]}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "show non-existent run rejected")

            with timed_step("Neg ❯ run results on non-existent run fails cleanly"):
                self.cmd(
                    f"iot adr ns job run results --ns {namespace_name} -g {rg} "
                    f"--jn {job_name} --rn does-not-exist-{generate_generic_id()[:8]}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "results for non-existent run rejected")

            with timed_step("Neg ❯ run list on non-existent job fails cleanly"):
                self.cmd(
                    f"iot adr ns job run list --ns {namespace_name} -g {rg} "
                    f"--jn does-not-exist-{generate_generic_id()[:8]}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "list under non-existent job rejected")

            with timed_step("Neg ❯ run cancel on non-existent run fails cleanly"):
                self.cmd(
                    f"iot adr ns job run cancel --ns {namespace_name} -g {rg} "
                    f"--jn {job_name} --rn does-not-exist-{generate_generic_id()[:8]} -y",
                    expect_failure=True,
                )
                _log(LogKind.OK, "cancel for non-existent run rejected")

        finally:
            self.cleanup_namespace(namespace_name, rg)

    @pytest.mark.skipif(
        not all(_PREPROVISIONED_RUN.values()),
        reason=(
            "Set azext_iot_adr_job_run_resource_group, "
            "azext_iot_adr_job_run_namespace, azext_iot_adr_job_run_job, and "
            "azext_iot_adr_job_run_name to an active pre-provisioned run."
        ),
    )
    def test_adr_preprovisioned_job_run_positive(self):
        """Exercise every positive run command against an explicitly supplied active run."""
        rg = _PREPROVISIONED_RUN["azext_iot_adr_job_run_resource_group"]
        namespace_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_namespace"]
        job_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_job"]
        run_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_name"]

        self.cmd(
            f"iot adr ns job run wait --ns {namespace_name} -g {rg} "
            f"--jn {job_name} --rn {run_name} "
            "--custom \"properties.status != null\""
        )
        shown = self.cmd(
            f"iot adr ns job run show --ns {namespace_name} -g {rg} "
            f"--jn {job_name} --rn {run_name}"
        ).get_output_in_json()
        assert shown.get("name") == run_name

        results = self.cmd(
            f"iot adr ns job run results --ns {namespace_name} -g {rg} "
            f"--jn {job_name} --rn {run_name} --filter \"status eq 'Succeeded'\""
        ).get_output_in_json()
        assert isinstance(results, list)

        self.cmd(
            f"iot adr ns job run cancel --ns {namespace_name} -g {rg} "
            f"--jn {job_name} --rn {run_name} -y"
        )
