# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Integration tests for ADR BYOR (Bring Your Own Root) policy lifecycle.

Requires openssl CLI on PATH for ECDSA certificate signing.
"""

import os
import subprocess
import tempfile
import time

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRHubInfraHelper,
    POLICY_PROPAGATION_DELAY,
    get_byor_config,
    get_ca_config,
)
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    CUSTOM_POLICY_NAME,
    TEST_RG,
    generate_adr_namespace_name,
    generate_hub_name,
    generate_identity_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRPolicyBYORLifecycle(ADRHubInfraHelper, CaptureOutputLiveScenarioTest):
    """Tests for BYOR (Bring Your Own Root) policy creation and activation."""

    def test_policy_create_with_enable_byor(self):
        """Create a BYOR policy and verify CSR generation with PendingActivation status."""
        _log(LogKind.TEST, "test_policy_create_with_enable_byor")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            policy = self.setup_namespace_with_policy(namespace_name, rg, enable_byor=True)
            assert policy["properties"]["provisioningState"] == "Succeeded"

            byor = get_byor_config(policy)
            assert byor["enabled"] is True
            assert byor["status"] == "PendingActivation"
            assert "BEGIN CERTIFICATE REQUEST" in byor.get("certificateSigningRequest", "")

        finally:
            self.cleanup_namespace(namespace_name, rg)

    def test_policy_activate_byor_full_lifecycle(self):
        """Create BYOR policy, sign its CSR with a test CA, activate, and verify Active status."""
        _log(LogKind.TEST, "test_policy_activate_byor_full_lifecycle")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            policy = self.setup_namespace_with_policy(namespace_name, rg, enable_byor=True)

            byor = get_byor_config(policy)
            assert byor["status"] == "PendingActivation"

            # Brief delay for policy internal state to settle after creation
            time.sleep(POLICY_PROPAGATION_DELAY)

            activated = self.activate_byor_policy(
                namespace_name, rg, "default", byor["certificateSigningRequest"]
            )
            activated_byor = get_byor_config(activated)
            assert activated_byor["status"] == "Active"
            assert activated_byor.get("issuingCertificateThumbprint") is not None

        finally:
            self.cleanup_namespace(namespace_name, rg)

    def test_byor_activate_and_sync_to_hub(self):
        """BYOR E2E: create infra with BYOR -> sign CSR -> activate -> sync -> verify ICA on hub."""
        _log(LogKind.TEST, "test_byor_activate_and_sync_to_hub")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        identity_name = generate_identity_name()
        policy_name = CUSTOM_POLICY_NAME

        try:
            # --- Step 1: Create full infrastructure with BYOR policy ---
            infra = self.setup_full_infra(
                resource_group=rg,
                namespace_name=namespace_name,
                hub_name=hub_name,
                identity_name=identity_name,
                policy_name=policy_name,
                enable_byor=True,
            )
            subscription_id = infra["subscription_id"]

            policy_rid = self.build_policy_resource_id(
                subscription_id, rg, namespace_name, policy_name,
            )

            # --- Step 2: Verify BYOR is PendingActivation with CSR ---
            policy = self.cmd(
                f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name {policy_name}"
            ).get_output_in_json()

            assert policy["properties"]["provisioningState"] == "Succeeded"
            byor = get_byor_config(policy)
            assert byor["enabled"] is True
            assert byor["status"] == "PendingActivation"
            csr = byor.get("certificateSigningRequest", "")
            assert "BEGIN CERTIFICATE REQUEST" in csr, "CSR must be present for BYOR activation"

            # Brief delay for policy internal state to settle
            time.sleep(POLICY_PROPAGATION_DELAY)

            # --- Step 3: Sign CSR and activate BYOR ---
            activated_policy = self.activate_byor_policy(namespace_name, rg, policy_name, csr)

            # --- Step 4: Verify BYOR status is Active with thumbprint ---

            activated_byor = get_byor_config(activated_policy)
            assert activated_byor["status"] == "Active", (
                f"Expected BYOR status 'Active', got '{activated_byor['status']}'"
            )
            issuing_thumbprint = activated_byor.get("issuingCertificateThumbprint")
            assert issuing_thumbprint is not None, "Active BYOR must have issuingCertificateThumbprint"

            # --- Step 5: Sync credentials and verify ICA on hub ---
            self.cmd(f"iot adr ns credential sync --ns {namespace_name} -g {rg}")

            hub_cert = self.find_hub_cert_by_policy(hub_name, rg, policy_rid)
            assert hub_cert is not None, (
                "BYOR ICA certificate should appear on hub after activation + sync"
            )
            assert hub_cert.get("properties", {}).get("PolicyResourceId") == policy_rid

        finally:
            self.cleanup_full_infra(
                resource_group=rg,
                hub_name=hub_name,
                namespace_name=namespace_name,
                identity_name=identity_name,
            )

    @pytest.mark.skip(
        reason="Backend temporarily disabled revoke-issuer for BYOR policies"
        " (PolicyRevokeNotAllowedForBringYourOwnRoot). Re-enable when backend fix is deployed."
    )
    def test_byor_revoke_and_reactivate(self):
        """BYOR rotation: activate -> sync -> revoke -> re-sign -> re-activate -> sync -> verify.

        Validates:
        1. BYOR policy activated and ICA synced to hub
        2. Revoke transitions back to PendingActivation with a new CSR
        3. Re-signing and re-activating restores Active status
        4. Credential sync after re-activation pushes new ICA to hub
        """
        _log(LogKind.TEST, "test_byor_revoke_and_reactivate")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        identity_name = generate_identity_name()
        policy_name = CUSTOM_POLICY_NAME

        try:
            # --- Step 1: Full infra with BYOR policy ---
            infra = self.setup_full_infra(
                resource_group=rg,
                namespace_name=namespace_name,
                hub_name=hub_name,
                identity_name=identity_name,
                policy_name=policy_name,
                enable_byor=True,
            )
            subscription_id = infra["subscription_id"]

            policy_rid = self.build_policy_resource_id(
                subscription_id, rg, namespace_name, policy_name,
            )

            # --- Step 2: First activation ---
            policy_show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name {policy_name}"
            with timed_step("Step 2 ❯ First BYOR Activation"):
                _log(LogKind.CMD, "az %s", policy_show_cmd)
                policy = self.cmd(policy_show_cmd).get_output_in_json()
                byor = get_byor_config(policy)
                assert byor["status"] == "PendingActivation"
                _log(LogKind.OK, "BYOR status is PendingActivation")

                time.sleep(POLICY_PROPAGATION_DELAY)

                first_csr = byor["certificateSigningRequest"]
                _log(LogKind.CMD, "Signing CSR and activating BYOR policy ...")
                activated = self.activate_byor_policy(namespace_name, rg, policy_name, first_csr)
                first_byor = get_byor_config(activated)
                assert first_byor["status"] == "Active"
                first_thumbprint = first_byor.get("issuingCertificateThumbprint")
                assert first_thumbprint is not None
                _log(LogKind.OK, "BYOR activated, thumbprint=%s", first_thumbprint)

            # --- Step 3: Sync and record first ICA on hub ---
            sync_cmd = f"iot adr ns credential sync --ns {namespace_name} -g {rg}"
            with timed_step("Step 3 ❯ Credential Sync"):
                _log(LogKind.CMD, "az %s", sync_cmd)
                self.cmd(sync_cmd)
                _log(LogKind.RESULT, "ok")

                first_hub_cert = self.find_hub_cert_by_policy(hub_name, rg, policy_rid)
                assert first_hub_cert is not None, "First BYOR ICA should be on hub after sync"
                first_hub_cert_name = first_hub_cert["name"]
                _log(LogKind.OK, "First BYOR ICA found on hub: %s", first_hub_cert_name)

            # --- Step 4: Revoke issuer -> PendingActivation with new CSR ---
            revoke_cmd = (
                f"iot adr ns policy revoke-issuer --ns {namespace_name} -g {rg} "
                f"--policy-name {policy_name} -y"
            )
            with timed_step("Step 4 ❯ Revoke Issuer"):
                _log(LogKind.CMD, "az %s", revoke_cmd)
                self.cmd(revoke_cmd)
                _log(LogKind.RESULT, "ok: revoke-issuer succeeded")

                _log(LogKind.CMD, "az %s", policy_show_cmd)
                revoked = self.cmd(policy_show_cmd).get_output_in_json()

                revoked_byor = get_byor_config(revoked)
                assert revoked_byor["status"] == "PendingActivation", (
                    f"After revoke, BYOR status should be PendingActivation, got '{revoked_byor['status']}'"
                )
                second_csr = revoked_byor.get("certificateSigningRequest", "")
                assert "BEGIN CERTIFICATE REQUEST" in second_csr
                assert second_csr != first_csr, "New CSR should differ from the original"
                _log(LogKind.OK, "After revoke: status=PendingActivation with new CSR")

                # 4b. Check if old ICA was auto-removed from hub after revoke (no manual sync)
                post_revoke_certs = self.get_hub_certificates(hub_name, rg)
                post_revoke_cert_names = [c["name"] for c in post_revoke_certs]
                if first_hub_cert_name not in post_revoke_cert_names:
                    _log(
                        LogKind.OK,
                        "Old BYOR ICA '%s' auto-removed from hub after revoke",
                        first_hub_cert_name,
                    )
                else:
                    _log(
                        LogKind.WARN,
                        "Old BYOR ICA '%s' still on hub after revoke (not auto-removed)",
                        first_hub_cert_name,
                    )

                time.sleep(POLICY_PROPAGATION_DELAY)

            # --- Step 5: Re-sign new CSR and re-activate ---
            with timed_step("Step 5 ❯ Re-sign & Re-activate"):
                _log(LogKind.CMD, "Re-signing new CSR and re-activating BYOR policy ...")
                reactivated = self.activate_byor_policy(namespace_name, rg, policy_name, second_csr)
                reactivated_byor = get_byor_config(reactivated)
                assert reactivated_byor["status"] == "Active"
                second_thumbprint = reactivated_byor.get("issuingCertificateThumbprint")
                assert second_thumbprint is not None
                assert second_thumbprint != first_thumbprint, (
                    "Thumbprint must change after revoke + re-activate"
                )
                _log(
                    LogKind.OK,
                    "Re-activated with new thumbprint=%s (was %s)",
                    second_thumbprint, first_thumbprint,
                )

                # 5b. Probe: did the backend auto-sync the new ICA to the hub?
                auto_synced_cert = self.check_hub_cert_auto_synced(
                    hub_name, rg, policy_rid, "post-reactivate",
                )

            # --- Step 6: Ensure new ICA is on hub (sync if needed) + final verification ---
            if auto_synced_cert is None:
                with timed_step("Step 6 ❯ Sync After Re-activation (new ICA was NOT auto-synced)"):
                    _log(
                        LogKind.WARN,
                        "Backend did not auto-sync new BYOR ICA to hub after re-activate -- "
                        "performing manual credential sync as workaround",
                    )
                    _log(LogKind.CMD, "az %s", sync_cmd)
                    self.cmd(sync_cmd)
                    _log(LogKind.RESULT, "ok")

                    post_certs = self.get_hub_certificates(hub_name, rg)
                    post_cert_names = [c["name"] for c in post_certs]
                    assert first_hub_cert_name not in post_cert_names, (
                        f"Old BYOR ICA '{first_hub_cert_name}' should be removed from hub"
                    )
                    _log(LogKind.OK, "Old BYOR ICA '%s' removed from hub", first_hub_cert_name)

                    new_hub_cert = self.find_hub_cert_by_policy(hub_name, rg, policy_rid)
                    assert new_hub_cert is not None, (
                        "New BYOR ICA should be on hub after re-activation + sync"
                    )
                    assert new_hub_cert["name"] != first_hub_cert_name
                    _log(
                        LogKind.OK,
                        "New BYOR ICA '%s' found on hub after manual sync (was '%s')",
                        new_hub_cert["name"], first_hub_cert_name,
                    )
            else:
                with timed_step("Step 6 ❯ Verify Auto-synced Cert"):
                    _log(LogKind.OK, "New BYOR ICA was auto-synced to hub -- no manual sync needed")
                    new_hub_cert = auto_synced_cert
                    assert new_hub_cert["name"] != first_hub_cert_name

            # Verify PolicyResourceId on the final hub cert
            new_cert_policy_rid = new_hub_cert.get("properties", {}).get("PolicyResourceId")
            assert new_cert_policy_rid == policy_rid, (
                f"New hub cert PolicyResourceId mismatch: "
                f"expected={policy_rid}, got={new_cert_policy_rid}"
            )
            _log(
                LogKind.OK,
                "New hub cert '%s' has correct PolicyResourceId",
                new_hub_cert["name"],
            )

        finally:
            self.cleanup_full_infra(
                resource_group=rg,
                hub_name=hub_name,
                namespace_name=namespace_name,
                identity_name=identity_name,
            )


@pytest.mark.usefixtures("set_cwd")
class TestADRBYOREdgeCases(ADRHubInfraHelper, CaptureOutputLiveScenarioTest):
    """Edge-case and negative tests for BYOR policy behavior."""

    def test_byor_not_enabled_on_standard_policy(self):
        """Verify a standard (non-BYOR) policy does not have BYOR enabled."""
        _log(LogKind.TEST, "test_byor_not_enabled_on_standard_policy")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            self.setup_namespace_with_policy(namespace_name, rg)

            _log(LogKind.STEP, "Verify ❯ Standard policy does not have BYOR enabled")
            show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
            _log(LogKind.CMD, "az %s", show_cmd)
            policy = self.cmd(show_cmd).get_output_in_json()

            byor = get_ca_config(policy).get("bringYourOwnRoot")
            if byor:
                assert byor.get("enabled") is not True
                _log(LogKind.OK, "BYOR present but not enabled (enabled=%s)", byor.get("enabled"))
            else:
                _log(LogKind.OK, "No BYOR section on standard policy")

        finally:
            self.cleanup_namespace(namespace_name, rg)

    def test_activate_byor_on_standard_policy_fails(self):
        """Attempting activate-byor on a non-BYOR policy is currently expected to fail.

        Note: The backend currently returns BringYourOwnRootNotEnabled as a
        temporary measure due to an internal bug. Once the backend fix is
        deployed, this operation may instead be silently accepted, and the test
        expectation should be updated accordingly.
        """
        _log(LogKind.TEST, "test_activate_byor_on_standard_policy_fails")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            self.setup_namespace_with_policy(namespace_name, rg)

            # Write a dummy PEM file (content doesn't matter — the policy is non-BYOR)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                f.write("-----BEGIN CERTIFICATE-----\nZHVtbXk=\n-----END CERTIFICATE-----\n")
                dummy_cert = f.name

            try:
                _log(LogKind.STEP, "Verify ❯ activate-byor on standard policy fails")
                activate_cmd = (
                    f"iot adr ns policy activate-byor --ns {namespace_name} -g {rg} "
                    f"--policy-name default --certificate-chain-file {dummy_cert}"
                )
                _log(LogKind.CMD, "az %s", activate_cmd)
                # Backend temporarily returns BringYourOwnRootNotEnabled due to
                # an internal bug. Once fixed, this may need expect_failure=False.
                self.cmd(activate_cmd, expect_failure=True)  # TODO(BYOR): revert to expect_failure=False after backend fix
                _log(LogKind.OK, "activate-byor on standard policy failed as expected")

                _log(LogKind.STEP, "Verify ❯ standard policy remains unchanged after activate-byor attempt")
                show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
                _log(LogKind.CMD, "az %s", show_cmd)
                policy = self.cmd(show_cmd).get_output_in_json()

                byor = get_ca_config(policy).get("bringYourOwnRoot")
                if byor:
                    assert byor.get("enabled") is not True
                    assert byor.get("status") != "Active"
                    _log(
                        LogKind.OK,
                        "BYOR remains disabled after failed activation attempt (enabled=%s, status=%s)",
                        byor.get("enabled"),
                        byor.get("status"),
                    )
                else:
                    _log(LogKind.OK, "No BYOR section on standard policy after failed activation attempt")
            finally:
                os.unlink(dummy_cert)

        finally:
            self.cleanup_namespace(namespace_name, rg)

    def test_activate_byor_with_mismatched_chain_fails(self):
        """Activating BYOR with a certificate that doesn't match the CSR is
        currently expected to fail.

        Note: The backend currently returns CertificateSubjectMismatch as a
        temporary measure due to an internal bug. Once the backend fix is
        deployed, this operation may instead be silently accepted, and the test
        expectation should be updated accordingly.
        """
        _log(LogKind.TEST, "test_activate_byor_with_mismatched_chain_fails")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            policy = self.setup_namespace_with_policy(namespace_name, rg, enable_byor=True)

            byor = get_byor_config(policy)
            assert byor["status"] == "PendingActivation"
            _log(LogKind.OK, "BYOR policy created with status=PendingActivation")

            # Generate a self-signed cert that does NOT match the CSR
            _log(LogKind.STEP, "Verify ❯ activate-byor with mismatched cert chain fails")
            _log(LogKind.CMD, "[local] Generating mismatched self-signed cert via openssl ...")
            with tempfile.TemporaryDirectory() as tmpdir:
                key_path = os.path.join(tmpdir, "wrong.key")
                cert_path = os.path.join(tmpdir, "wrong.pem")

                subprocess.run(
                    ["openssl", "ecparam", "-genkey", "-name", "secp384r1",
                     "-noout", "-out", key_path],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    ["openssl", "req", "-x509", "-new", "-sha384",
                     "-key", key_path, "-out", cert_path,
                     "-days", "365", "-subj", "/CN=Wrong CA",
                     "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                     "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
                    check=True, capture_output=True,
                )

                with open(cert_path, encoding="utf-8") as f:
                    wrong_chain = f.read()
            _log(LogKind.RESULT, "Mismatched cert generated (CN=Wrong CA)")

            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                f.write(wrong_chain)
                wrong_cert_file = f.name

            try:
                activate_cmd = (
                    f"iot adr ns policy activate-byor --ns {namespace_name} -g {rg} "
                    f"--policy-name default --certificate-chain-file {wrong_cert_file}"
                )
                _log(LogKind.CMD, "az %s", activate_cmd)
                # Backend temporarily returns CertificateSubjectMismatch due to
                # an internal bug. Once fixed, this may need expect_failure=False.
                self.cmd(activate_cmd, expect_failure=True)  # TODO(BYOR): revert to expect_failure=False after backend fix
                _log(LogKind.OK, "activate-byor with mismatched cert failed as expected")
            finally:
                os.unlink(wrong_cert_file)

            # Policy should still be PendingActivation after rejected activation attempt
            show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
            _log(LogKind.CMD, "az %s", show_cmd)
            still_pending = self.cmd(show_cmd).get_output_in_json()
            assert get_byor_config(still_pending)["status"] == "PendingActivation"
            _log(LogKind.OK, "Policy still PendingActivation after failed activation attempt")

        finally:
            self.cleanup_namespace(namespace_name, rg)

    def test_revoke_pending_byor_before_activation(self):
        """Revoking a BYOR policy still in PendingActivation (never activated).

        Validates behavior when revoking before the BYOR CSR has been signed.
        The backend may reject the operation or regenerate the CSR.
        """
        _log(LogKind.TEST, "test_revoke_pending_byor_before_activation")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            policy = self.setup_namespace_with_policy(namespace_name, rg, enable_byor=True)
            byor = get_byor_config(policy)
            assert byor["status"] == "PendingActivation"
            original_csr = byor.get("certificateSigningRequest", "")
            _log(LogKind.OK, "BYOR policy created with status=PendingActivation")

            _log(LogKind.STEP, "Verify ❯ Revoke on PendingActivation BYOR policy")
            revoke_cmd = (
                f"iot adr ns policy revoke-issuer --ns {namespace_name} -g {rg} "
                f"--policy-name default -y"
            )
            _log(LogKind.CMD, "az %s", revoke_cmd)
            try:
                self.cmd(revoke_cmd)
                _log(LogKind.RESULT, "ok: revoke-issuer accepted on PendingActivation policy")

                # If revoke succeeds, policy should still be PendingActivation with new CSR
                show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
                _log(LogKind.CMD, "az %s", show_cmd)
                revoked = self.cmd(show_cmd).get_output_in_json()
                revoked_byor = get_byor_config(revoked)
                assert revoked_byor["status"] == "PendingActivation"
                new_csr = revoked_byor.get("certificateSigningRequest", "")
                assert new_csr != original_csr, (
                    "CSR should change after revoking PendingActivation BYOR"
                )
                _log(LogKind.OK, "CSR regenerated after revoke (status still PendingActivation)")
            except Exception:
                _log(LogKind.WARN, "Backend rejected revoke on unactivated BYOR -- verifying unchanged state")
                # Backend may reject revoke on unactivated policy — verify unchanged state
                show_cmd = f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
                _log(LogKind.CMD, "az %s", show_cmd)
                still_pending = self.cmd(show_cmd).get_output_in_json()
                assert get_byor_config(still_pending)["status"] == "PendingActivation"
                _log(LogKind.OK, "Policy unchanged at PendingActivation after rejected revoke")

        finally:
            self.cleanup_namespace(namespace_name, rg)
