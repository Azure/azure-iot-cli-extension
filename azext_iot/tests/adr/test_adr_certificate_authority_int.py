# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR certificate authority and policy integration tests.

Exercises the `iot adr ns ca` and `iot adr ns ca policy` command surfaces against a
namespace. External activation uses a disposable ECC root and the documented OpenSSL
CSR-signing recipe. Microsoft revocation is explicitly opt-in and uses only owned CAs.

Run via ``tox -e ADR-int``.
"""

import os
import shlex
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import pytest
from azure.core.exceptions import HttpResponseError
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._certificate_fixtures import is_expected_policy_rejection, negative_certificate_chains
from azext_iot.tests.adr._certificate_action_tracker import CertificateActionTracker
from azext_iot.tests.adr._helpers import (
    CleanupLedger,
    is_resource_not_found_error,
    resource_is_absent,
    wait_for_resource_absent,
    wait_for_condition,
)
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_API_VERSION,
    TEST_ARM_ENDPOINT,
    TEST_ARM_RESOURCE,
    TEST_LOCATION,
    TEST_RG,
    TEST_SUBSCRIPTION,
    generate_adr_namespace_name,
)
from azext_iot.adr.providers.certificate_helpers import validate_external_certificate_chain
from azext_iot.common.certops import make_cert_chain


@pytest.mark.usefixtures("set_cwd")
class TestADRCAActions(ADRLiveScenarioTest):
    @staticmethod
    def _bounded_read(fetch, predicate, description):
        deadline = monotonic() + 600

        def read():
            value = fetch()
            if monotonic() >= deadline:
                raise AssertionError(f"Timed out reading {description}.")
            return value

        return wait_for_condition(
            read, predicate, description=description, timeout=600,
            is_terminal_failure=lambda value: value["properties"].get("provisioningState") in ("Failed", "Canceled"),
            is_retryable_error=lambda _error: False,
        )

    def _ready(self, show):
        return self._bounded_read(
            lambda: self.cmd(show).get_output_in_json(),
            lambda value: value["properties"].get("provisioningState") == "Succeeded",
            show,
        )

    def _assert_raw_fields(self, shown):
        raw = self.cmd(
            f"rest --method get --url {shlex.quote(TEST_ARM_ENDPOINT + shown['id'] + '?api-version=' + TEST_API_VERSION)} "
            f"--resource {shlex.quote(TEST_ARM_RESOURCE)}"
        ).get_output_in_json()
        assert raw["id"] == shown["id"]
        assert raw["properties"]["issuer"] == shown["properties"]["issuer"]

    @contextmanager
    def _owned_target(self, microsoft=False):
        namespace = generate_adr_namespace_name()
        scope = f"--ns {namespace} -g {TEST_RG}"
        namespace_id = (
            f"/subscriptions/{TEST_SUBSCRIPTION}/resourceGroups/{TEST_RG}"
            f"/providers/Microsoft.DeviceRegistry/namespaces/{namespace}"
        )
        resources = [
            (namespace_id, "iot adr ns", f"-n {namespace} -g {TEST_RG}", f"--location {TEST_LOCATION}"),
        ]
        if microsoft:
            resources.append((f"{namespace_id}/certificateAuthorities/root", "iot adr ns ca", f"-n root {scope}", "--type Root"))
        resources.append((
            f"{namespace_id}/certificateAuthorities/ica", "iot adr ns ca", f"-n ica {scope}",
            "--type ICA --issuer-type Microsoft --issuer-ca-name root" if microsoft
            else "--type ICA --issuer-type External --key-type ECC",
        ))
        owned = set()
        self._owned_ca_ids = owned
        self._ca_actions = {}
        ledger = CleanupLedger()

        def remove(resource_id, group, args):
            if resource_id not in owned:
                return
            # Include unexpected submissions against an absent child: those also
            # prevent deleting its owned namespace or reusing any ancestor.
            for action in self._ca_actions.values():
                action.wait(cleanup=True)
            show = f"{group} show {args}"
            if not resource_is_absent(self, show):
                self.cmd(f"{group} delete {args} -y")
                wait_for_resource_absent(self, show)
            owned.remove(resource_id)

        for index, (resource_id, group, args, _) in enumerate(resources):
            dependencies = (resources[index + 1][0],) if index + 1 < len(resources) else ()
            ledger.register(
                resource_id, lambda rid=resource_id, group=group, args=args: remove(rid, group, args),
                depends_on=dependencies,
            )
        with ledger:
            for resource_id, group, args, options in resources:
                if not resource_is_absent(self, f"{group} show {args}"):
                    raise AssertionError(f"Refusing to overwrite existing resource {resource_id}.")
                owned.add(resource_id)
                self.cmd(f"{group} create {args} {options}")
                self._ready(f"{group} show {args}")
            assert resources[-1][0] in owned
            yield scope, self.cmd(f"iot adr ns ca show -n ica {scope}").get_output_in_json()

    def _new_ca_tracker(self, resource_id, action, *, missing=False):
        if resource_id in self._ca_actions:
            raise AssertionError("Refusing to replay an action on this disposable CA.")
        owned = self._owned_ca_ids
        if missing:
            assert resource_id.rsplit("/certificateAuthorities/", 1)[0] in owned
            assert resource_id not in owned
            owned = owned | {resource_id}
        tracker = CertificateActionTracker(
            resource_id=resource_id, owned=owned, subscription=TEST_SUBSCRIPTION,
            endpoint=TEST_ARM_ENDPOINT, audience=TEST_ARM_RESOURCE, location=TEST_LOCATION,
            cli_ctx=self.cli_ctx, action=action,
        )
        self._ca_actions[resource_id] = tracker
        return tracker

    @contextmanager
    def _rejected_ca_action(self, resource_id, action, *, missing=False):
        tracker = self._new_ca_tracker(resource_id, action, missing=missing)
        try:
            with tracker.observe(negative=True):
                yield
        finally:
            if not tracker.submitted:
                del self._ca_actions[resource_id]
            tracker.assert_no_submission()

    def _tracked_ca_action(self, before, command, action):
        # Reject local formatting errors before registering a mutation receipt.
        self._apply_kwargs(command)
        tracker = self._new_ca_tracker(before["id"], action)
        with tracker.observe():
            result = self.cmd(command)
        tracker.wait()
        return result

    @staticmethod
    def _sign_service_csr(directory, resource):
        root = Path(directory)
        csr = root / "ica.csr"
        csr.write_text(resource["properties"]["issuer"]["certificateSigningRequest"], encoding="utf-8")
        csr.chmod(0o600)
        assert isinstance(x509.load_pem_x509_csr(csr.read_bytes()).public_key(), ec.EllipticCurvePublicKey)
        key = root / "root.key"
        key.touch(mode=0o600)
        commands = [
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:secp384r1",
             "-nodes", "-keyout", str(key), "-out", str(root / "root.pem"), "-days", "3650",
             "-subj", "/CN=Disposable ADR Root", "-addext", "basicConstraints=critical,CA:TRUE,pathlen:2",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
            ["openssl", "req", "-in", str(csr), "-noout", "-text"],
            ["openssl", "x509", "-req", "-in", str(csr), "-CA", str(root / "root.pem"), "-CAkey", str(key),
             "-set_serial", "2", "-days", "730", "-sha384", "-copy_extensions", "copy", "-out", str(root / "ica.pem")],
        ]
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        chain = make_cert_chain([(root / name).read_text(encoding="utf-8") for name in ("ica.pem", "root.pem")])
        validate_external_certificate_chain(chain, resource)
        path = root / "chain.pem"
        path.write_text(chain, encoding="utf-8")
        return path

    def _external_activation(self, no_wait=False):
        with self._owned_target() as (scope, pending), TemporaryDirectory(prefix="adr-disposable-pki-") as directory:
            if not no_wait:
                for label, text, findings in negative_certificate_chains(pending, now=datetime.now(timezone.utc)):
                    path = Path(directory) / f"{label}.pem"
                    path.write_text(text, encoding="utf-8")
                    with self._rejected_ca_action(pending["id"], "activate"), pytest.raises(CLIError) as raised:
                        self.cmd(f"iot adr ns ca activate -n ica {scope} --ccf {shlex.quote(str(path))}")
                    for finding in findings:
                        assert finding in str(raised.value)
                    unchanged = self.cmd(f"iot adr ns ca show -n ica {scope}").get_output_in_json()
                    assert unchanged["properties"] == pending["properties"]
            chain = self._sign_service_csr(directory, pending)
            if not no_wait:
                with self._rejected_ca_action(pending["id"], "revokeAndRotate"), \
                        pytest.raises(CLIError, match="requires an ICA with issuerType 'Microsoft'"):
                    self.cmd(f"iot adr ns ca revoke -n ica {scope} -y")
                missing_id = pending["id"].rsplit("/", 1)[0] + "/nonexistent-owned-ca"
                with self._rejected_ca_action(missing_id, "activate", missing=True), \
                        pytest.raises((CLIError, HttpResponseError)) as missing:
                    self.cmd(
                        f"iot adr ns ca activate -n nonexistent-owned-ca {scope} --ccf {shlex.quote(str(chain))}"
                    )
                assert is_resource_not_found_error(missing.value)
            result = self._tracked_ca_action(
                pending,
                f"iot adr ns ca activate -n ica {scope} --ccf {shlex.quote(str(chain))}"
                + (" --no-wait" if no_wait else (
                    " --query '{{id:id,name:name,properties:properties,"
                    "prov:properties.provisioningState,status:properties.issuer.status}}'"
                )),
                "activate",
            )
            shown = self._bounded_read(
                lambda: self.cmd(f"iot adr ns ca show -n ica {scope}").get_output_in_json(),
                lambda value: value["properties"]["issuer"].get("status") == "Active",
                description=f"External ICA activation {pending['id']}",
            )
            assert shown["properties"]["issuer"]["thumbprint"]
            assert shown["properties"]["issuer"]["thumbprint"] != pending["properties"]["issuer"].get("thumbprint")
            self._assert_raw_fields(shown)
            if not no_wait:
                output = result.get_output_in_json()
                assert output["id"] == shown["id"]
                assert output["name"] == shown["name"]
                assert output["prov"] == shown["properties"]["provisioningState"]
                assert output["status"] == "Active"
                for field in ("status", "thumbprint"):
                    assert output["properties"]["issuer"][field] == shown["properties"]["issuer"][field]
            else:
                assert result.output.strip() in ("", "null")

    def test_external_activation_recipe(self):
        self._external_activation()

    def test_external_activation_no_wait(self):
        self._external_activation(no_wait=True)

    def _microsoft_revocation(self, no_wait=False):
        if os.getenv("azext_iot_adr_revoke_certificates", "").lower() not in ("1", "true", "yes"):
            pytest.skip("Microsoft revocation requires explicit azext_iot_adr_revoke_certificates opt-in.")
        with self._owned_target(microsoft=True) as (scope, before):
            with TemporaryDirectory(prefix="adr-rejected-activation-") as directory:
                path = Path(directory) / "unused.pem"
                path.write_text("issuer validation must precede PEM parsing", encoding="utf-8")
                for name in ("root", "ica"):
                    resource_id = before["id"].rsplit("/", 1)[0] + "/" + name
                    with self._rejected_ca_action(resource_id, "activate"), \
                            pytest.raises(CLIError, match="requires an ICA with issuerType 'External'"):
                        self.cmd(f"iot adr ns ca activate -n {name} {scope} --ccf {shlex.quote(str(path))}")
            result = self._tracked_ca_action(
                before, f"iot adr ns ca revoke -n ica {scope} -y" + (" --no-wait" if no_wait else ""), "revokeAndRotate",
            )
            if no_wait:
                assert result.output.strip() in ("", "null")
            shown = self._ready(f"iot adr ns ca show -n ica {scope}")
            assert shown["id"] == before["id"]
            self._assert_raw_fields(shown)
            if not no_wait:
                output = result.get_output_in_json()
                assert output["id"] == shown["id"]
                assert output["properties"]["issuer"] == shown["properties"]["issuer"]
                for field in ("subject", "validityNotBefore", "validityNotAfter"):
                    assert output["properties"].get(field) == shown["properties"].get(field)
                    _log(LogKind.RESULT, "Microsoft ICA %s before=%s after=%s (observation, not revocation proof)",
                         field, before["properties"].get(field), shown["properties"].get(field))

    def test_microsoft_revocation(self):
        self._microsoft_revocation()

    def test_microsoft_revocation_no_wait(self):
        self._microsoft_revocation(no_wait=True)


@pytest.mark.usefixtures("set_cwd")
class TestADRCertificateAuthorityLifecycle(ADRLiveScenarioTest):
    """End-to-end certificate authority + certificate policy lifecycle through the CLI."""

    @staticmethod
    def _observe_additional_policy(policy_cmd):
        try:
            additional = policy_cmd("create -n additionalpolicy --validity-days 30").get_output_in_json()
        except (HttpResponseError, CloudError, CLIError) as error:
            if not is_expected_policy_rejection(error):
                raise
            text = str(error)
            if "did not include a detailed error" in text:
                assert "resource-status response" in text or "initial operation response" in text
                assert "Check Azure Activity Log for this resource around the operation time" in text
            _log(LogKind.RESULT, "Additional-policy backend rejection observed: %s", error)
        else:
            assert additional["name"] == "additionalpolicy"
            _log(LogKind.RESULT, "Backend allowed the additional policy; missing-detail live branch unexercised.")

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
            "ica": ("iot adr ns ca", f"-n {ica_name} {scope}", ("policy", "additional-policy")),
            "policy": ("iot adr ns ca policy", f"-n {policy_name} --ca-name {ica_name} {scope}", ()),
            "additional-policy": ("iot adr ns ca policy", f"-n additionalpolicy --ca-name {ica_name} {scope}", ()),
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

            owned.add("additional-policy")
            self._observe_additional_policy(policy_cmd)

            # --- Step 9: Negative: policy under a missing CA fails clearly ---
            with timed_step("Step 9 ❯ Negative: policy on nonexistent CA fails"):
                bad = (
                    f"iot adr ns ca policy create -n {policy_name} --ca-name nonexistent-ca "
                    f"--ns {namespace_name} -g {rg} --validity-days 30"
                )
                _log(LogKind.CMD, "az %s  (expect failure)", bad)
                self.cmd(bad, expect_failure=True)

            # --- Step 10: Delete policy, ICA, then Root ---
            with timed_step("Step 10 ❯ Delete policy and certificate authorities"):
                for label in ("additional-policy", "policy", "ica", "root"):
                    delete_resource(label)
                remaining = [c["name"] for c in ca_cmd("list").get_output_in_json()]
                assert ca_name not in remaining
                assert ica_name not in remaining
                _log(LogKind.OK, "CA '%s' deleted", ca_name)
