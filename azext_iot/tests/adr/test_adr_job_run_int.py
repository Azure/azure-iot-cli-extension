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

Set all of ``azext_iot_adr_job_run_resource_group``,
``azext_iot_adr_job_run_namespace``, ``azext_iot_adr_job_run_job``, and
``azext_iot_adr_job_run_name`` to enable the pre-provisioned positive test.
The supplied run must be active and safe for the test to cancel.
Also set ``azext_iot_adr_job_run_target_group_id`` to its test-controlled target
group resource ID: this explicitly authorizes cancellation of this fixture only.
The fixture owner must hold compatible test devices in a controllable rollout;
the test does not provision devices, import content, or discover runs to cancel.
Read-only preflight requires a ready UpdateInstance, successful namespace SU link,
and the job's imported update. OnboardingUpdate is not this positive fixture.
"""

import os
import re
from shlex import quote
from urllib.parse import unquote

import pytest
from azure.cli.core.azclierror import AzureResponseError
from azure.core.exceptions import HttpResponseError
from msrestazure.tools import parse_resource_id

from azext_iot.adr.common import SU_ENDPOINT_TYPE
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper, CleanupLedger, wait_for_condition
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


def _delete_test_namespace(scenario, namespace_name, resource_group):
    """Allow the observed child-visibility delay after owned child cleanup."""
    scope = f"--namespace {quote(namespace_name)} -g {quote(resource_group)}"

    def delete_when_empty():
        try:
            scenario.cmd(f"iot adr ns delete {scope} -y")
        except HttpResponseError as error:
            if getattr(error.error, "code", None) != "CannotDeleteResource":
                raise
            # Live OnboardingUpdate cleanup returned CannotDeleteResource for
            # an already deleted job. Never retry generic Conflict, or mask a
            # remaining child / failed child cleanup. These reads delete nothing.
            jobs = scenario.cmd(f"iot adr ns job list {scope}").get_output_in_json()
            groups = scenario.cmd(f"iot adr ns group list {scope}").get_output_in_json()
            if jobs != [] or groups != []:
                raise
            _log(
                LogKind.WARN,
                "Namespace deletion reports children, but job/group lists are empty; retrying within the cleanup deadline",
            )
            return False
        return True

    wait_for_condition(
        delete_when_empty,
        bool,
        description=f"Delete test namespace '{namespace_name}' after child cleanup",
        timeout=_RUN_WAIT_TIMEOUT,
        interval=10,
        is_retryable_error=lambda _error: False,
        describe=lambda _value: "CannotDeleteResource despite empty job/group lists",
    )


def _cancel_active_run(scenario, scope):
    """Cancel once, then verify execution; a 202/204 or completed LRO is not proof."""
    run = scenario.cmd(f"iot adr ns job run show {scope}").get_output_in_json()
    properties = run["properties"]
    assert properties["provisioningState"] == "Succeeded", properties
    # The SDK exposes begin_cancel -> LROPoller[None], but no cancelability
    # matrix. Restrict this fixture to Active; do not guess that Scheduled or
    # every nonterminal state is cancelable. A racing Conflict must propagate.
    assert properties["status"] == "Active", properties
    assert not properties.get("error"), properties
    scenario.cmd(f"iot adr ns job run cancel {scope} -y --no-wait")
    canceled = _wait_for_run_statuses(scenario, scope, _TERMINAL_RUN_STATUSES)
    assert canceled["properties"]["status"] == "Canceled", canceled["properties"]


def _assert_software_update_fixture_ready(scenario, namespace_scope, job_name, target_id):
    """Read-only prerequisite checks; safety/controllability is the owner's opt-in."""
    namespace = scenario.cmd(f"iot adr ns show {namespace_scope}").get_output_in_json()
    assert namespace["properties"]["provisioningState"] == "Succeeded"
    job = scenario.cmd(
        f"iot adr ns job show -n {quote(job_name)} {namespace_scope}"
    ).get_output_in_json()
    properties = job["properties"]
    assert properties["provisioningState"] == "Succeeded"
    assert properties["jobType"] == "SoftwareUpdate"
    assert properties["target"]["resourceId"].casefold() == target_id.casefold()

    endpoints = namespace["properties"].get("updating", {}).get("endpoints", {})
    su_links = [
        endpoint for endpoint in endpoints.values()
        if endpoint.get("endpointType", "").casefold() == SU_ENDPOINT_TYPE.casefold()
    ]
    assert len(su_links) == 1, "Exactly one namespace SU link is required"
    link = su_links[0]
    assert link.get("linkingState") == "Succeeded", link
    assert link.get("serviceAddress"), "SU link has no usable data-plane address"
    instance_id = link["resourceId"]
    instance = parse_resource_id(instance_id)
    shown = scenario.cmd(
        f"iot adr ns su instance show -n {quote(instance['name'])} "
        f"-g {quote(instance['resource_group'])} --subscription {quote(instance['subscription'])}"
    ).get_output_in_json()
    assert shown["id"].casefold() == instance_id.casefold()
    assert shown["properties"]["provisioningState"] == "Succeeded"

    update_path = properties["definition"]["updateResourceId"]
    match = re.fullmatch(r"updates/providers/([^/]+)/names/([^/]+)/versions/([^/]+)", update_path)
    assert match, f"Unsupported updateResourceId: {update_path}"
    provider, name, version = (unquote(value) for value in match.groups())
    update = scenario.cmd(
        f"iot adr ns su software-update show {namespace_scope} "
        f"--update-provider {quote(provider)} --update-name {quote(name)} --update-version {quote(version)}"
    ).get_output_in_json()
    assert update["updateId"] == {"provider": provider, "name": name, "version": version}

    group = parse_resource_id(target_id)
    assert target_id.casefold().startswith(namespace["id"].casefold() + "/groups/")
    shown_group = scenario.cmd(
        f"iot adr ns group show -n {quote(group['child_name_1'])} {namespace_scope}"
    ).get_output_in_json()
    # An empty live group progressed Creating -> RefreshingMembers -> Ready
    # (2026-09-11, centraluseuap). This is membership, not ARM provisioning.
    assert shown_group["properties"]["membershipState"] == "Ready"


