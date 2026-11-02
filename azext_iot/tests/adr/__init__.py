# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import nullcontext

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._log import log_command


class ADRLiveScenarioTest(CaptureOutputLiveScenarioTest):
    """Log ADR scenario commands before delegating execution to the test SDK."""

    def cmd(self, command, checks=None, expect_failure=False):
        log_command(self._apply_kwargs(command), expect_failure=expect_failure)
        recorder = getattr(self, "record_group_reader_assignments", None)
        with recorder() if recorder else nullcontext():
            return super().cmd(command, checks=checks, expect_failure=expect_failure)
