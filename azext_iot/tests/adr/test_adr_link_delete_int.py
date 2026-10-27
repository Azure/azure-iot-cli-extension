# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import re
from time import sleep
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from azure.cli.core.azclierror import AzureResponseError
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger

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
from azext_iot.tests.adr._readiness import link_dps_with_readiness, link_hub_with_readiness
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
    generate_identity_name,
)
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.settings import HUB_TEST_LOCATION

logger = get_logger(__name__)


def _assert_unlink_service_rejection(error, namespace_id):
    if isinstance(error, ADRResourceStateError):
        body = error.body
        assert body.get("id", "").casefold() == namespace_id.casefold(), "Failure belongs to another namespace."
        assert body.get("properties", {}).get("provisioningState") == "Failed", "Unlink did not reach a Failed state."
        logger.info("Unlink rejection: type=ADRResourceStateError code=unavailable correlationId=unavailable")
        return None
    response = getattr(error, "response", None)
    request = getattr(response, "request", None)
    method = getattr(request, "method", None)
    path = urlsplit(getattr(request, "url", "")).path
    if error.status_code == 400:
        assert method == "PUT", "Failure did not reject the namespace mutation."
        assert path.casefold() == namespace_id.casefold(), "Failure belongs to another resource."
    else:
        assert error.status_code == 200 and method == "GET", f"Unexpected unlink HTTP failure: {error.status_code}"
        subscription = namespace_id.split("/")[2]
        assert re.fullmatch(
            rf"/subscriptions/{re.escape(subscription)}/providers/Microsoft\.DeviceRegistry/"
            r"locations/[^/]+/(?:asyncOperationStatuses|operationStatuses)/[^/]+", path, re.IGNORECASE,
        ), "Failure did not come from this subscription's ADR operation-status endpoint."
        assert response.json().get("status") == "Failed", "Unlink operation did not fail."
    code = getattr(error.error, "code", None)
    assert isinstance(code, str) and re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.-]{0,63}", code,
    ), "Unlink rejection did not include a structured service error code."
    headers = getattr(response, "headers", {}) or {}
    correlation = headers.get("x-ms-correlation-request-id") or headers.get("x-ms-request-id")
    try:
        correlation = str(UUID(correlation)) if isinstance(correlation, str) else "unavailable"
    except ValueError:
        correlation = "unavailable"
    logger.info("Unlink rejection: type=HttpResponseError code=%s correlationId=%s", code, correlation)
    return code


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
            with pytest.raises((HttpResponseError, ADRResourceStateError)) as rejected:
                self.cmd(f"iot adr ns link {kind} remove --ns {namespace_name} -g {TEST_RG} -n {endpoint_name} --yes")
        _assert_unlink_service_rejection(rejected.value, before["id"])
        assert any("Cannot confirm read access" in message for message in logs.output), logs.output
        assert not self._reader_assignments(principal, scope), "Unlink must not create Reader grants."
        after = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        assert endpoint_name in after["properties"][section]["endpoints"]
        assert after["tags"] == before["tags"]

    def _assert_requested_reader_retained(self, namespace_name, kind, section, endpoint_name):
        before = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        endpoint = before["properties"][section]["endpoints"][endpoint_name]
        assert endpoint["linkingState"] == "Succeeded", endpoint
        principal = resolve_namespace_outbound_principal(before)
        scope = endpoint["resourceId"].split("/providers/")[0]
        assert not self._reader_assignments(principal, scope)
        self.addCleanup(self._cleanup_reader, principal, scope)
        command = (
            f"iot adr ns link {kind} remove --ns {namespace_name} -g {TEST_RG} -n {endpoint_name} --yes --grant-reader"
        )
        with pytest.raises((HttpResponseError, ADRResourceStateError)) as rejected:
            self.cmd(command)
        first_code = _assert_unlink_service_rejection(rejected.value, before["id"])
        created = self._reader_assignments(principal, scope)
        assert len(created) == 1, "Explicit grant must be retained after service rejection."
        sleep(ROLE_PROPAGATION_DELAY)
        with pytest.raises((HttpResponseError, ADRResourceStateError)) as rejected:
            self.cmd(command)
        second_code = _assert_unlink_service_rejection(rejected.value, before["id"])
        if first_code is not None and second_code is not None:
            assert first_code == second_code, "Repeated unlink attempts returned different service rejections."
        assert self._reader_assignments(principal, scope) == created, "Retry must not duplicate the Reader assignment."
        after = self.cmd(f"iot adr ns show -n {namespace_name} -g {TEST_RG}").get_output_in_json()
        assert endpoint_name in after["properties"][section]["endpoints"]
        assert after["identity"] == before["identity"]
        assert after["tags"] == before["tags"]

    def _remove_endpoint(
        self, namespace_name, kind, section, endpoint_name, target_name, *, skip_rbac_check=False, grant_reader=False,
    ):
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
        permission_option = " --no-rbac-check" if skip_rbac_check else " --grant-reader" if grant_reader else ""
        with self.assertLogs("cli.azext_iot.adr", level="INFO") as logs:
            submitted = self.cmd(
                f"iot adr ns link {kind} remove {selector} -n {endpoint_name} --yes{permission_option}",
            ).get_output_in_json()
        assert not any("Cannot confirm read access" in message or "Could not verify" in message for message in logs.output)
        if not skip_rbac_check:
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
        assert submitted.get("identity") == before.get("identity")
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
            identity_resource_id = infrastructure["identity_resource_id"]
            extra_identity_name = generate_identity_name()
            extra_identity = self.create_owned_resource(
                f"identity create -n {extra_identity_name} -g {TEST_RG} --location {TEST_LOCATION}",
                kind="identity", name=extra_identity_name, resource_group=TEST_RG,
            ).get_output_in_json()
            attached = self.cmd(
                f"iot adr ns identity assign -n {namespace_name} -g {TEST_RG} --user {extra_identity['id']}",
            ).get_output_in_json()
            assert "SystemAssigned" in attached["type"]
            assert "UserAssigned" in attached["type"]
            assert {identity_id.casefold() for identity_id in attached["userAssignedIdentities"]} == {
                identity_resource_id.casefold(), extra_identity["id"].casefold(),
            }
            self.cmd(f"iot adr ns update -n {namespace_name} -g {TEST_RG} --tags unlink-test=preserve")
            dps = self.create_owned_resource(
                f"iot dps create -n {dps_name} -g {TEST_RG} --location {TEST_LOCATION} --system-assigned-mi",
                kind="dps", name=dps_name, resource_group=TEST_RG,
            ).get_output_in_json()
            dps_id = dps["id"]
            self.create_owned_resource(
                f"iot hub create -n {second_hub} -g {TEST_RG} --sku S1 --location {HUB_TEST_LOCATION} "
                f"--user-assigned-mi {identity_resource_id} --disable-local-auth true",
                kind="hub", name=second_hub, resource_group=TEST_RG,
            )
            selector = f"--ns {namespace_name} -g {TEST_RG}"
            link_dps_with_readiness(
                self,
                f"iot adr ns link dps add {selector} -n dps --dps-id {dps_id} --system-assigned-mi",
                namespace_name,
                TEST_RG,
                "dps",
                {
                    "resourceId": dps_id,
                    "inboundCallerIdentity": {"type": "SystemAssigned"},
                },
            )
            for endpoint_name, hub_name in (("first", first_hub), ("second", second_hub)):
                hub = self.cmd(f"iot hub show -n {hub_name} -g {TEST_RG}").get_output_in_json()
                hub_id = hub["id"]
                add_cmd = (
                    f"iot adr ns link hub add {selector} -n {endpoint_name} --hub-id {hub_id} "
                    f"--user-assigned-mi {identity_resource_id} --availability Available --allocation-weight 1"
                )
                link_hub_with_readiness(
                    self, add_cmd, namespace_name, TEST_RG, endpoint_name,
                    {
                        "resourceId": hub_id,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned",
                            "userAssignedIdentity": identity_resource_id,
                        },
                        "provisioning": {"availability": "Available", "allocationWeight": 1},
                    },
                )
            self._assert_live_target_removal_rejected(namespace_name, "hub", "messaging", "first")
            self._assert_requested_reader_retained(namespace_name, "hub", "messaging", "first")
            self._remove_endpoint(namespace_name, "hub", "messaging", "first", first_hub, grant_reader=True)
            self._remove_endpoint(
                namespace_name, "hub", "messaging", "second", second_hub, skip_rbac_check=True,
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
            assert namespace["identity"]["type"] == "SystemAssigned"
            assert namespace["identity"]["principalId"]
            assert not namespace["identity"].get("userAssignedIdentities")
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
            self._assert_requested_reader_retained(namespace_name, "su", "updating", "su")
            self._remove_endpoint(namespace_name, "su", "updating", "su", su_name, grant_reader=True)
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
            with pytest.raises(AzureResponseError, match="never creates subscription-scoped assignments") as raised:
                LinkRbacManager(self.cli_ctx).check_unlink_read_access(
                    principal, f"{subscription_scope}/resourceGroups/{missing_group}", grant_reader=True,
                )
            assert f"--scope '{subscription_scope}'" in str(raised.value)
            assert self.cmd(assignments_command).get_output_in_json() == before
            assert self.cmd(f"group exists -n {missing_group}").get_output_in_json() is False
        finally:
            self.cleanup_full_infra()
