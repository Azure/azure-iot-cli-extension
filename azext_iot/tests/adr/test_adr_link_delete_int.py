# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from time import sleep

import pytest
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.base import ADRResourceStateError
from azext_iot.adr.topology import writable_namespace_properties
from azext_iot.adr.rbac import LINK_ROLE_IDS, READER_ROLE, LinkRbacManager, resolve_namespace_outbound_principal
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    ROLE_PROPAGATION_DELAY,
    SU_LIFECYCLE_TIMEOUT,
    wait_for_resource_absent,
)
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
    generate_identity_name,
)
from azext_iot.tests.generators import generate_generic_id


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkDelete(ADRFullInfraHelper, ADRLiveScenarioTest):
    def _reader_assignments(self, principal, scope):
        assignments = self.cmd(
            f"role assignment list --assignee-object-id {principal} --role Reader "
            f"--scope {scope} --fill-principal-name false",
        ).get_output_in_json()
        for assignment in assignments:
            assert assignment["principalId"].casefold() == principal.casefold()
            assert assignment["scope"].casefold() == scope.casefold()
            assert assignment["roleDefinitionId"].rsplit("/", 1)[-1] == LINK_ROLE_IDS[READER_ROLE]
        return assignments

    def _cleanup_reader(self, principal, scope):
        for assignment in self._reader_assignments(principal, scope):
            self.cmd(f"role assignment delete --ids {assignment['id']}")
        assert not self._reader_assignments(principal, scope)

    def _delete_owned_resource(self, kind, name, resource_group, *, no_wait=False):
        super()._delete_owned_resource(kind, name, resource_group, no_wait=kind == "su" or no_wait)
        wait_for_resource_absent(
            self, f"{self._RESOURCE_COMMANDS[kind]} show -n {name} -g {resource_group}",
            timeout=3600 if kind == "su" else 600,
        )

    def _assert_live_target_removal_rejected(self, namespace_name, kind, section, endpoint_name):
        before = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        principal = resolve_namespace_outbound_principal(before)
        scope = before["properties"][section]["endpoints"][endpoint_name]["resourceId"].split("/providers/")[0]
        assert not self._reader_assignments(principal, scope)
        with self.assertLogs("cli.azext_iot.adr", level="WARNING") as logs:
            with pytest.raises((HttpResponseError, ADRResourceStateError)):
                self.cmd(f"iot adr ns link {kind} remove --ns {namespace_name} -g {TEST_RG} -n {endpoint_name} --yes")
        assert any("Cannot confirm read access" in message for message in logs.output), logs.output
        assert not self._reader_assignments(principal, scope), "Unlink must not create Reader grants."
        after = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        assert endpoint_name in after["properties"][section]["endpoints"]
        assert after["tags"] == before["tags"]

    def _remove_endpoint(self, namespace_name, kind, section, endpoint_name, target_name, *, skip_permission_check=False):
        selector = f"--ns {namespace_name} -g {TEST_RG}"
        before = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        principal = resolve_namespace_outbound_principal(before)
        scope = before["properties"][section]["endpoints"][endpoint_name]["resourceId"].split("/providers/")[0]
        existing_reader = self._reader_assignments(principal, scope)
        if not existing_reader:
            self.addCleanup(self._cleanup_reader, principal, scope)
            assert self.assign_role(principal, READER_ROLE, scope, assignee_type="ServicePrincipal")
            sleep(ROLE_PROPAGATION_DELAY)
        prepared_reader = self._reader_assignments(principal, scope)
        assert len(prepared_reader) == 1, "Fixture must prepare the required access before unlink."
        self._delete_owned_resource(kind, target_name, TEST_RG)
        skip_option = " --skip-permission-check" if skip_permission_check else ""
        with self.assertLogs("cli.azext_iot.adr", level="INFO") as logs:
            submitted = self.cmd(
                f"iot adr ns link {kind} remove {selector} -n {endpoint_name} --yes{skip_option}",
            ).get_output_in_json()
        assert not any("Cannot confirm read access" in message or "Could not verify" in message for message in logs.output)
        if not skip_permission_check:
            assert any(
                "Observed a read-capable role assignment" in message
                or "Skipping permission check for endpoint linkingState" in message
                for message in logs.output
            ), logs.output
        else:
            assert not any(
                "Observed a read-capable role assignment" in message
                or "Skipping permission check for endpoint linkingState" in message
                for message in logs.output
            ), logs.output
        assert submitted["id"].casefold() == before["id"].casefold()
        assert submitted["properties"]["provisioningState"] == "Succeeded"
        assert endpoint_name not in submitted["properties"].get(section, {}).get("endpoints", {})
        reader = self._reader_assignments(principal, scope)
        assert reader == prepared_reader, "Unlink must not create, remove or change role assignments."

        after = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        assert after["properties"]["provisioningState"] == "Succeeded"
        for key in ("id", "location", "tags", "identity"):
            assert after.get(key) == before.get(key), key
        expected = writable_namespace_properties(before["properties"])
        del expected[section]["endpoints"][endpoint_name]
        actual = writable_namespace_properties(after["properties"])
        for properties in (actual, expected):
            for endpoint_section in ("messaging", "provisioning", "updating"):
                properties.setdefault(endpoint_section, {}).setdefault("endpoints", {})
        assert actual == expected
        for endpoint_section in ("messaging", "provisioning", "updating"):
            retained = deepcopy(before["properties"].get(endpoint_section, {}).get("endpoints", {}))
            if endpoint_section == section:
                retained.pop(endpoint_name)
            assert after["properties"].get(endpoint_section, {}).get("endpoints", {}) == retained
        self.cmd(f"iot adr ns link {kind} remove {selector} -n {endpoint_name} --yes", expect_failure=True)

    @pytest.mark.timeout(3600)
    def test_adr_link_hub_dps_delete(self):
        namespace_name, first_hub = generate_adr_namespace_name(), generate_hub_name()
        second_hub, dps_name = generate_hub_name(), generate_dps_name()
        try:
            infrastructure = self.setup_full_infra(
                TEST_RG, namespace_name, first_hub, generate_identity_name(), assign_setup_roles=False,
            )
            self.cmd(f"iot adr ns update -n {namespace_name} -g {TEST_RG} --tags unlink-test=preserve")
            dps = self.create_owned_resource(
                f"iot dps create -n {dps_name} -g {TEST_RG} --location {TEST_LOCATION} --system-assigned-mi",
                kind="dps", name=dps_name, resource_group=TEST_RG,
            ).get_output_in_json()
            self.create_owned_resource(
                f"iot hub create -n {second_hub} -g {TEST_RG} --sku S1 --location {TEST_LOCATION} "
                f"--user-assigned-mi {infrastructure['identity_resource_id']}",
                kind="hub", name=second_hub, resource_group=TEST_RG,
            )
            selector = f"--ns {namespace_name} -g {TEST_RG}"
            self.cmd(f"iot adr ns link dps add {selector} -n dps --dps-id {dps['id']} --system-assigned-mi")
            for endpoint_name, hub_name in (("first", first_hub), ("second", second_hub)):
                hub = self.cmd(f"iot hub show -n {hub_name} -g {TEST_RG}").get_output_in_json()
                self.cmd(
                    f"iot adr ns link hub add {selector} -n {endpoint_name} --hub-id {hub['id']} "
                    f"--user-assigned-mi {infrastructure['identity_resource_id']}",
                )
            self._assert_live_target_removal_rejected(namespace_name, "hub", "messaging", "first")
            self._remove_endpoint(namespace_name, "hub", "messaging", "first", first_hub)
            self._remove_endpoint(
                namespace_name, "hub", "messaging", "second", second_hub, skip_permission_check=True,
            )
            self._remove_endpoint(namespace_name, "dps", "provisioning", "dps", dps_name)
        finally:
            self.cleanup_full_infra()

    @pytest.mark.timeout(SU_LIFECYCLE_TIMEOUT * 2)
    def test_adr_link_su_delete(self):
        namespace_name = generate_adr_namespace_name()
        su_name = f"unlinksu{generate_generic_id()[:8]}"
        try:
            namespace = self.create_owned_resource(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG} --location {TEST_LOCATION} "
                "--tags unlink-test=preserve",
                kind="namespace", name=namespace_name, resource_group=TEST_RG,
            ).get_output_in_json()
            su = self.create_owned_resource(
                f"iot adr ns su instance create -n {su_name} -g {TEST_RG} "
                f"--location {TEST_LOCATION} --system-assigned-mi",
                kind="su", name=su_name, resource_group=TEST_RG,
            ).get_output_in_json()
            assert su["properties"]["provisioningState"] == "Succeeded", su
            for role in ("Contributor", "Device Update Administrator"):
                assert self.assign_role(
                    namespace["identity"]["principalId"], role, su["id"], assignee_type="ServicePrincipal",
                ), f"Namespace outbound identity requires {role} on the owned Update Instance."
            sleep(ROLE_PROPAGATION_DELAY)
            self.cmd(
                f"iot adr ns link su add --ns {namespace_name} -g {TEST_RG} -n su "
                f"--su-id {su['id']} --system-assigned-mi --timeout 1200",
            )
            self._remove_endpoint(namespace_name, "su", "updating", "su", su_name)
        finally:
            self.cleanup_full_infra()

    @pytest.mark.timeout(900)
    def test_adr_unlink_missing_rg_advisory(self):
        namespace_name = generate_adr_namespace_name()
        missing_group = f"unlink-absent-{generate_generic_id()}"
        assert self.cmd(f"group exists -n {missing_group}").get_output_in_json() is False
        try:
            namespace = self.create_owned_resource(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG} --location {TEST_LOCATION}",
                kind="namespace", name=namespace_name, resource_group=TEST_RG,
            ).get_output_in_json()
            principal = resolve_namespace_outbound_principal(namespace)
            subscription_scope = "/".join(namespace["id"].split("/")[:3])
            assignments_command = (
                f"role assignment list --assignee-object-id {principal} --scope {subscription_scope} "
                "--include-inherited --fill-principal-name false"
            )
            before = self.cmd(assignments_command).get_output_in_json()
            assert not before
            with self.assertLogs("cli.azext_iot.adr.rbac", level="WARNING") as logs:
                LinkRbacManager(self.cli_ctx).check_unlink_read_access(
                    principal, f"{subscription_scope}/resourceGroups/{missing_group}",
                )
            assert any(
                f"Cannot confirm read access for namespace outbound principalId={principal} at scope={subscription_scope}."
                in message for message in logs.output
            ), logs.output
            assert self.cmd(assignments_command).get_output_in_json() == before
            assert self.cmd(f"group exists -n {missing_group}").get_output_in_json() is False
        finally:
            self.cleanup_full_infra()
