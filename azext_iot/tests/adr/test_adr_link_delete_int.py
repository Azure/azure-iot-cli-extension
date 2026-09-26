# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from time import sleep

import pytest

from azext_iot.adr.topology import writable_namespace_properties
from azext_iot.adr.rbac import LINK_ROLE_IDS, READER_ROLE, resolve_namespace_outbound_principal
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    ROLE_PROPAGATION_DELAY,
    SU_LIFECYCLE_TIMEOUT,
    wait_for_condition,
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

    def _remove_endpoint(self, namespace_name, kind, section, endpoint_name, target_name):
        selector = f"--ns {namespace_name} -g {TEST_RG}"
        before = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        assert before["properties"][section]["endpoints"][endpoint_name]["linkingState"] == "Succeeded"
        principal = resolve_namespace_outbound_principal(before)
        scope = before["properties"][section]["endpoints"][endpoint_name]["resourceId"].split("/providers/")[0]
        existing_reader = self._reader_assignments(principal, scope)
        if not existing_reader:
            self.addCleanup(self._cleanup_reader, principal, scope)
        self._delete_owned_resource(kind, target_name, TEST_RG)
        submitted = self.cmd(
            f"iot adr ns link {kind} delete {selector} -n {endpoint_name} --yes",
        ).get_output_in_json()
        assert submitted["id"].casefold() == before["id"].casefold()
        assert submitted["properties"]["provisioningState"] in {"Accepted", "Updating", "Succeeded"}
        reader = self._reader_assignments(principal, scope)
        assert len(reader) == 1
        if existing_reader:
            assert reader[0]["id"] == existing_reader[0]["id"], "Reuse Reader rather than creating duplicate grants."

        # Completion belongs to the test, not the nonwaiting delete command.
        after = wait_for_condition(
            lambda: self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json(),
            lambda ns: ns["properties"]["provisioningState"] == "Succeeded"
            and endpoint_name not in ns["properties"].get(section, {}).get("endpoints", {}),
            description=f"{kind} endpoint '{endpoint_name}' removal",
            is_terminal_failure=lambda ns: ns["properties"]["provisioningState"] in {"Failed", "Canceled", "Cancelled"},
            timeout=600,
            describe=lambda ns: str(ns["properties"]),
        )
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
        self.cmd(f"iot adr ns link {kind} delete {selector} -n {endpoint_name} --yes", expect_failure=True)

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
            self._remove_endpoint(namespace_name, "hub", "messaging", "first", first_hub)
            self._remove_endpoint(namespace_name, "hub", "messaging", "second", second_hub)
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
