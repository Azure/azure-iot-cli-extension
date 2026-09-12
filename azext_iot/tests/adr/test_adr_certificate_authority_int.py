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
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    CleanupLedger,
    is_resource_not_found_error,
    resource_is_absent,
    wait_for_resource_absent,
)
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
        owned = set()
        deleting = set()
        delete_errors = {}
        scope = f"--ns {namespace_name} -g {rg}"
        resources = {
            "namespace": ("iot adr ns", f"-n {namespace_name} -g {rg}", ("root",)),
            "root": ("iot adr ns ca", f"-n {ca_name} {scope}", ("ica",)),
            "ica": ("iot adr ns ca", f"-n {ica_name} {scope}", ("policy",)),
            "policy": ("iot adr ns ca policy", f"-n {policy_name} --ca-name {ica_name} {scope}", ()),
        }
        cleanup = CleanupLedger()

        def delete_resource(label):
            if label not in owned:
                return
            # A later RP 404 does not erase an ARM child-dependency rejection.
            if label in delete_errors:
                raise delete_errors[label]
            command, arguments, _ = resources[label]
            show = f"{command} show {arguments}"
            if not resource_is_absent(self, show):
                if label not in deleting:
                    deleting.add(label)
                    try:
                        self.cmd(f"{command} delete {arguments} -y")
                    except (HttpResponseError, CloudError, CLIError) as error:
                        if not is_resource_not_found_error(error):
                            delete_errors[label] = error
                            raise
                wait_for_resource_absent(self, show)
            owned.remove(label)
            cleanup.dismiss(label)

        for label, (_, _, dependencies) in resources.items():
            cleanup.register(
                label, lambda label=label: delete_resource(label), depends_on=dependencies,
            )

        with cleanup:
            # --- Setup: namespace ---
            with timed_step("Setup ❯ Create namespace"):
                ns_cmd = (
                    f"iot adr ns create -n {namespace_name} -g {rg} "
                    f"--location {TEST_LOCATION}"
                )
                _log(LogKind.CMD, "az %s", ns_cmd)
                if not resource_is_absent(self, f"iot adr ns show -n {namespace_name} -g {rg}"):
                    raise AssertionError(f"Refusing to overwrite existing namespace '{namespace_name}'.")
                owned.add("namespace")
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
                owned.add("root")
                created = ca_cmd(f"create -n {ca_name} --type Root").get_output_in_json()
                assert created["name"] == ca_name
                assert props(created).get("certificateAuthorityType") == "Root"
                ca_cmd(f"wait -n {ca_name}")
                _log(LogKind.OK, "Root CA '%s' created", ca_name)

            # --- Step 2: Create a Microsoft-issued ICA under the Root ---
            with timed_step("Step 2 ❯ Create issuing certificate authority"):
                owned.add("ica")
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
                owned.add("policy")
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
                for label in ("policy", "ica", "root"):
                    delete_resource(label)
                remaining = [c["name"] for c in ca_cmd("list").get_output_in_json()]
                assert ca_name not in remaining
                assert ica_name not in remaining
                _log(LogKind.OK, "CA '%s' deleted", ca_name)
