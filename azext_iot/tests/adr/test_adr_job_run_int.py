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
* ``run cancel``  — clean error for a non-existent run

Scheduling creates a run resource independently of successful execution.
This fixture deliberately has no linked Software Update endpoint, so the
immediate run must fail with ``AduEndpointNotLinked``. The smoke test covers:

* Run resource creation, explicit/custom waits, and failed-execution reporting.
* Run show, list, summary, results, and deletion without a deployment fixture.
* Verify ``run show`` on a non-existent run returns a clean error.
* Verify ``run results`` on a non-existent run returns a clean error.
* Verify ``run cancel`` on a non-existent run returns a clean error.

The full results-pagination behavior (single page, nextLink follow-through,
HTTP error propagation, lazy generator) is covered exhaustively by
:mod:`azext_iot.tests.adr.test_adr_job_run_unit`.

A healthy Active run needs devices in a controllable rollout, which this suite
does not provision; run cancellation is covered by unit tests and the
non-existent-run negative here.
"""

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper, CleanupLedger
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr._readiness import delete_test_namespace as _delete_test_namespace
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


_TERMINAL_RUN_STATUSES = ("Succeeded", "Failed", "TimedOut", "Canceled")
_RUN_WAIT_TIMEOUT = 120


def _wait_for_run_statuses(scenario, scope, statuses):
    """Bound execution polling separately from successful ARM provisioning."""
    choices = ", ".join(f"'{status}'" for status in statuses)
    scenario.cmd(
        f"iot adr ns job run wait {scope} --timeout {_RUN_WAIT_TIMEOUT} --interval 10 "
        f'--custom "contains([{choices}], properties.status)"'
    )
    run = scenario.cmd(f"iot adr ns job run show {scope}").get_output_in_json()
    properties = run["properties"]
    assert properties["provisioningState"] == "Succeeded", properties
    assert properties["status"] in statuses, properties
    return run


def _delete_test_run(scenario, scope):
    """Delete only an owned, scheduled or terminal run; never cancel as cleanup."""
    _wait_for_run_statuses(scenario, scope, ("Scheduled", *_TERMINAL_RUN_STATUSES))
    scenario.cmd(f"iot adr ns job run delete {scope} -y")


@pytest.mark.usefixtures("set_cwd")
class TestADRJobRunSurface(ADRFullInfraHelper, ADRLiveScenarioTest):

    def test_adr_job_run_surface_smoke(self):
        _log(LogKind.TEST, "test_adr_job_run_surface_smoke")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        job_name = _generate_job_name()

        with CleanupLedger() as cleanup:
            with timed_step("Setup ❯ Namespace + Group + Job"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                )
                cleanup.register(
                    "namespace",
                    lambda: _delete_test_namespace(
                        self, namespace_name, rg, jobs=(job_name,), groups=(group_name,),
                    ),
                )
                self.cmd(
                    f"iot adr ns group create -n {group_name} --ns {namespace_name} -g {rg} "
                    f'--query-string "*"'
                )
                cleanup.register(
                    "group",
                    lambda: self.cmd(
                        f"iot adr ns group delete -n {group_name} --ns {namespace_name} -g {rg} -y"
                    ),
                )
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--type SoftwareUpdate "
                    f"--target-group-name {group_name} "
                    f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0"
                )
                cleanup.register(
                    "job",
                    lambda: self.cmd(
                        f"iot adr ns job delete -n {job_name} --ns {namespace_name} -g {rg} -y"
                    ),
                )

            with timed_step("Step 1 ❯ Schedule the job (immediate)"):
                generated = self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                cleanup.register(
                    "generated run",
                    lambda: _delete_test_run(
                        self, f"-n {generated['name']} --job-name {job_name} --ns {namespace_name} -g {rg}"
                    ),
                )
                # --run-name is optional; a UTC-timestamped name is generated.
                assert generated["name"].startswith("run-")
                self.cmd(
                    "iot adr ns job run wait "
                    f"-n {generated['name']} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg} "
                    "--created --timeout 300 --interval 10"
                )
                _log(LogKind.OK, "generated run name=%s", generated["name"])

            with timed_step("Neg ❯ Missing Software Update link fails execution, not creation"):
                wait_command = (
                    f"iot adr ns job run wait -n {generated['name']} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg} --timeout 300 --interval 10"
                )
                self.cmd(wait_command + " --custom \"properties.status == 'Failed'\"")
                failed_run = self.cmd(
                    f"iot adr ns job run show -n {generated['name']} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert failed_run["properties"]["provisioningState"] == "Succeeded"
                assert failed_run["properties"]["status"] == "Failed"
                assert failed_run["properties"]["error"]["code"] == "AduEndpointNotLinked"
                with pytest.raises(AzureResponseError, match="terminal status 'Failed'"):
                    self.cmd(wait_command)

            with timed_step("Step 1b ❯ Explicit run name, summary, results, delete"):
                explicit_run = f"run-explicit-{generate_generic_id()[:8]}"
                created_run = self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg} --run-name {explicit_run}"
                ).get_output_in_json()
                cleanup.register(
                    "explicit run",
                    lambda: _delete_test_run(
                        self, f"-n {explicit_run} --job-name {job_name} --ns {namespace_name} -g {rg}"
                    ),
                )
                assert created_run["name"] == explicit_run
                # This is the same deliberately unlinked setup, not a healthy
                # rollout. Wait for failure rather than racing cancel/delete.
                failed_explicit = _wait_for_run_statuses(
                    self,
                    f"-n {explicit_run} --job-name {job_name} --ns {namespace_name} -g {rg}",
                    ("Failed",),
                )
                assert failed_explicit["properties"]["error"]["code"] == "AduEndpointNotLinked"

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

                _delete_test_run(
                    self, f"-n {explicit_run} --job-name {job_name} --ns {namespace_name} -g {rg}"
                )
                cleanup.dismiss("explicit run")
                self.cmd(
                    f"iot adr ns job run show -n {explicit_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "explicit run lifecycle complete")

            with timed_step("Step 2 ❯ job run list includes the generated run"):
                runs = self.cmd(
                    f"iot adr ns job run list --ns {namespace_name} -g {rg} "
                    f"--jn {job_name} --order-by \"status asc\""
                ).get_output_in_json()
                assert isinstance(runs, list), (
                    f"job run list should return list, got {type(runs)}"
                )
                assert generated["name"] in [run["name"] for run in runs]
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