_PREPROVISIONED_RUN_ENV_VARS = (
    "azext_iot_adr_job_run_resource_group",
    "azext_iot_adr_job_run_namespace",
    "azext_iot_adr_job_run_job",
    "azext_iot_adr_job_run_name",
    "azext_iot_adr_job_run_target_group_id",
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

        with CleanupLedger() as cleanup:
            with timed_step("Setup ❯ Namespace + Group + Job"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                )
                cleanup.register(
                    "namespace",
                    lambda: _delete_test_namespace(self, namespace_name, rg),
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

    @pytest.mark.skipif(
        not all(_PREPROVISIONED_RUN.values()),
        reason=(
            "Set azext_iot_adr_job_run_resource_group, "
            "azext_iot_adr_job_run_namespace, azext_iot_adr_job_run_job, and "
            "azext_iot_adr_job_run_name to an active pre-provisioned SoftwareUpdate run; "
            "set azext_iot_adr_job_run_target_group_id to authorize its safe test target."
        ),
    )
    def test_adr_preprovisioned_job_run_positive(self):
        """Verify healthy cancellation only against an explicitly authorized fixture.

        The read-only preflight requires fixture-validation read access to the
        namespace/job, linked UpdateInstance, imported update (SU data plane),
        and target group, plus run summary/results access. These are opt-in
        integration-fixture checks, not additional permission requirements for
        the production job-run cancellation command.
        """
        rg = _PREPROVISIONED_RUN["azext_iot_adr_job_run_resource_group"]
        namespace_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_namespace"]
        job_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_job"]
        run_name = _PREPROVISIONED_RUN["azext_iot_adr_job_run_name"]
        namespace_scope = f"--namespace {quote(namespace_name)} -g {quote(rg)}"
        scope = f"{namespace_scope} --jn {quote(job_name)} --rn {quote(run_name)}"

        _assert_software_update_fixture_ready(
            self, namespace_scope, job_name,
            _PREPROVISIONED_RUN["azext_iot_adr_job_run_target_group_id"],
        )
        shown = self.cmd(
            f"iot adr ns job run show {scope}"
        ).get_output_in_json()
        assert shown.get("name") == run_name
        assert shown["properties"]["provisioningState"] == "Succeeded"
        assert shown["properties"]["status"] == "Active", shown["properties"]

        summary = self.cmd(f"iot adr ns job run summary {scope}").get_output_in_json()
        assert summary["total"] > 0, "Healthy cancellation needs actual test targets"

        results = self.cmd(
            f"iot adr ns job run results {scope} --filter \"status eq 'Succeeded'\""
        ).get_output_in_json()
        assert isinstance(results, list)

        # Recheck immediately before the sole mutation. Do not register cleanup:
        # this fixture is supplied, not created/owned by the test.
        _cancel_active_run(self, scope)
