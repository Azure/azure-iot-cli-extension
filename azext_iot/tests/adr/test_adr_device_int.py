# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR device lifecycle integration tests.

Requires the preview azure-iot-device SDK (feature/dps-csr-preview)
and ``DEVICE_PREVIEW_SDK=1``.  Run via ``tox -e ADR-device-int``.
"""

import os
import time

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRHubInfraHelper
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_device_id,
    generate_dps_name,
    generate_enrollment_group_id,
    generate_hub_name,
    generate_identity_name,
)

DPS_PROVISIONING_HOST = "global.azure-devices-provisioning.net"


@pytest.mark.usefixtures("set_cwd")
class TestADRDeviceLifecycle(ADRHubInfraHelper, CaptureOutputLiveScenarioTest):
    """Device provisioning + CRUD + revoke via CLI.

    Uses the preview azure-iot-device SDK to register a device with CSR
    through DPS, then exercises list/show/update/revoke commands.
    """

    @pytest.mark.skipif(
        not os.environ.get("DEVICE_PREVIEW_SDK"),
        reason=(
            "Device lifecycle requires azure-iot-device preview SDK with CSR support "
            "(feature/dps-csr-preview). Set DEVICE_PREVIEW_SDK=1 or run via tox -e ADR-device-int."
        ),
    )
    def test_adr_device_provision_crud_and_revoke(self):
        """Provision a device with CSR via preview SDK, then test list/show/update/revoke via CLI."""
        _log(LogKind.TEST, "test_adr_device_provision_crud_and_revoke")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        dps_name = generate_dps_name()
        identity_name = generate_identity_name()
        device_id = generate_device_id()
        enrollment_group_id = generate_enrollment_group_id()

        try:
            infra = self.setup_full_infra(
                resource_group=rg,
                namespace_name=namespace_name,
                hub_name=hub_name,
                identity_name=identity_name,
                use_default_policy=True,
            )
            infra = self.setup_dps_with_sync(
                infra=infra,
                resource_group=rg,
                namespace_name=namespace_name,
                dps_name=dps_name,
                device_id=device_id,
                enrollment_group_id=enrollment_group_id,
            )

            # Register device via preview SDK with CSR
            from cryptography import x509 as crypto_x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import NameOID

            # Generate EC P-256 key pair and CSR
            private_key = ec.generate_private_key(ec.SECP256R1())
            csr = (
                crypto_x509.CertificateSigningRequestBuilder()
                .subject_name(crypto_x509.Name([
                    crypto_x509.NameAttribute(NameOID.COMMON_NAME, device_id),
                ]))
                .sign(private_key, hashes.SHA256())
            )
            csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()

            # --- Step 2: Provision device via preview SDK ---
            with timed_step("Step 2 ❯ Provision Device via DPS"):
                enroll_show_cmd = (
                    f"iot dps enrollment show --dps-name {dps_name} -g {rg} "
                    f"--enrollment-id {device_id} --show-keys"
                )
                _log(LogKind.CMD, "az %s", enroll_show_cmd)
                enrollment_keys = self.cmd(enroll_show_cmd).get_output_in_json()
                sym_key = enrollment_keys["attestation"]["symmetricKey"]["primaryKey"]
                id_scope = infra["id_scope"]
                _log(LogKind.RESULT, "symmetricKey retrieved, idScope=%s", id_scope)

                from azure.iot.device import ProvisioningDeviceClient

                _log(
                    LogKind.CMD,
                    "[SDK] ProvisioningDeviceClient.register(host=%s, id=%s, scope=%s)",
                    DPS_PROVISIONING_HOST, device_id, id_scope,
                )
                client = ProvisioningDeviceClient.create_from_symmetric_key(
                    provisioning_host=DPS_PROVISIONING_HOST,
                    registration_id=device_id,
                    id_scope=id_scope,
                    symmetric_key=sym_key,
                )
                client.client_certificate_signing_request = csr_pem
                result = client.register()
                _log(
                    LogKind.RESULT,
                    "DPS registration: status=%s, device_id=%s, assigned_hub=%s",
                    result.status,
                    result.registration_state.device_id if result.registration_state else "N/A",
                    result.registration_state.assigned_hub if result.registration_state else "N/A",
                )
                assert result.status == "assigned", (
                    f"DPS registration failed: status={result.status}"
                )
                _log(LogKind.OK, "Device '%s' registered via DPS", device_id)

            def device_cmd(action):
                """Run ``iot adr ns device <action>`` against the test namespace."""
                cmd = f"iot adr ns device {action} --ns {namespace_name} -g {rg}"
                _log(LogKind.CMD, "az %s", cmd)
                return self.cmd(cmd)

            def props(resp):
                """Extract properties sub-dict from ARM resource envelope."""
                return resp.get("properties", resp)

            # Poll until device appears (ZTP provisioning is async)
            with timed_step("Step 3 ❯ Verify Device Appears"):
                max_polls = 40
                devices = []
                for _poll in range(1, max_polls + 1):
                    devices = device_cmd("list").get_output_in_json()
                    if devices:
                        break
                    time.sleep(15)

                assert len(devices) >= 1, (
                    f"Device '{device_id}' never appeared in namespace after provisioning."
                )
                assert device_id in [d["name"] for d in devices]
                _log(LogKind.OK, "Device '%s' found in namespace device list", device_id)

                device = device_cmd(f"show -n {device_id}").get_output_in_json()
                assert device["name"] == device_id
                _log(LogKind.OK, "Device show returned correct device '%s'", device_id)

            with timed_step("Step 4 ❯ Update: Policy, Enabled, OS Version"):
                updated_dev = device_cmd(
                    f"update -n {device_id} --policy-resource-id {infra['policy_resource_id']}"
                ).get_output_in_json()
                assert props(updated_dev).get("policy"), (
                    f"Policy assignment failed: {updated_dev}"
                )
                _log(LogKind.OK, "Policy assigned to device '%s'", device_id)

                for val, expected in [("false", False), ("true", True)]:
                    updated = device_cmd(f"update -n {device_id} --enabled {val}").get_output_in_json()
                    assert props(updated).get("enabled") is expected
                    _log(LogKind.OK, "Device enabled=%s after update --enabled %s", expected, val)

                updated = device_cmd(f"update -n {device_id} --os-version 2.0.1").get_output_in_json()
                assert props(updated).get("operatingSystemVersion") == "2.0.1"

                updated = device_cmd(
                    f"update -n {device_id} --enabled false --os-version 3.0.0 --tags env=test"
                ).get_output_in_json()
                assert props(updated).get("enabled") is False
                assert props(updated).get("operatingSystemVersion") == "3.0.0"
                assert updated.get("tags", {}).get("env") == "test"

            with timed_step("Step 5 ❯ Update: Set & Clear Attributes"):
                # Set attributes
                updated = device_cmd(
                    f'update -n {device_id} --attributes \'{{{{"region": "us", "tier": 1}}}}\''
                ).get_output_in_json()
                assert props(updated).get("attributes", {}).get("region") == "us"
                assert props(updated).get("attributes", {}).get("tier") == 1
                _log(LogKind.OK, "Attributes set on device '%s'", device_id)

                # Clear attributes
                updated = device_cmd(
                    f"update -n {device_id} --attributes ''"
                ).get_output_in_json()
                assert props(updated).get("attributes") == {} or props(updated).get("attributes") is None
                _log(LogKind.OK, "Attributes cleared on device '%s'", device_id)

            with timed_step("Step 6 ❯ Update: Clear OS Version"):
                # Ensure os-version is set
                updated = device_cmd(
                    f"update -n {device_id} --os-version 4.0.0"
                ).get_output_in_json()
                assert props(updated).get("operatingSystemVersion") == "4.0.0"

                # Clear os-version
                updated = device_cmd(
                    f"update -n {device_id} --os-version ''"
                ).get_output_in_json()
                assert props(updated).get("operatingSystemVersion") in ("", None)
                _log(LogKind.OK, "OS version cleared on device '%s'", device_id)

            with timed_step("Step 7 ❯ Update: Clear Tags"):
                # Ensure tags are set
                updated = device_cmd(
                    f"update -n {device_id} --tags env=staging"
                ).get_output_in_json()
                assert updated.get("tags", {}).get("env") == "staging"

                # Clear all tags
                updated = device_cmd(
                    f"update -n {device_id} --tags ''"
                ).get_output_in_json()
                assert updated.get("tags") in ({}, None)
                _log(LogKind.OK, "Tags cleared on device '%s'", device_id)

            with timed_step("Step 8 ❯ Revoke Credentials"):
                # Re-enable device (policy already assigned from Step 4)
                device_cmd(f"update -n {device_id} --enabled true")

                def revoke_and_check(revoke_args, expected_enabled, label=""):
                    """Revoke device credentials and verify response and enabled state."""
                    call_label = label or revoke_args or '(default)'

                    # 1. Call revoke and capture response
                    try:
                        revoke_result = device_cmd(
                            f"revoke -n {device_id} {revoke_args} -y"
                        ).get_output_in_json()
                        _log(
                            LogKind.OK,
                            "[%s] Revoke response: result=%s, error=%s",
                            call_label,
                            revoke_result.get("result"),
                            revoke_result.get("error"),
                        )
                        assert revoke_result.get("error") is None, (
                            f"[{call_label}] Revoke returned error: {revoke_result.get('error')}"
                        )
                    except Exception as e:
                        if "get_output_in_json" in str(e) or "JSON" in str(e).upper():
                            _log(
                                LogKind.WARN,
                                "[%s] Could not parse revoke response as JSON — "
                                "command may not return structured output: %s",
                                call_label, str(e)[:200],
                            )
                        else:
                            raise

                    # 2. Query ADR device state
                    d = device_cmd(f"show -n {device_id}").get_output_in_json()
                    dp = props(d)

                    if expected_enabled is not None:
                        assert dp.get("enabled") is expected_enabled, (
                            f"[{call_label}] expected enabled={expected_enabled}, "
                            f"got {dp.get('enabled')}"
                        )
                    _log(
                        LogKind.OK,
                        "[%s] ADR device: enabled=%s, version=%s",
                        call_label, dp.get("enabled"), dp.get("version"),
                    )

                revoke_and_check("", expected_enabled=True, label="revoke-default")
                revoke_and_check("--disable", expected_enabled=False, label="revoke-disable")
                revoke_and_check("", expected_enabled=None, label="revoke-while-disabled")

                device_cmd(f"update -n {device_id} --enabled true")
                _log(LogKind.RESULT, "Device re-enabled for idempotency test")
                revoke_and_check("", expected_enabled=True, label="revoke-idempotency")

            with timed_step("Step 9 ❯ Update: Clear Policy"):
                # Ensure policy is assigned
                updated = device_cmd(
                    f"update -n {device_id} --policy-resource-id {infra['policy_resource_id']}"
                ).get_output_in_json()
                assert props(updated).get("policy")
                _log(LogKind.OK, "Policy re-assigned before clear test")

                # Clear policy
                updated = device_cmd(
                    f"update -n {device_id} --policy-resource-id ''"
                ).get_output_in_json()
                assert not props(updated).get("policy") or not props(updated).get("policy", {}).get("resourceId")
                _log(LogKind.OK, "Policy cleared on device '%s'", device_id)

            # Revoke nonexistent device -- expect failure
            _log(LogKind.STEP, "Step 10 ❯ Negative: Revoke Nonexistent Device")
            nonexistent_revoke_cmd = f"iot adr ns device revoke -n nonexistent-device --ns {namespace_name} -g {rg} -y"
            _log(LogKind.CMD, "az %s  (expect failure)", nonexistent_revoke_cmd)
            self.cmd(
                nonexistent_revoke_cmd,
                expect_failure=True,
            )
            _log(LogKind.OK, "Revoking nonexistent device correctly failed")

        finally:
            self.cleanup_full_infra(
                resource_group=rg,
                hub_name=hub_name,
                namespace_name=namespace_name,
                identity_name=identity_name,
                dps_name=dps_name,
            )


@pytest.mark.usefixtures("set_cwd")
class TestADRDeviceEdgeCases(ADRHubInfraHelper, CaptureOutputLiveScenarioTest):
    """Negative and edge-case device tests that don't require DPS or the preview SDK."""

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
