# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR client-side validation negatives (cross-surface).

Every scenario in this module exercises argument validation before mutation:
required-argument guards, mutually-exclusive identity flags, and
discriminator-specific requirements.

These commands require no pre-provisioned ADR resources, but do require working
credentials and any preceding resource lookup to complete. Each ``self.cmd(...)``
must fail with the specific argument rejection. They complement the lifecycle
suites by driving the rejection branches end-to-end through the CLI, mirroring
the provider unit tests at the command surface.

Provider construction can obtain credentials before validating arguments.
Namespace create also reads the existing namespace before its identity guard.
Authentication and transport failures must not count as argument rejections.
"""

import re

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    logger as cli_error_logger,
)

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import TEST_LOCATION, TEST_RG


_UAMI_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
)


@pytest.mark.usefixtures("set_cwd")
class TestADRValidationNegatives(ADRLiveScenarioTest):
    """Command-surface validation without pre-provisioned ADR resources."""

    def _assert_argument_error(self, command, error_type, message):
        with pytest.raises(error_type, match=f"^{re.escape(message)}$"):
            self.cmd(command)

    def _assert_parser_error(self, command, message):
        with self.assertLogs(cli_error_logger, level="ERROR") as logs:
            with pytest.raises(SystemExit) as parser_error:
                self.cmd(command)
        assert parser_error.value.code == 2
        assert message in [record.getMessage() for record in logs.records]

    def test_adr_validation_negatives(self):
        _log(LogKind.TEST, "test_adr_validation_negatives")
        rg = TEST_RG
        # Names need not resolve to real resources. Namespace create can read
        # the resource first, but every command must reject before mutation.
        ns = "validation-ns-does-not-matter"

        # --- Namespace: outbound identity guards (resolved before the LRO) ---
        with timed_step("ns create ❯ outbound SAMI + UAMI together rejected"):
            self._assert_argument_error(
                f"iot adr ns create -n {ns} -g {rg} --location {TEST_LOCATION} "
                f"--omi-sa --omi-ua {_UAMI_ID}",
                MutuallyExclusiveArgumentError,
                "Specify only one outbound identity: --outbound-system-assigned-mi uses the "
                "namespace's system-assigned identity, while --outbound-user-assigned-mi "
                "<uami-resource-id> uses a user-assigned managed identity (the two options "
                "are mutually exclusive).",
            )
        with timed_step("ns migrate ❯ non-asset resource ID rejected"):
            self._assert_argument_error(
                f"iot adr ns migrate -n {ns} -g {rg} "
                f"--resource-ids {_UAMI_ID}",
                InvalidArgumentValueError,
                f"'{_UAMI_ID}' is not a Microsoft.DeviceRegistry/assets resource ID.",
            )
        with timed_step("ns device ❯ removed alias is not registered"):
            self._assert_parser_error(
                f"iot adr ns device show -n mydev --ns {ns} -g {rg}",
                "'device' is misspelled or not recognized by the system.",
            )

        # --- Certificate authority: update requires --tags ---
        with timed_step("ca update ❯ nothing-to-update rejected"):
            self._assert_argument_error(
                f"iot adr ns ca update -n myca --ns {ns} -g {rg}",
                RequiredArgumentMissingError,
                "Nothing to update. Provide --tags to update the certificate authority.",
            )

        # --- Certificate policy: update requires tags or certificate validity ---
        with timed_step("ca policy update ❯ nothing-to-update rejected"):
            self._assert_argument_error(
                f"iot adr ns ca policy update -n mypolicy --ca myca --ns {ns} -g {rg}",
                RequiredArgumentMissingError,
                "Nothing to update. Provide --tags or --validity-days "
                "to update the certificate policy.",
            )

        # --- Namespace resources: empty updates are rejected client-side ---
        with timed_step("namespace update ❯ nothing-to-update rejected"):
            self._assert_argument_error(
                f"iot adr ns update -n {ns} -g {rg}",
                RequiredArgumentMissingError,
                "Nothing to update. Provide --tags, --observability-enabled, or "
                "an outbound managed identity.",
            )
        with timed_step("registry-device update ❯ nothing-to-update rejected"):
            self._assert_argument_error(
                f"iot adr ns registry-device update -n mydev --ns {ns} -g {rg}",
                RequiredArgumentMissingError,
                "Nothing to update. Provide --enablement-state, --manufacturer, --model, "
                "--hardware-revision, --software-revision, or --tags.",
            )
        with timed_step("group update ❯ nothing-to-update rejected"):
            self._assert_argument_error(
                f"iot adr ns group update -n mygroup --ns {ns} -g {rg}",
                RequiredArgumentMissingError,
                "Nothing to update. Provide --display-name, --description or --tags.",
            )

        with timed_step("group report ❯ group name required"):
            self._assert_argument_error(
                f"iot adr ns report generate --ns {ns} -g {rg} "
                "--report-type GroupBestUpdatesComplianceReport",
                ArgumentUsageError,
                "--group-name is required for group update reports.",
            )

        # --- Job: guards that fire before any service call ---
        # (The job_int suite covers the same guards, but only after a real
        # namespace+group setup; these run with no backend.)
        with timed_step("job create ❯ missing --target-group-name rejected"):
            self._assert_argument_error(
                f"iot adr ns job create -n myjob --ns {ns} -g {rg} "
                f"--update-id-provider Contoso --update-id-name fw --update-id-version 1.0.0",
                ArgumentUsageError,
                "--target-group-name is required for --type SoftwareUpdate. The group must be in the "
                "same namespace and resource group as the job.",
            )
        with timed_step("job update ❯ nothing-to-update (no --tags) rejected"):
            self._assert_argument_error(
                f"iot adr ns job update -n myjob --ns {ns} -g {rg}",
                ArgumentUsageError,
                'Nothing to update. Pass --tags k=v [k2=v2 ...] to set tags or --tags "" to clear all tags.',
            )
        with timed_step("job run create ❯ not a command; use job schedule"):
            self._assert_parser_error(
                f"iot adr ns job run create --job-name myjob --ns {ns} -g {rg}",
                "'create' is misspelled or not recognized by the system.",
            )
        with timed_step("job schedule ❯ invalid ISO 8601 --scheduled-time rejected"):
            self._assert_argument_error(
                f"iot adr ns job schedule -n myjob --ns {ns} -g {rg} "
                f"--scheduled-time not-a-datetime",
                InvalidArgumentValueError,
                "--scheduled-time must be a valid ISO 8601 UTC datetime (e.g. '2025-12-01T08:00:00Z'). "
                "Provided value: 'not-a-datetime'.",
            )
        with timed_step("job schedule ❯ timezone-naive --scheduled-time rejected"):
            self._assert_argument_error(
                f"iot adr ns job schedule -n myjob --ns {ns} -g {rg} "
                f"--scheduled-time 2026-11-02T12:00:00",
                InvalidArgumentValueError,
                "--scheduled-time must be a valid ISO 8601 UTC datetime (e.g. '2025-12-01T08:00:00Z'). "
                "Provided value: '2026-11-02T12:00:00'.",
            )
        with timed_step("job run results ❯ unsupported --order-by field rejected"):
            self._assert_argument_error(
                "iot adr ns job run results --job-name myjob --run-name myrun "
                f"--ns {ns} -g {rg} --order-by \"name asc\"",
                InvalidArgumentValueError,
                'Use an order by expression such as "status asc" or "status desc". '
                "Supported fields: status.",
            )

        # --- Group: query filter is required at create time ---
        with timed_step("group create ❯ missing --query-string rejected"):
            self._assert_parser_error(
                f"iot adr ns group create -n mygroup --ns {ns} -g {rg}",
                "the following arguments are required: --query-string/--qs",
            )

        _log(LogKind.OK, "All cross-surface validation negatives rejected client-side as designed")
