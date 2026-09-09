# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR certificate authority and policy integration tests.

Exercises the `iot adr ns ca` and `iot adr ns ca policy` command surfaces against a
namespace. Activation of an externally issued ICA requires external PKI signing and is
therefore not asserted here;
the lifecycle focuses on the create/show/list/update/delete paths that run without an
external signer.

Run via ``tox -e ADR-int``.
"""

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRCertificateAuthorityLifecycle(ADRLiveScenarioTest):
    """End-to-end certificate authority + certificate policy lifecycle through the CLI."""

    def test_adr_certificate_authority_lifecycle(self):
        _log(LogKind.TEST, "test_adr_certificate_authority_lifecycle")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        ca_name = "rootca"
        ica_name = "issuingca"
        policy_name = "leafpolicy"
        namespace_created = False
        root_created = False
        ica_created = False
        policy_created = False

        try:
            # --- Setup: namespace ---
            with timed_step("Setup ❯ Create namespace"):
                ns_cmd = (
                    f"iot adr ns create -n {namespace_name} -g {rg} "
                    f"--location {TEST_LOCATION}"
                )
                _log(LogKind.CMD, "az %s", ns_cmd)
                namespace_created = True
                ns = self.cmd(ns_cmd).get_output_in_json()
                assert ns["name"] == namespace_name
                _log(LogKind.OK, "namespace created")

            def ca_cmd(action):
                cmd = f"iot adr ns ca {action} --ns {namespace_name} -g {rg}"
                _log(LogKind.CMD, "az %s", cmd)
                return self.cmd(cmd)

            def props(resp):
                return resp.get("properties", resp)

            # --- Step 1: Create a service-managed Root CA ---
            with timed_step("Step 1 ❯ Create Root certificate authority"):
                root_created = True
                created = ca_cmd(f"create -n {ca_name} --type Root").get_output_in_json()
                assert created["name"] == ca_name
                assert props(created).get("certificateAuthorityType") == "Root"
                ca_cmd(f"wait -n {ca_name}")
                _log(LogKind.OK, "Root CA '%s' created", ca_name)

            # --- Step 2: Create a Microsoft-issued ICA under the Root ---
            with timed_step("Step 2 ❯ Create issuing certificate authority"):
                ica_created = True
                issuing = ca_cmd(
                    f"create -n {ica_name} --type ICA "
                    f"--issuer-type Microsoft --issuer-ca-name {ca_name}"
                ).get_output_in_json()
                assert issuing["name"] == ica_name
                assert props(issuing).get("certificateAuthorityType") == "ICA"
                ca_cmd(f"wait -n {ica_name}")
                _log(LogKind.OK, "Issuing CA '%s' created", ica_name)

            # --- Step 3: Show round-trips the CA ---
            with timed_step("Step 3 ❯ Show certificate authority"):
                shown = ca_cmd(f"show -n {ca_name}").get_output_in_json()
                assert shown["name"] == ca_name

            # --- Step 4: List includes the new CAs ---
            with timed_step("Step 4 ❯ List certificate authorities"):
                cas = ca_cmd("list").get_output_in_json()
                ca_names = [c["name"] for c in cas]
                assert ca_name in ca_names
                assert ica_name in ca_names

            # --- Step 5: Update CA tags ---
            with timed_step("Step 5 ❯ Update certificate authority tags"):
                updated = ca_cmd(f"update -n {ca_name} --tags env=int").get_output_in_json()
                assert updated.get("tags", {}).get("env") == "int"

            # --- Step 6: Create a certificate policy under the issuing CA ---
            with timed_step("Step 6 ❯ Create certificate policy"):
                pol_cmd = (
                    f"iot adr ns ca policy create -n {policy_name} --ca-name {ica_name} "
                    f"--ns {namespace_name} -g {rg} --validity-days 30"
                )
                _log(LogKind.CMD, "az %s", pol_cmd)
                policy_created = True
                pol = self.cmd(pol_cmd).get_output_in_json()
                assert pol["name"] == policy_name
                assert props(pol)["certificate"]["validityPeriodInDays"] == 30
                self.cmd(
                    f"iot adr ns ca policy wait -n {policy_name} "
                    f"--ca-name {ica_name} --ns {namespace_name} -g {rg} "
                    "--created"
                )
                _log(LogKind.OK, "Policy '%s' created with 30-day validity", policy_name)

            def policy_cmd(action):
                cmd = (
                    f"iot adr ns ca policy {action} --ca-name {ica_name} "
                    f"--ns {namespace_name} -g {rg}"
                )
                _log(LogKind.CMD, "az %s", cmd)
                return self.cmd(cmd)

            # --- Step 7: Show + list policies ---
            with timed_step("Step 7 ❯ Show & list certificate policies"):
                shown_pol = policy_cmd(f"show -n {policy_name}").get_output_in_json()
                assert shown_pol["name"] == policy_name
                policies = policy_cmd("list").get_output_in_json()
                assert policy_name in [p["name"] for p in policies]

            # --- Step 8: Update policy tags ---
            with timed_step("Step 8 ❯ Update certificate policy tags"):
                updated_pol = policy_cmd(
                    f"update -n {policy_name} --tags env=updated"
                ).get_output_in_json()
                assert updated_pol.get("tags", {}).get("env") == "updated"

            # --- Step 9: Negative: policy under a missing CA fails clearly ---
            with timed_step("Step 9 ❯ Negative: policy on nonexistent CA fails"):
                bad = (
                    f"iot adr ns ca policy show -n {policy_name} --ca-name nonexistent-ca "
                    f"--ns {namespace_name} -g {rg}"
                )
                _log(LogKind.CMD, "az %s  (expect failure)", bad)
                self.cmd(bad, expect_failure=True)

            # --- Step 10: Delete policy, ICA, then Root ---
            with timed_step("Step 10 ❯ Delete policy and certificate authorities"):
                policy_cmd(f"delete -n {policy_name} -y")
                policy_created = False
                ca_cmd(f"delete -n {ica_name} -y")
                ica_created = False
                ca_cmd(f"delete -n {ca_name} -y")
                root_created = False
                remaining = [c["name"] for c in ca_cmd("list").get_output_in_json()]
                assert ca_name not in remaining
                assert ica_name not in remaining
                _log(LogKind.OK, "CA '%s' deleted", ca_name)

        finally:
            cleanup = [
                (
                    policy_created,
                    "certificate policy",
                    f"iot adr ns ca policy delete -n {policy_name} "
                    f"--ca-name {ica_name} --ns {namespace_name} -g {rg} -y",
                ),
                (
                    ica_created,
                    "issuing certificate authority",
                    f"iot adr ns ca delete -n {ica_name} "
                    f"--ns {namespace_name} -g {rg} -y",
                ),
                (
                    root_created,
                    "Root certificate authority",
                    f"iot adr ns ca delete -n {ca_name} "
                    f"--ns {namespace_name} -g {rg} -y",
                ),
                (
                    namespace_created,
                    "namespace",
                    f"iot adr ns delete -n {namespace_name} -g {rg} -y",
                ),
            ]
            for should_delete, label, cleanup_cmd in cleanup:
                if not should_delete:
                    continue
                _log(LogKind.STEP, "Cleanup ❯ Delete %s", label)
                _log(LogKind.CMD, "az %s", cleanup_cmd)
                try:
                    self.cmd(cleanup_cmd)
                except Exception as error:  # noqa: BLE001 - cleanup is best-effort
                    _log(LogKind.WARN, "Cleanup failed for %s: %s", label, error)
