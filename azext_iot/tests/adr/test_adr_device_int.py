# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR device negative and edge-case integration tests.

Covers ``az iot adr ns device`` behavior against empty namespaces and
nonexistent resources.
"""

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRHubInfraHelper
from azext_iot.tests.adr._log import LogKind, _log
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRDeviceEdgeCases(ADRHubInfraHelper, CaptureOutputLiveScenarioTest):
    """Negative and edge-case device tests."""

    def test_adr_device_negative_and_edge_cases(self):
        """Verify device command behavior for empty namespaces, nonexistent resources."""
        _log(LogKind.TEST, "test_adr_device_negative_and_edge_cases")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            _log(LogKind.STEP, "Setup ❯ Create namespace with credential+policy")
            ns_cmd = (
                f"iot adr ns create -n {namespace_name} -g {rg} "
                f"--location {TEST_LOCATION} --enable-certificate-management"
            )
            _log(LogKind.CMD, "az %s", ns_cmd)
            self.cmd(ns_cmd)
            _log(LogKind.RESULT, "ok")

            # Device list on empty namespace returns an empty list
            _log(LogKind.STEP, "Verify ❯ Device list on empty namespace returns empty")
            list_cmd = f"iot adr ns device list --ns {namespace_name} -g {rg}"
            _log(LogKind.CMD, "az %s", list_cmd)
            devices = self.cmd(list_cmd).get_output_in_json()
            assert isinstance(devices, list)
            assert len(devices) == 0, (
                f"Expected empty device list on fresh namespace, got {len(devices)} devices"
            )
            _log(LogKind.OK, "Device list returned empty list (0 devices)")

            # Show nonexistent device returns ResourceNotFound
            _log(LogKind.STEP, "Verify ❯ Show nonexistent device fails")
            show_cmd = f"iot adr ns device show -n nonexistent-device --ns {namespace_name} -g {rg}"
            _log(LogKind.CMD, "az %s  (expect failure)", show_cmd)
            self.cmd(show_cmd, expect_failure=True)
            _log(LogKind.OK, "Show nonexistent device correctly returned failure")

        finally:
            _log(LogKind.STEP, "Cleanup ❯ Delete Namespace")
            try:
                cleanup_cmd = f"iot adr ns delete -n {namespace_name} -g {rg} -y"
                _log(LogKind.CMD, "az %s", cleanup_cmd)
                self.cmd(cleanup_cmd)
                _log(LogKind.RESULT, "ok")
            except Exception as e:
                _log(LogKind.WARN, "Cleanup failed: %s", e)

        # Device list against a nonexistent namespace returns a 404
        # (ParentResourceNotFound) because the parent namespace does not exist.
        _log(LogKind.STEP, "Verify ❯ Device list on nonexistent namespace fails with 404")
        nonexistent_list_cmd = f"iot adr ns device list --ns nonexistent-ns-{namespace_name} -g {rg}"
        _log(LogKind.CMD, "az %s  (expect failure)", nonexistent_list_cmd)
        self.cmd(nonexistent_list_cmd, expect_failure=True)
        _log(LogKind.OK, "Device list on nonexistent namespace correctly returned failure")
