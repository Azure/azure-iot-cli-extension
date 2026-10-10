# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory

import pytest
from knack.util import CLIError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper, CleanupLedger, resource_is_absent, wait_for_resource_absent,
)
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
)
from azext_iot.tests.generators import generate_generic_id


@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceWorkflow(
    ADRFullInfraHelper, ADRLiveScenarioTest
):
    @contextmanager
    def _owned_configuration(self, resources):
        """Claim absent resources before setup can create any of them."""
        for prefix, arguments, _confirmation in resources:
            show = f"{prefix} show {arguments}"
            if not resource_is_absent(self, show):
                raise AssertionError(f"Refusing to overwrite an existing setup resource: {show}")
        ledger = CleanupLedger()

        def remove(prefix, arguments, confirmation):
            show = f"{prefix} show {arguments}"
            if not resource_is_absent(self, show):
                self.cmd(f"{prefix} delete {arguments}{confirmation}")
                wait_for_resource_absent(self, show)

        # Caller supplies child-before-parent/unlink-before-target deletion order.
        for index, resource in reversed(list(enumerate(resources))):
            ledger.register(
                str(index), lambda resource=resource: remove(*resource),
                depends_on=(str(index - 1),) if index else (),
            )
        with ledger:
            yield

    def test_namespace_setup_tagged_plan_is_read_only(self):
        namespace_name = generate_adr_namespace_name()
        plan = self.cmd(
            "iot adr ns setup "
            f"-n {namespace_name} -g {TEST_RG} -l {TEST_LOCATION} "
            "--tags env=integration owner=adr-workflow "
            "--namespace-outbound-identity system-assigned "
            "--plan-only"
        ).get_output_in_json()
        namespace = next(
            item for item in plan["items"] if item["id"] == "namespace"
        )
        assert namespace["state"] == "Planned"
        assert namespace["details"]["tags"] == {
            "env": "integration",
            "owner": "adr-workflow",
        }

    def test_namespace_setup_check_and_resume(self):
        namespace_name = generate_adr_namespace_name()
        setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned"
        )
        try:
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            assert any(
                item["id"] == "namespace" and item["state"] == "Planned"
                for item in plan["items"]
            )

            applied = self.create_owned_resource(
                f"{setup} --yes",
                kind="namespace",
                name=namespace_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            assert applied["state"] == "Succeeded"

            checked = self.cmd(
                f"iot adr ns check -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert checked["state"] == "Succeeded"
            assert checked["summary"]["NotConfigured"] == 3

            resumed = self.cmd(f"{setup} --yes").get_output_in_json()
            assert resumed["state"] == "Succeeded"
            assert any(
                item["id"] == "namespace"
                and item["state"] == "Satisfied"
                for item in resumed["items"]
            )
        finally:
            self.cleanup_full_infra()

    def test_namespace_setup_links_dps(self):
        namespace_name = generate_adr_namespace_name()
        dps_name = generate_dps_name()
        try:
            dps = self.create_owned_resource(
                f"iot dps create -n {dps_name} -g {TEST_RG} "
                f"-l {TEST_LOCATION} --system-assigned-mi",
                kind="dps",
                name=dps_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            setup = (
                f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
                f"-l {TEST_LOCATION} "
                "--namespace-outbound-identity system-assigned "
                f"--dps endpoint=dps-primary resource-id={dps['id']} "
                "identity=system-assigned"
            )
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            applied = self.create_owned_resource(
                f"{setup} --yes",
                kind="namespace",
                name=namespace_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link dps show -n dps-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()["linkingState"] == "Succeeded"
            assert linked

            checked = self.cmd(
                f"iot adr ns check -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert checked["state"] == "Succeeded"
        finally:
            self.cleanup_full_infra()

    def test_namespace_setup_links_hub_after_dps(self):
        namespace_name = generate_adr_namespace_name()
        dps_name = generate_dps_name()
        hub_name = generate_hub_name()
        try:
            dps = self.create_owned_resource(
                f"iot dps create -n {dps_name} -g {TEST_RG} "
                f"-l {TEST_LOCATION} --system-assigned-mi",
                kind="dps",
                name=dps_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            hub = self.create_owned_resource(
                f"iot hub create -n {hub_name} -g {TEST_RG} "
                f"-l {TEST_LOCATION} --sku S1 --system-assigned-mi "
                "--disable-local-auth true",
                kind="hub",
                name=hub_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            dps_setup = (
                f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
                f"-l {TEST_LOCATION} "
                "--namespace-outbound-identity system-assigned "
                f"--dps endpoint=dps-primary resource-id={dps['id']} "
                "identity=system-assigned"
            )
            hub_setup = (
                f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
                f"--hub endpoint=hub-primary resource-id={hub['id']} "
                "identity=system-assigned"
            )
            assert self.create_owned_resource(
                f"{dps_setup} --yes",
                kind="namespace",
                name=namespace_name,
                resource_group=TEST_RG,
            ).get_output_in_json()["state"] == "Succeeded"
            plan = self.cmd(
                f"{hub_setup} --plan-only"
            ).get_output_in_json()
            assert plan["state"] == "Planned"
            applied = self.cmd(f"{hub_setup} --yes").get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link hub show -n hub-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert linked["linkingState"] == "Succeeded"
        finally:
            self.cleanup_full_infra()

    def test_namespace_setup_links_software_updates(self):
        namespace_name = generate_adr_namespace_name()
        update_instance_name = f"testsu{generate_generic_id()[:8]}"
        subscription_id = self.get_subscription_id()
        update_instance_id = (
            f"/subscriptions/{subscription_id}/resourceGroups/{TEST_RG}"
            "/providers/Microsoft.DeviceUpdate/updateInstances/"
            f"{update_instance_name}"
        )
        namespace_setup = (
            f"iot adr ns setup -n {namespace_name} -g {TEST_RG} "
            f"-l {TEST_LOCATION} "
            "--namespace-outbound-identity system-assigned"
        )
        setup = (
            f"{namespace_setup} "
            "--software-updates endpoint=su-primary "
            f"resource-id={update_instance_id} identity=system-assigned "
            "create-if-missing=true"
        )
        try:
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            # Create the namespace separately so each setup mutation has its
            # own absence check and ownership record before it can create.
            namespace = self.create_owned_resource(
                f"{namespace_setup} --yes",
                kind="namespace",
                name=namespace_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            assert namespace["state"] == "Succeeded"
            applied = self.create_owned_resource(
                f"{setup} --yes",
                kind="su",
                name=update_instance_name,
                resource_group=TEST_RG,
            ).get_output_in_json()
            assert applied["state"] == "Succeeded"
            linked = self.cmd(
                f"iot adr ns link su show -n su-primary "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert linked["linkingState"] == "Succeeded"
        finally:
            self.cleanup_full_infra()

    def test_namespace_setup_json_managed_cms_reuse(self):
        namespace = generate_adr_namespace_name()
        scope = f"--ns {namespace} -g {TEST_RG}"
        namespace_args = f"-n {namespace} -g {TEST_RG}"
        config = {
            "schemaVersion": 1,
            "subscriptionId": self.get_subscription_id(),
            "namespace": {
                "name": namespace, "resourceGroup": TEST_RG, "location": TEST_LOCATION,
                "outboundIdentity": {"type": "SystemAssigned"},
            },
            "cms": {
                "enabled": True, "rootName": "setup-root", "intermediateName": "setup-ica",
                "policyName": "setup-devices", "validityDays": 30,
            },
            "checkStatus": True,
        }
        resources = [
            ("iot adr ns ca policy", f"-n setup-devices --ca-name setup-ica {scope}", " --yes"),
            ("iot adr ns ca", f"-n setup-ica {scope}", " --yes"),
            ("iot adr ns ca", f"-n setup-root {scope}", " --yes"),
            ("iot adr ns", namespace_args, " --yes"),
        ]
        with self._owned_configuration(resources), TemporaryDirectory(prefix="adr-setup-json-") as directory:
            path = Path(directory) / "managed.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            setup = f"iot adr ns setup --config {shlex.quote('@' + str(path))} --no-input"
            plan = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert plan["state"] == "Planned"
            assert resource_is_absent(self, f"iot adr ns show {namespace_args}")
            assert self.cmd(f"{setup} --yes").get_output_in_json()["state"] == "Succeeded"
            issuing = self.cmd(f"iot adr ns ca show -n setup-ica {scope}").get_output_in_json()
            assert issuing["properties"]["issuer"]["issuerType"] == "Microsoft"
            policy_show = f"iot adr ns ca policy show -n setup-devices --ca-name setup-ica {scope}"
            policy = self.cmd(policy_show).get_output_in_json()
            assert policy["properties"]["certificate"]["validityPeriodInDays"] == 30
            assert self.cmd(f"{setup} --yes").get_output_in_json()["state"] == "Succeeded"
            assert self.cmd(policy_show).get_output_in_json()["id"] == policy["id"]
            assert self.cmd(f"iot adr ns check {namespace_args}").get_output_in_json()["state"] == "Succeeded"

            incompatible = deepcopy(config)
            incompatible["cms"]["validityDays"] = 31
            path.write_text(json.dumps(incompatible), encoding="utf-8")
            blocked = self.cmd(f"{setup} --plan-only").get_output_in_json()
            assert blocked["state"] == "Blocked"
            assert self.cmd(policy_show).get_output_in_json()["properties"]["certificate"]["validityPeriodInDays"] == 30

    def test_namespace_setup_json_creates_link_targets(self):
        namespace = generate_adr_namespace_name()
        dps_name = generate_dps_name()
        hub_name = generate_hub_name()
        namespace_args = f"-n {namespace} -g {TEST_RG}"
        config = {
            "schemaVersion": 1,
            "subscriptionId": self.get_subscription_id(),
            "namespace": {
                "name": namespace, "resourceGroup": TEST_RG, "location": TEST_LOCATION,
                "outboundIdentity": {"type": "SystemAssigned"},
            },
            "links": {
                "dps": {"resourceName": dps_name, "identity": "system-assigned", "createIfMissing": True},
                "hubs": [{
                    "resourceName": hub_name, "identity": "system-assigned", "createIfMissing": True,
                    "sku": "S1", "unit": 1,
                }],
            },
            "checkStatus": True,
        }
        resources = [
            ("iot adr ns", namespace_args, " --yes"),
            ("iot dps", f"-n {dps_name} -g {TEST_RG}", ""),
            ("iot hub", f"-n {hub_name} -g {TEST_RG}", ""),
        ]
        with self._owned_configuration(resources), TemporaryDirectory(prefix="adr-setup-json-") as directory:
            path = Path(directory) / "connected.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            setup = f"iot adr ns setup --config {shlex.quote(str(path))} --no-input"
            assert self.cmd(f"{setup} --plan-only").get_output_in_json()["state"] == "Planned"
            for prefix, arguments, _ in resources:
                assert resource_is_absent(self, f"{prefix} show {arguments}")
            assert self.cmd(f"{setup} --yes").get_output_in_json()["state"] == "Succeeded"
            hub = self.cmd(f"iot hub show -n {hub_name} -g {TEST_RG}").get_output_in_json()
            assert hub["properties"]["disableLocalAuth"] is True
            assert hub["location"].replace(" ", "").lower() == TEST_LOCATION.replace(" ", "").lower()
            assert self.cmd(f"{setup} --yes").get_output_in_json()["state"] == "Succeeded"
            assert self.cmd(f"iot adr ns check {namespace_args}").get_output_in_json()["state"] == "Succeeded"

    def test_namespace_setup_json_rejects_invalid_input_before_creation(self):
        namespace = generate_adr_namespace_name()
        config = {"namespace": {"name": namespace, "resourceGroup": TEST_RG, "location": TEST_LOCATION}}
        show = f"iot adr ns show -n {namespace} -g {TEST_RG}"
        assert resource_is_absent(self, show)
        with TemporaryDirectory(prefix="adr-invalid-setup-") as directory:
            path = Path(directory) / "invalid.json"
            external = dict(config, cms={"enabled": True, "issuerType": "External"})
            for text in ("{broken", json.dumps(dict(config, unknownOption=True)), json.dumps(external)):
                path.write_text(text, encoding="utf-8")
                with pytest.raises(CLIError):
                    self.cmd(f"iot adr ns setup --config {shlex.quote(str(path))} --no-input --yes")
                assert resource_is_absent(self, show)
