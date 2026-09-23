# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""ADR group lifecycle integration tests."""

import logging

import pytest
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers import group as group_provider
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper, CleanupLedger
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr._readiness import delete_test_namespace
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id


def _generate_group_name() -> str:
    return f"testgrp{generate_generic_id()[:8]}"


class _RefreshEvidence(logging.Handler):
    """Capture only the provider's service acknowledgement, not CLI exit codes."""

    def __init__(self):
        super().__init__()
        self.acknowledgements = []

    def emit(self, record):
        evidence = getattr(record, "adr_group_refresh", None)
        if evidence is not None:
            self.acknowledgements.append(evidence)


def _observe_group_refresh(scenario, command):
    evidence = _RefreshEvidence()
    group_provider.logger.addHandler(evidence)
    try:
        try:
            scenario.cmd(command)
        except HttpResponseError as error:
            if error.status_code not in (409, 429) or getattr(error.error, "code", None) != "GroupRefreshRateLimited":
                raise
            assert not evidence.acknowledgements, "Refresh failed after a conflicting service acknowledgement"
            _log(LogKind.RESULT, "Refresh explicitly throttled: HTTP %s GroupRefreshRateLimited", error.status_code)
            return "throttled"
        assert len(evidence.acknowledgements) == 1, "Refresh completed without a unique service acknowledgement"
        outcome, status = evidence.acknowledgements[0]
        assert (outcome, status) in {
            ("reused", 409), ("accepted", 202), ("accepted", 204),
        }, "Refresh returned an unrecognized service acknowledgement"
        _log(LogKind.RESULT, "Refresh service acknowledgement: %s, HTTP %s", outcome, status)
        return outcome
    finally:
        group_provider.logger.removeHandler(evidence)


@pytest.mark.usefixtures("set_cwd")
class TestADRGroupLifecycle(ADRFullInfraHelper, ADRLiveScenarioTest):
    def test_adr_group_delete_allows_immediate_name_reuse(self):
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        namespace_args = f"--ns {namespace_name} -g {TEST_RG}"
        group_args = f"-n {group_name} {namespace_args}"
        with CleanupLedger() as cleanup:
            self.cmd(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG} "
                f"--location {TEST_LOCATION}"
            )
            cleanup.register(
                "namespace",
                lambda: delete_test_namespace(
                    self, namespace_name, TEST_RG, groups=(group_name,),
                ),
            )
            for suffix in ("--no-wait", ""):
                created = self.cmd(
                    f"iot adr ns group create {group_args} "
                    '--query-string "*" --tags lifecycle=original'
                ).get_output_in_json()
                cleanup.register(
                    "group",
                    lambda: self.cmd(f"iot adr ns group delete {group_args} --yes"),
                )
                self.cmd(f"iot adr ns group delete {group_args} --yes {suffix}")
                cleanup.dismiss("group")
                self.cmd(f"iot adr ns group wait {group_args} --deleted")
                recreated = self.cmd(
                    f"iot adr ns group create {group_args} "
                    '--query-string "*" --tags lifecycle=recreated'
                ).get_output_in_json()
                cleanup.register(
                    "group",
                    lambda: self.cmd(f"iot adr ns group delete {group_args} --yes"),
                )
                assert recreated["id"] == created["id"]
                assert recreated["tags"] == {"lifecycle": "recreated"}
                self.cmd(f"iot adr ns group delete {group_args} --yes")
                cleanup.dismiss("group")
                self.cmd(f"iot adr ns group wait {group_args} --deleted")

    def test_adr_group_lifecycle(self):
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        group_name = _generate_group_name()
        with CleanupLedger() as cleanup:
            with timed_step("Setup ❯ Create namespace"):
                self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} "
                    f"--location {TEST_LOCATION}"
                )
                cleanup.register(
                    "namespace",
                    lambda: delete_test_namespace(self, namespace_name, rg, groups=(group_name,)),
                )

            with timed_step("Step 1 ❯ Create and inspect group"):
                cleanup.register(
                    "group",
                    lambda: self.cmd(
                        f"iot adr ns group delete -n {group_name} --ns {namespace_name} -g {rg} -y"
                    ),
                )
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

            with timed_step("Step 3 ❯ Refresh members after initial calculation"):
                refresh_outcome = _observe_group_refresh(
                    self,
                    f"iot adr ns group refresh -n {group_name} "
                    f"--ns {namespace_name} -g {rg}",
                )
                # Acceptance does not establish that a separate calculation was started.
                assert refresh_outcome in {"accepted", "throttled", "reused"}, (
                    f"Unexpected group refresh outcome: {refresh_outcome}"
                )

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
                cleanup.dismiss("group")
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
