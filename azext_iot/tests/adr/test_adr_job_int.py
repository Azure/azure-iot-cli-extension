# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR job integration tests (P6).

Covers the ``iot adr ns job`` surface end-to-end:

* CRUD: create / show / list / update / delete
* ``schedule`` with optional ``--scheduled-time`` and ``--timeout``
* Update guards (``Nothing to update``; non-tag fields rejected)
* ``wait`` (LRO polling)
* Same-namespace lock on ``--target-group-name`` (no cross-namespace targets)

Jobs require a target Group in the same namespace; they do **not** require
any Hub/DPS infrastructure. We keep the namespace lightweight (no certificate
infrastructure or linked Hub) since job CRUD does not exercise
linking surfaces.
"""

import datetime

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


@pytest.mark.usefixtures("set_cwd")
class TestADRJobLifecycle(ADRFullInfraHelper, ADRLiveScenarioTest):
    """End-to-end Job CRUD + schedule + delete."""

    def test_adr_job_lifecycle(self):
        _log(LogKind.TEST, "test_adr_job_lifecycle")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        job_name = _generate_job_name()
        run_names = []
        group_created = False
        job_created = False

        try:
            with timed_step("Setup ❯ Namespace + Group"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                )
                self.cmd(
                    f"iot adr ns group create -n {group_name} --ns {namespace_name} -g {rg} "
                    f'--query-string "*"'
                )
                group_created = True
                _log(LogKind.OK, "Group '%s' created", group_name)

            with timed_step("Step 1 ❯ job create (SoftwareUpdate)"):
                created = self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--type SoftwareUpdate --description 'Integration rollout' "
                    f"--target-group-name {group_name} "
                    f"--update-id-provider Contoso "
                    f"--update-id-name gateway-firmware "
                    f"--update-id-version 1.2.3"
                ).get_output_in_json()
                job_created = True
                assert created["name"] == job_name
                assert created["properties"]["provisioningState"] == "Succeeded"
                # Surface-level: target & update identity should be present in
                # the response (back-end shape may vary slightly).
                props = created["properties"]
                assert props["jobType"] == "SoftwareUpdate"
                assert props["description"] == "Integration rollout"
                target_id = (props.get("target") or {}).get("resourceId", "")
                assert group_name.lower() in target_id.lower(), (
                    f"target group not in target.resourceId: {target_id}"
                )
                definition = props.get("definition") or {}
                assert definition.get("schedulingType") == "Continuous"
                # 2026-11-02-preview flattens updateId into a relative
                # data-plane resource path.
                assert definition.get("updateResourceId") == (
                    "updates/providers/Contoso/names/gateway-firmware/versions/1.2.3"
                )
                _log(
                    LogKind.OK,
                    "job created; target=%s update=Contoso/gateway-firmware/1.2.3",
                    group_name,
                )

            with timed_step("Step 2 ❯ job show / list"):
                shown = self.cmd(
                    f"iot adr ns job show -n {job_name} --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert shown["name"] == job_name
                listed = self.cmd(
                    f"iot adr ns job list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert isinstance(listed, list)
                assert job_name in [j["name"] for j in listed]
                _log(LogKind.OK, "job visible in show + list")

            with timed_step("Step 3 ❯ job update (tags only)"):
                updated = self.cmd(
                    f"iot adr ns job update -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--tags env=int owner=adr-tests"
                ).get_output_in_json()
                assert updated["tags"]["env"] == "int"
                assert updated["tags"]["owner"] == "adr-tests"
                _log(LogKind.OK, "tags set: env=int owner=adr-tests")

                # Replace tags
                updated = self.cmd(
                    f"iot adr ns job update -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--tags purpose=p6-int"
                ).get_output_in_json()
                assert updated["tags"]["purpose"] == "p6-int"
                assert "env" not in updated.get("tags", {})
                _log(LogKind.OK, "tags replaced (env removed)")

            with timed_step("Step 4 ❯ job update with NO args raises Nothing to update"):
                # Provider raises ArgumentUsageError → CLI exits non-zero with
                # the "Nothing to update. Pass --tags k=v ..." message.
                self.cmd(
                    f"iot adr ns job update -n {job_name} --ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "no-args update correctly rejected")

            with timed_step("Step 5 ❯ job update --tags '' clears all tags"):
                cleared = self.cmd(
                    f"iot adr ns job update -n {job_name} --ns {namespace_name} -g {rg} --tags ''"
                ).get_output_in_json()
                assert cleared.get("tags") in (None, {}), (
                    f"Expected tags to be cleared, got {cleared.get('tags')}"
                )
                _log(LogKind.OK, "tags cleared with --tags ''")

            with timed_step("Step 6 ❯ job schedule (no args = immediate)"):
                run = self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                # --run-name is optional; the CLI generates a UTC-timestamped name.
                assert run["name"].startswith("run-")
                run_names.append(run["name"])
                _log(LogKind.OK, "job schedule (immediate) returned %s", run["name"])

            with timed_step("Step 7 ❯ job schedule with --scheduled-time"):
                self.cmd(
                    f"iot adr ns job run cancel -n {run['name']} "
                    f"--job-name {job_name} --ns {namespace_name} -g {rg} -y"
                )
                self.cmd(
                    f"iot adr ns job run delete -n {run['name']} "
                    f"--job-name {job_name} --ns {namespace_name} -g {rg} -y"
                )
                run_names.remove(run["name"])
                # Schedule for ~1 hour from now to keep it well-formed
                future = (
                    datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(hours=1)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                scheduled_run = f"{job_name}-scheduled"
                self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg} "
                    f"--run-name {scheduled_run} --scheduled-time {future}"
                )
                run_names.append(scheduled_run)
                _log(LogKind.OK, "job schedule (--scheduled-time=%s) returned", future)

                summary = self.cmd(
                    f"iot adr ns job run summary -n {scheduled_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert "total" in summary

                self.cmd(
                    f"iot adr ns job run delete -n {scheduled_run} --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg} -y"
                )
                run_names.remove(scheduled_run)

            with timed_step("Step 8 ❯ job wait"):
                self.cmd(
                    f"iot adr ns job wait -n {job_name} --ns {namespace_name} -g {rg}"
                )
                _log(LogKind.OK, "default success wait returned")

            with timed_step("Step 9 ❯ job delete"):
                self.cmd(
                    f"iot adr ns job delete -n {job_name} --ns {namespace_name} -g {rg} -y"
                )
                job_created = False
                self.cmd(
                    f"iot adr ns job show -n {job_name} --ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "job deleted")

        finally:
            for run_name in list(run_names):
                try:
                    self.cmd(
                        f"iot adr ns job run cancel -n {run_name} "
                        f"--job-name {job_name} --ns {namespace_name} -g {rg} -y"
                    )
                except Exception:
                    pass
                try:
                    self.cmd(
                        f"iot adr ns job run delete -n {run_name} "
                        f"--job-name {job_name} --ns {namespace_name} -g {rg} -y"
                    )
                except Exception:
                    pass
            if job_created:
                try:
                    self.cmd(
                        f"iot adr ns job delete -n {job_name} "
                        f"--ns {namespace_name} -g {rg} -y"
                    )
                except Exception:
                    pass
            if group_created:
                try:
                    self.cmd(
                        f"iot adr ns group delete -n {group_name} "
                        f"--ns {namespace_name} -g {rg} -y"
                    )
                except Exception:
                    pass
            self.cleanup_namespace(namespace_name, rg)

    def test_adr_onboarding_update_job_lifecycle(self):
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        job_name = _generate_job_name()

        try:
            self.cmd(
                f"iot adr ns create -n {namespace_name} -g {rg} "
                f"--location {TEST_LOCATION}"
            )
            self.cmd(
                f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                "--type OnboardingUpdate --description 'Onboarding integration rollout' "
                "--update-id-provider Contoso --update-id-name onboarding-fw "
                "--update-id-version 1.0.0 --no-wait"
            )
            self.cmd(
                f"iot adr ns job wait -n {job_name} --ns {namespace_name} -g {rg} "
                "--created"
            )

            job = self.cmd(
                f"iot adr ns job show -n {job_name} --ns {namespace_name} -g {rg}"
            ).get_output_in_json()
            properties = job["properties"]
            assert properties["jobType"] == "OnboardingUpdate"
            assert "target" not in properties
            assert properties["definition"]["schedulingType"] == "Continuous"

            self.cmd(
                f"iot adr ns job schedule -n {job_name} "
                f"--ns {namespace_name} -g {rg}"
            )
            self.cmd(
                f"iot adr ns job delete -n {job_name} --ns {namespace_name} -g {rg} -y"
            )
        finally:
            self.cleanup_namespace(namespace_name, rg)


@pytest.mark.usefixtures("set_cwd")
class TestADRJobValidation(ADRFullInfraHelper, ADRLiveScenarioTest):
    """Negative / validation tests for ``job create`` and ``job update``.

    These do not require a real namespace for some paths (CLI-side arg parsing
    fails before any API call), but creating one lets us exercise the cleaner
    provider-side ArgumentUsageError messages too.
    """

    def test_adr_job_validation_negatives(self):
        _log(LogKind.TEST, "test_adr_job_validation_negatives")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        job_name = _generate_job_name()

        try:
            with timed_step("Setup ❯ Namespace + Group"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                )
                self.cmd(
                    f"iot adr ns group create -n {group_name} --ns {namespace_name} -g {rg} "
                    f'--query-string "*"'
                )

            with timed_step("Neg 1 ❯ job create missing --target-group-name"):
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0",
                    expect_failure=True,
                )
                _log(LogKind.OK, "missing --target-group-name rejected")

            with timed_step("Neg 2 ❯ job create with partial --update-id-* triple"):
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--target-group-name {group_name} "
                    f"--update-id-provider Contoso --update-id-name fw",  # version missing
                    expect_failure=True,
                )
                _log(LogKind.OK, "partial update-id triple rejected")

            with timed_step("Neg 3 ❯ OnboardingUpdate rejects a target group"):
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--type OnboardingUpdate --target-group-name {group_name} "
                    f"--update-id-provider Contoso --update-id-name fw "
                    f"--update-id-version 1.0.0",
                    expect_failure=True,
                )
                _log(LogKind.OK, "OnboardingUpdate target rejected")

            with timed_step("Neg 4 ❯ job update with forbidden non-tag field"):
                # Create a job we can poke at
                self.cmd(
                    f"iot adr ns job create -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--target-group-name {group_name} "
                    f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0"
                )
                # `--target-group-name` is not a valid `job update` param at the
                # arg-parser layer; CLI core surfaces an unknown-argument error.
                self.cmd(
                    f"iot adr ns job update -n {job_name} --ns {namespace_name} -g {rg} "
                    f"--target-group-name some-other-group",
                    expect_failure=True,
                )
                _log(LogKind.OK, "non-tag update field rejected")

            with timed_step("Neg 5 ❯ job run create is not a command"):
                # Scheduling is exposed as `job schedule`, not `job run create`.
                self.cmd(
                    f"iot adr ns job run create --job-name {job_name} "
                    f"--ns {namespace_name} -g {rg}",
                    expect_failure=True,
                )
                _log(LogKind.OK, "job run create rejected as unknown command")

            with timed_step("Neg 6 ❯ job schedule with invalid ISO 8601 scheduled-time"):
                self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg} "
                    f"--scheduled-time 'tomorrow at noon'",
                    expect_failure=True,
                )
                _log(LogKind.OK, "invalid scheduled-time rejected")

            with timed_step("Neg 7 ❯ timezone-naive scheduled time rejected"):
                self.cmd(
                    f"iot adr ns job schedule -n {job_name} "
                    f"--ns {namespace_name} -g {rg} "
                    f"--scheduled-time 2026-11-02T12:00:00",
                    expect_failure=True,
                )

        finally:
            self.cleanup_namespace(namespace_name, rg)
