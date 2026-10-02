# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
ADR link integration tests.

Validates the namespace-linking surface exposed as ``iot adr ns link ...``:

* ``link dps add / update / show / list`` — including the ``brownfieldHubs``
  enumeration surfaced by ``dps show`` (DPS-side ``properties.iotHubs[]``)
* ``link hub add / update / show / list`` — both UAMI and SAMI inbound caller
  identities, multi-hub list, identity rotation via ``hub update``
* Combined ``link add`` — DPS must succeed before the command submits a Hub link

These tests require real Hub and DPS resources to be linked to a real ADR
namespace, so they re-use :class:`ADRFullInfraHelper` to provision the full
infrastructure once per test class and exercise the link CLI surface against
it. ``setup_full_infra`` creates a Standard Hub independently. Every
relationship in this suite is created only through namespace-side link
commands.

What is intentionally NOT covered here (covered by unit tests):
- Failed-Hub retry without DPS (requires deliberately inducing a backend link failure)
- MI mutually-exclusive rejection
- Invalid DPS resource id rejection

Owned Hub and DPS adds use the native 600-second default for actual
namespace/endpoint readiness, including authorization propagation recovery via link update.
The dedicated combined scenario instead uses native command recovery with
fresh service roles, explicit 1200-second mutation budgets, and no fixture repair.
"""

import os
import re
import shlex
from time import monotonic, sleep
from typing import Optional

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
)

from azext_iot._factory import _ADR_DPS_API_VERSION
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    wait_for_condition,
)
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr._readiness import (
    _LINK_INITIATE_REJECTED, LINK_READINESS_TIMEOUT, link_dps_with_readiness, link_hub_with_readiness,
)

from azext_iot.tests.adr.conftest import (
    TEST_ARM_ENDPOINT,
    TEST_ARM_RESOURCE,
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
    generate_identity_name,
)
from azext_iot.tests.settings import HUB_TEST_LOCATION
from azext_iot.adr.topology import (
    DPS_CAP_EXCEEDED_MSG,
)
from azext_iot.adr.rbac import (
    CONTRIBUTOR_ROLE,
    HUB_DATA_ROLE,
    resolve_namespace_outbound_principal,
)


_LINKING_POLL_ATTEMPTS = int(os.getenv("azext_iot_adr_su_link_poll_attempts", "240"))
_LINKING_POLL_INTERVAL_SECONDS = 10
_NATIVE_LINK_TIMEOUT = 1200
_NATIVE_LINK_INTERVAL = 10
_NATIVE_LINK_OPTIONS = f"--timeout {_NATIVE_LINK_TIMEOUT} --interval {_NATIVE_LINK_INTERVAL}"
_HUB_IDENTITY_ROTATION_BACKOFFS = (30, 60, 120)
_HUB_IDENTITY_ROTATION_BUDGET_SECONDS = 600
_HUB_ROTATION_REJECTED_CHAIN = re.compile(r"\(IdentityRotationUpdateFailed\) " + _LINK_INITIATE_REJECTED.pattern)
_HUB_ROTATION_REJECTED_MESSAGE = re.compile(r"(?:IdentityRotationUpdateFailed: )?" + _LINK_INITIATE_REJECTED.pattern)
_TERMINAL_LINK_STATES = {"Succeeded", "Failed", "Canceled", "Cancelled"}


def _link_properties(shown):
    return shown.get("properties") or shown


def _link_observation(shown):
    properties = _link_properties(shown)
    identity = properties.get("inboundCallerIdentity") or {}
    return properties.get("linkingState"), identity.get("type")


def _link_failure_detail(shown):
    properties = _link_properties(shown)
    status = properties.get("provisioningStatus") or properties.get("status") or {}
    error = properties.get("linkingError") or status.get("error") or properties.get("error") or {}
    return error if isinstance(error, dict) else {}


def _error_chain_text(error):
    seen = set()
    texts = []
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        texts.append(str(current))
        detail = getattr(current, "error", None)
        code = detail.get("code") if isinstance(detail, dict) else getattr(detail, "code", None)
        if isinstance(code, str):
            texts.append(code)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return " ".join(texts)


def _structured_hub_rotation_rejection(endpoint):
    """Persisted form, held to the same structural guards as the DPS readiness classifier."""
    properties = _link_properties(endpoint or {})
    error = properties.get("linkingError")
    if properties.get("linkingState") != "Failed" or not isinstance(error, dict) or set(error) - {"code", "message"}:
        return False
    message = error.get("message")
    match = _HUB_ROTATION_REJECTED_MESSAGE.fullmatch(message) if isinstance(message, str) else None
    return bool(error.get("code") == "IdentityRotationUpdateFailed" and match and match["service"] == "Hub")


def _is_identity_rotation_authorization_failure(*, error=None, endpoint=None):
    detail = _link_failure_detail(endpoint or {}) if endpoint else {}
    chain = _error_chain_text(error) if error else ""
    text = " ".join(filter(None, [detail.get("code"), detail.get("message"), chain]))
    if "IdentityRotationUpdateFailed" not in text:
        return False
    # The generic "rejected as invalid" text is otherwise a permanent configuration error; accept it only
    # when the service attributes it to identity rotation, either in the error chain or the persisted state.
    rejected = _HUB_ROTATION_REJECTED_CHAIN.search(chain)
    return bool(
        (rejected and rejected["service"] == "Hub")
        or _structured_hub_rotation_rejection(endpoint)
        or "IH400913" in text
        or re.search(
            r"\b(denied|not authorized|does not have authorization|AuthorizationFailed)\b",
            text,
            re.IGNORECASE,
        )
    )


def _show_link(test_case, link_kind, namespace_name, resource_group_name, endpoint_name):
    return test_case.cmd(
        f"iot adr ns link {link_kind} show --ns {namespace_name} "
        f"-g {resource_group_name} -n {endpoint_name}"
    ).get_output_in_json()


def _wait_for_link_terminal(
    test_case, link_kind, namespace_name, resource_group_name, endpoint_name, *, timeout,
):
    def fetch():
        return _show_link(test_case, link_kind, namespace_name, resource_group_name, endpoint_name)

    return wait_for_condition(
        fetch,
        lambda shown: _link_observation(shown)[0] in _TERMINAL_LINK_STATES,
        description=f"{link_kind} endpoint '{endpoint_name}' terminal linking state",
        timeout=timeout,
        interval=_LINKING_POLL_INTERVAL_SECONDS,
        describe=lambda shown: (
            f"linkingState={_link_observation(shown)[0]!r}, "
            f"identityType={_link_observation(shown)[1]!r}, "
            f"failure={_link_failure_detail(shown)}"
        ),
    )


def _assert_hub_rotation_retry_safe(endpoint, hub_id, previous_user_identity):
    properties = _link_properties(endpoint)
    assert properties.get("resourceId", "").casefold() == hub_id.casefold(), properties
    identity = properties.get("inboundCallerIdentity") or {}
    identity_type = identity.get("type")
    assert identity_type in {"SystemAssigned", "UserAssigned"}, properties
    if identity_type == "UserAssigned":
        assert identity.get("userAssignedIdentity", "").casefold() == previous_user_identity.casefold(), properties


def _assert_hub_sami_rotation_grants(test_case, namespace_name, resource_group_name, hub_id):
    namespace = test_case.cmd(
        f"iot adr ns show -n {namespace_name} -g {resource_group_name}"
    ).get_output_in_json()
    hub = test_case.cmd(
        f"iot hub show --ids {shlex.quote(hub_id)}"
    ).get_output_in_json()
    namespace_principal = namespace["identity"]["principalId"]
    hub_principal = hub["identity"]["principalId"]
    _assert_service_roles(
        test_case,
        [
            (namespace_principal, CONTRIBUTOR_ROLE, hub_id),
            (namespace_principal, HUB_DATA_ROLE, hub_id),
            (hub_principal, CONTRIBUTOR_ROLE, namespace["id"]),
        ],
        present=True,
    )


def _update_hub_to_sami_with_recovery(
    test_case, update_cmd, namespace_name, resource_group_name, endpoint_name, hub_id, previous_user_identity,
):
    deadline = monotonic() + _HUB_IDENTITY_ROTATION_BUDGET_SECONDS

    def submit():
        # Bound the synchronous link wait so a slow mutation cannot outlive the recovery budget.
        test_case.cmd(f"{update_cmd} --timeout {max(1, int(deadline - monotonic()))}")

    first_error = None
    try:
        submit()
    except Exception as error:  # noqa: BLE001 - only recovered when persisted state proves the known race.
        first_error = error

    for attempt in range(len(_HUB_IDENTITY_ROTATION_BACKOFFS) + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        endpoint = _wait_for_link_terminal(
            test_case, "hub", namespace_name, resource_group_name, endpoint_name, timeout=remaining,
        )
        state, identity_type = _link_observation(endpoint)
        if state == "Succeeded" and identity_type == "SystemAssigned":
            return endpoint
        recoverable = _is_identity_rotation_authorization_failure(error=first_error, endpoint=endpoint)
        if state not in {"Failed", "Succeeded"} or not recoverable:
            if first_error is not None:
                raise first_error
            raise AssertionError(f"Non-recoverable Hub identity rotation failure: {_link_failure_detail(endpoint)}")
        if attempt == len(_HUB_IDENTITY_ROTATION_BACKOFFS):
            break
        _assert_hub_rotation_retry_safe(endpoint, hub_id, previous_user_identity)
        _assert_hub_sami_rotation_grants(test_case, namespace_name, resource_group_name, hub_id)
        sleep_for = _HUB_IDENTITY_ROTATION_BACKOFFS[attempt]
        # Never start another mutation that could not be observed within the recovery budget.
        if deadline - monotonic() <= sleep_for:
            break
        sleep(sleep_for)
        first_error = None
        try:
            submit()
        except Exception as error:  # noqa: BLE001 - recovered only with matching persisted failure evidence.
            first_error = error
    raise AssertionError("Hub identity rotation authorization recovery budget exhausted") from first_error


def _assert_service_roles(test_case, roles, *, present):
    for principal, role, scope in roles:
        assignments = test_case.cmd(
            f"role assignment list --assignee-object-id {principal} "
            f"--role '{role}' --scope '{scope}' --include-inherited --fill-principal-name false"
        ).get_output_in_json()
        assert isinstance(assignments, list), assignments
        assert bool(assignments) is present, (
            f"Expected {'existing' if present else 'no preauthorized'} {role} "
            f"for service principal {principal} on {scope}; assignments={assignments}"
        )


def _assert_native_link_result(namespace, section, name, resource_id, inbound_identity):
    assert namespace["properties"]["provisioningState"] == "Succeeded", namespace
    endpoint = namespace["properties"][section]["endpoints"][name]
    assert endpoint["linkingState"] == "Succeeded", endpoint
    assert endpoint["resourceId"].casefold() == resource_id.casefold(), endpoint
    actual = endpoint["inboundCallerIdentity"]
    assert actual["type"] == inbound_identity["type"], endpoint
    if inbound_identity["type"] == "UserAssigned":
        assert actual["userAssignedIdentity"].casefold() == inbound_identity["userAssignedIdentity"].casefold(), endpoint


def _assert_dps_blocks_namespace_sami_removal(test_case, namespace_name, resource_group_name):
    test_case.cmd(
        f"iot adr ns identity remove -n {namespace_name} -g {resource_group_name} "
        "--system-assigned",
        expect_failure=True,
    )
    identity = test_case.cmd(
        f"iot adr ns identity show -n {namespace_name} -g {resource_group_name}"
    ).get_output_in_json()
    assert "SystemAssigned" in str(identity.get("type") or ""), identity


def _assert_cli_failure(test_case, command: str, expected_message: str):
    with pytest.raises(
        ArgumentUsageError,
        match=re.escape(expected_message),
    ):
        test_case.cmd(command)


def _wait_for_linking_succeeded(
    test_case,
    link_kind: str,
    namespace_name: str,
    resource_group_name: str,
    endpoint_name: str,
    expected_identity_type: Optional[str] = None,
) -> dict:
    """Poll a namespace endpoint until its contract linking state succeeds."""
    def succeeded(shown):
        linking_state, identity_type = _link_observation(shown)
        return linking_state == "Succeeded" and (
            expected_identity_type is None
            or identity_type == expected_identity_type
        )

    return wait_for_condition(
        lambda: _show_link(test_case, link_kind, namespace_name, resource_group_name, endpoint_name),
        succeeded,
        description=f"{link_kind} endpoint '{endpoint_name}' linking",
        is_terminal_failure=lambda shown: _link_observation(shown)[0] == "Failed",
        timeout=None,
        interval=_LINKING_POLL_INTERVAL_SECONDS,
        max_attempts=_LINKING_POLL_ATTEMPTS,
        describe=lambda shown: (
            f"linkingState={_link_observation(shown)[0]!r}, "
            f"identityType={_link_observation(shown)[1]!r}"
        ),
    )


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkLifecycle(ADRFullInfraHelper, ADRLiveScenarioTest):
    """End-to-end lifecycle of namespace-side Hub and DPS link entries.

    The flow follows the design's enforced DPS-first ordering and exercises
    both inbound caller identity variants (UAMI and SAMI):

    1. Setup: provision ADR + UAMI + an independent Standard primary Hub
    2. Step 1: create a standalone DPS without classic Hub registrations,
       then ``link dps add`` to attach the DPS to the namespace
    3. Step 2: ``link dps show`` / ``list`` projects the DPS endpoint
    4. Step 3-4: secondary Hub linked with **UAMI**; verify its namespace
       endpoint and the read-only DPS ``brownfieldHubs`` projection separately
    5. Step 5-6: tertiary Hub linked with **SAMI** + multi-hub list assertion
    6. Step 7-8: ``link hub update`` rotates inbound identities
    7. Step 9: ``link dps update`` rotates DPS identity
    Cleanup deletes only the namespace, targets and identity created by this test.
    """

    # Retain the suite's existing 900s for three-Hub setup, lifecycle and cleanup.
    # Reserve one bounded readiness window per add: two Hubs and one DPS;
    # do not spend their propagation retries out of the existing cleanup allowance.
    @pytest.mark.timeout(900 + 3 * LINK_READINESS_TIMEOUT, func_only=False)
    def test_adr_link_lifecycle(self):
        _log(LogKind.TEST, "test_adr_link_lifecycle")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        primary_hub = generate_hub_name()  # independent resource; not auto-linked
        secondary_hub = generate_hub_name()  # linked via `link hub add` (UAMI)
        tertiary_hub = generate_hub_name()  # linked via `link hub add` (SAMI)
        dps_name = generate_dps_name()
        identity_name = generate_identity_name()

        secondary_endpoint = "secondary"
        tertiary_endpoint = "tertiary"
        dps_endpoint = "dps-primary"

        def _names_in(listed):
            """Read endpoint names from the 2026 named-object list shape."""
            assert isinstance(listed, list)
            return {item["name"] for item in listed}

        try:
            infra = self.setup_full_infra(
                resource_group=rg,
                namespace_name=namespace_name,
                hub_name=primary_hub,
                identity_name=identity_name,
                assign_setup_roles=False,
            )
            identity_resource_id = infra["identity_resource_id"]

            # The setup Hub is intentionally independent. The namespace's
            # properties.messaging.endpoints collection is the only ownership
            # model, and link tests add endpoint entries explicitly.

            # DPS must be linked before adding namespace Hubs. Once linked,
            # its classic Hub registrations are read-only.
            with timed_step("Step 1 ❯ link dps add"):
                cmd = (
                    f"iot dps create --name {dps_name} -g {rg} "
                    f"--location {TEST_LOCATION} --disable-local-auth true "
                    f"--user-assigned-mi {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", cmd)
                self.create_owned_resource(cmd, kind="dps", name=dps_name, resource_group=rg)
                _log(LogKind.RESULT, "DPS '%s' created", dps_name)

                dps_show = self.cmd(f"iot dps show --name {dps_name} -g {rg}").get_output_in_json()
                dps_id = dps_show["id"]
                _log(LogKind.RESULT, "dps_id=%s", dps_id)
                namespace = self.cmd(
                    f"iot adr ns show -n {namespace_name} -g {rg}"
                ).get_output_in_json()
                self_role = (
                    namespace["identity"]["principalId"], "Azure Device Registry Administrator", namespace["id"],
                )
                _assert_service_roles(self, [self_role], present=False)

                add_cmd = (
                    f"iot adr ns link dps add --ns {namespace_name} -g {rg} "
                    f"-n {dps_endpoint} --dps-id {dps_id} "
                    f"--user-assigned-mi {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                link_dps_with_readiness(
                    self, add_cmd, namespace_name, rg, dps_endpoint,
                    {
                        "resourceId": dps_id,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned", "userAssignedIdentity": identity_resource_id,
                        },
                    },
                )
                self.cmd(
                    f"iot adr ns link dps wait -n {dps_endpoint} "
                    f"--ns {namespace_name} -g {rg}"
                )
                _assert_service_roles(self, [self_role], present=True)
                _log(LogKind.OK, "DPS link '%s' created", dps_endpoint)

            with timed_step("Step 1b ❯ DPS link blocks namespace SAMI removal"):
                _assert_dps_blocks_namespace_sami_removal(self, namespace_name, rg)
                _log(LogKind.OK, "DPS link preserved namespace system-assigned identity")

            with timed_step("Step 2 ❯ link dps show / list"):
                shown = self.cmd(
                    f"iot adr ns link dps show --ns {namespace_name} -g {rg} -n {dps_endpoint}"
                ).get_output_in_json()
                assert shown.get("name") == dps_endpoint, (
                    f"link dps show did not surface name field: {shown}"
                )

                assert isinstance(shown.get("brownfieldHubs"), list), shown

                listed = self.cmd(
                    f"iot adr ns link dps list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert len(listed or []) == 1, f"Expected exactly one DPS link, got {listed}"
                duplicate = (
                    f"iot adr ns link dps add --ns {namespace_name} -g {rg} "
                    f"-n dps-cap-rejected --dps-id {dps_id} "
                    f"--user-assigned-mi {identity_resource_id}"
                )
                _assert_cli_failure(self, duplicate, DPS_CAP_EXCEEDED_MSG)
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot dps identity remove -n {dps_name} -g {rg} "
                        f"--user {identity_resource_id}"
                    )
                _log(LogKind.OK, "DPS list returned 1 entry")

            # Step 3: link hub (UAMI) — should now succeed since a DPS is linked.
            with timed_step("Step 3 ❯ link hub add - secondary, UAMI (DPS-first satisfied)"):
                hub_cmd = (
                    f"iot hub create -n {secondary_hub} -g {rg} --sku S1 --location {HUB_TEST_LOCATION} "
                    f"--system-assigned-mi --user-assigned-mi {identity_resource_id} "
                    "--disable-local-auth true"
                )
                _log(LogKind.CMD, "az %s", hub_cmd)
                hub = self.create_owned_resource(
                    hub_cmd, kind="hub", name=secondary_hub, resource_group=rg,
                ).get_output_in_json()
                hub_id = hub["id"]
                hub_identity_types = {
                    identity_type.strip()
                    for identity_type in (hub.get("identity", {}).get("type") or "").split(",")
                    if identity_type.strip()
                }
                assert {"SystemAssigned", "UserAssigned"}.issubset(
                    hub_identity_types
                ), f"Secondary Hub must have both identities, got: {hub.get('identity')}"
                _log(
                    LogKind.RESULT,
                    "Secondary Hub '%s' created with SAMI+UAMI (id=%s)",
                    secondary_hub,
                    hub_id,
                )

                add_cmd = (
                    f"iot adr ns link hub add --ns {namespace_name} -g {rg} "
                    f"-n {secondary_endpoint} --hub-id {hub_id} "
                    f"--user-assigned-mi {identity_resource_id} "
                    f"--availability Available --weight 1"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                link_hub_with_readiness(
                    self, add_cmd, namespace_name, rg, secondary_endpoint,
                    {
                        "resourceId": hub_id,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned", "userAssignedIdentity": identity_resource_id,
                        },
                        "provisioning": {"availability": "Available", "allocationWeight": 1},
                    },
                )
                self.cmd(
                    f"iot adr ns link hub wait -n {secondary_endpoint} "
                    f"--ns {namespace_name} -g {rg}"
                )
                _log(LogKind.OK, "Hub link '%s' created (UAMI)", secondary_endpoint)

            with timed_step("Step 4 ❯ link hub show / list (single entry)"):
                shown = self.cmd(
                    f"iot adr ns link hub show --ns {namespace_name} -g {rg} -n {secondary_endpoint}"
                ).get_output_in_json()
                assert shown.get("name") == secondary_endpoint, (
                    f"link hub show did not surface name field: {shown}"
                )
                assert shown["resourceId"].casefold() == hub_id.casefold(), (
                    "Namespace Hub resource ID does not match the linked Hub."
                )
                assert shown["linkingState"] == "Succeeded", "Namespace Hub linkingState must be Succeeded."
                assert shown["inboundCallerIdentity"]["type"] == "UserAssigned", (
                    "Namespace Hub inbound identity type must be UserAssigned."
                )
                assert (
                    shown["inboundCallerIdentity"]["userAssignedIdentity"].casefold()
                    == identity_resource_id.casefold()
                ), "Namespace Hub selected UAMI does not match the requested identity."

                listed = self.cmd(
                    f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                names = _names_in(listed)
                assert secondary_endpoint in names, (
                    f"Hub link '{secondary_endpoint}' missing from list: {names}"
                )
                hub_before = self.cmd(
                    f"iot hub show -n {secondary_hub} -g {rg}"
                ).get_output_in_json()
                registry_before = (hub_before.get("properties") or {}).get(
                    "deviceRegistry"
                )
                assert registry_before, (
                    "The linked Hub must expose its read-only deviceRegistry projection."
                )
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot hub identity remove -n {secondary_hub} -g {rg} "
                        f"--user {identity_resource_id}"
                    )
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot hub update -n {secondary_hub} -g {rg} "
                        "--remove identity.userAssignedIdentities"
                    )
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot hub create -n {secondary_hub} -g {rg} "
                        "--user-assigned-mi --disable-local-auth true"
                    )
                self.cmd(
                    f"iot hub update -n {secondary_hub} -g {rg} "
                    "--tags adrStatePreservation=true"
                )
                route_name = "adr-state-preservation"
                self.cmd(
                    f"iot hub message-route create -n {secondary_hub} "
                    f"-g {rg} --route-name {route_name} "
                    "--endpoint-name events --source DeviceMessages"
                )
                self.cmd(
                    f"iot hub message-route fallback set "
                    f"-n {secondary_hub} -g {rg} --enabled false"
                )
                self.cmd(
                    f"iot hub message-route fallback set "
                    f"-n {secondary_hub} -g {rg} --enabled true"
                )
                self.cmd(
                    f"iot hub message-route delete -n {secondary_hub} "
                    f"-g {rg} --route-name {route_name} --yes"
                )
                hub_after = self.cmd(
                    f"iot hub show -n {secondary_hub} -g {rg}"
                ).get_output_in_json()
                registry_after = (hub_after.get("properties") or {}).get(
                    "deviceRegistry"
                )
                assert registry_after == registry_before, (
                    "Ordinary Hub or route mutation changed the read-only ADR "
                    "projection."
                )
                _log(LogKind.OK, "Hub list returned %d entry/entries", len(names))

            with timed_step("Verify read-only DPS projection after namespace Hub linking"):
                # brownfieldHubs projects existing DPS registrations, not the
                # namespace messaging endpoints. Never seed this read-only list.
                shown = self.cmd(
                    f"iot adr ns link dps show --ns {namespace_name} -g {rg} -n {dps_endpoint}"
                ).get_output_in_json()
                dps_url = f"{TEST_ARM_ENDPOINT}{dps_id}?api-version={_ADR_DPS_API_VERSION}"
                dps = self.cmd(
                    f"rest --method get --url {shlex.quote(dps_url)} --resource {shlex.quote(TEST_ARM_RESOURCE)}"
                ).get_output_in_json()
                assert isinstance(shown["brownfieldHubs"], list)
                # Compare all fields without including registration credentials
                # in assertion failure output.
                matches_dps = shown["brownfieldHubs"] == ((dps.get("properties") or {}).get("iotHubs") or [])
                assert matches_dps, "brownfieldHubs must match the DPS resource's existing registrations."
                self.cmd(
                    f"iot adr ns link dps update --ns {namespace_name} -g {rg} "
                    f"-n {dps_endpoint} --user-assigned-mi {identity_resource_id}"
                )
                recovered = _wait_for_linking_succeeded(
                    self, "dps", namespace_name, rg, dps_endpoint,
                    expected_identity_type="UserAssigned",
                )
                assert recovered["resourceId"].casefold() == dps_id.casefold()
                assert (
                    recovered["inboundCallerIdentity"]["userAssignedIdentity"].casefold()
                    == identity_resource_id.casefold()
                )

            # Step 5: link hub (SAMI). Provision both identities so subsequent
            # SAMI/UAMI rotations always reference identities on the Hub.
            with timed_step("Step 5 ❯ link hub add - tertiary, SAMI"):
                hub_cmd = (
                    f"iot hub create -n {tertiary_hub} -g {rg} --sku S1 --location {HUB_TEST_LOCATION} "
                    f"--system-assigned-mi --user-assigned-mi {identity_resource_id} "
                    "--disable-local-auth true"
                )
                _log(LogKind.CMD, "az %s", hub_cmd)
                hub = self.create_owned_resource(
                    hub_cmd, kind="hub", name=tertiary_hub, resource_group=rg,
                ).get_output_in_json()
                tertiary_hub_id = hub["id"]
                _log(LogKind.RESULT, "Tertiary Hub '%s' created (SAMI)", tertiary_hub)

                add_cmd = (
                    f"iot adr ns link hub add --ns {namespace_name} -g {rg} "
                    f"-n {tertiary_endpoint} --hub-id {tertiary_hub_id} "
                    f"--system-assigned-mi "
                    f"--availability Available --weight 2"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                link_hub_with_readiness(
                    self, add_cmd, namespace_name, rg, tertiary_endpoint,
                    {
                        "resourceId": tertiary_hub_id,
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                        "provisioning": {"availability": "Available", "allocationWeight": 2},
                    },
                )
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot hub update -n {tertiary_hub} -g {rg} "
                        "--set identity.type=UserAssigned"
                    )
                with pytest.raises(
                    ArgumentUsageError, match="active ADR link"
                ):
                    self.cmd(
                        f"iot hub create -n {tertiary_hub} -g {rg} "
                        "--system-assigned-mi false --disable-local-auth true"
                    )
                _log(LogKind.OK, "Hub link '%s' created (SAMI)", tertiary_endpoint)

            with timed_step("Step 6 ❯ link hub list (multi-hub, both endpoints)"):
                listed = self.cmd(
                    f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                names = _names_in(listed)
                assert {secondary_endpoint, tertiary_endpoint}.issubset(names), (
                    f"Expected both hub links present, got: {names}"
                )
                _log(LogKind.OK, "Hub list returned %d entries (both endpoints present)", len(names))

            with timed_step("Step 7 ❯ link hub update (rotate secondary identity)"):
                update_cmd = (
                    f"iot adr ns link hub update --ns {namespace_name} -g {rg} "
                    f"-n {secondary_endpoint} --system-assigned-mi"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                updated = _update_hub_to_sami_with_recovery(
                    self,
                    update_cmd,
                    namespace_name,
                    rg,
                    secondary_endpoint,
                    hub_id,
                    identity_resource_id,
                )
                identity = (
                    updated.get("properties", updated).get("inboundCallerIdentity")
                    or updated.get("inboundCallerIdentity")
                    or {}
                )
                assert identity.get("type") == "SystemAssigned"
                _log(LogKind.OK, "Hub link inbound identity rotated")

            # Step 8: rotate the tertiary Hub's inbound identity SAMI → UAMI → SAMI.
            # Exercises the --system-assigned-mi / --user-assigned-mi branches of
            # hub_update.
            with timed_step("Step 8 ❯ link hub update (rotate identity SAMI → UAMI → SAMI)"):
                def _identity_type(endpoint: dict) -> Optional[str]:
                    ici = (endpoint.get("properties", endpoint).get("inboundCallerIdentity")
                           or endpoint.get("inboundCallerIdentity") or {})
                    return ici.get("type")

                # SAMI → UAMI
                update_cmd = (
                    f"iot adr ns link hub update --ns {namespace_name} -g {rg} "
                    f"-n {tertiary_endpoint} --user-assigned-mi {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                self.cmd(update_cmd)
                shown = _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    tertiary_endpoint,
                    expected_identity_type="UserAssigned",
                )
                assert _identity_type(shown) == "UserAssigned", (
                    f"Expected UserAssigned after rotation, saw: {_identity_type(shown)}"
                )
                _log(LogKind.OK, "Rotated SAMI → UAMI")

                # UAMI → SAMI
                update_cmd = (
                    f"iot adr ns link hub update --ns {namespace_name} -g {rg} "
                    f"-n {tertiary_endpoint} --system-assigned-mi"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                self.cmd(update_cmd)
                shown = _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    tertiary_endpoint,
                    expected_identity_type="SystemAssigned",
                )
                assert _identity_type(shown) == "SystemAssigned", (
                    f"Expected SystemAssigned after rotation, saw: {_identity_type(shown)}"
                )
                _log(LogKind.OK, "Rotated UAMI → SAMI")

            with timed_step("Step 9 ❯ link dps update (rotate identity)"):
                update_cmd = (
                    f"iot adr ns link dps update --ns {namespace_name} -g {rg} "
                    f"-n {dps_endpoint} --user-assigned-mi {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                self.cmd(update_cmd)
                _wait_for_linking_succeeded(
                    self,
                    "dps",
                    namespace_name,
                    rg,
                    dps_endpoint,
                    expected_identity_type="UserAssigned",
                )
                _log(LogKind.OK, "DPS link identity rotated (idempotent)")

            _log(LogKind.OK, "Link lifecycle passed")

        finally:
            self.cleanup_full_infra()


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkSequentialAdd(ADRFullInfraHelper, ADRLiveScenarioTest):
    """The combined command links DPS successfully before submitting the Hub link.

    Provision fresh targets without service-role grants, leaving the namespace
    empty. One native combined invocation owns RBAC, propagation recovery and
    DPS-first sequencing. No fixture repair or preauthorization delay is allowed.
    """

    @pytest.mark.timeout(900 + _NATIVE_LINK_TIMEOUT, func_only=False)
    def test_adr_link_sequential_add(self):
        _log(LogKind.TEST, "test_adr_link_sequential_add")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        dps_name = generate_dps_name()
        identity_name = generate_identity_name()

        try:
            # Start with no endpoints so the combined command owns both link writes.
            with timed_step("Setup 1/5 > Create UAMI"):
                identity = self.create_owned_resource(
                    f"identity create -n {identity_name} -g {rg} --location {TEST_LOCATION}",
                    kind="identity", name=identity_name, resource_group=rg,
                ).get_output_in_json()
                identity_resource_id = identity["id"]

            with timed_step("Setup 2/5 > Create ADR namespace (no links)"):
                namespace = self.create_owned_resource(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}",
                    kind="namespace", name=namespace_name, resource_group=rg,
                ).get_output_in_json()
                assert namespace["properties"]["provisioningState"] == "Succeeded", namespace

            with timed_step("Setup 3/5 > Start standalone Standard Hub asynchronously"):
                self.create_owned_resource(
                    f"iot hub create -n {hub_name} -g {rg} --sku S1 --location {HUB_TEST_LOCATION} "
                    f"--user-assigned-mi {identity_resource_id} --disable-local-auth true --no-wait",
                    kind="hub", name=hub_name, resource_group=rg,
                )
                hub = wait_for_condition(
                    lambda: self.cmd(f"iot hub show -n {hub_name} -g {rg}").get_output_in_json(),
                    lambda resource: bool(resource.get("id")),
                    description="owned Hub materialization",
                    timeout=120,
                )
                hub_id = hub["id"]

            with timed_step("Setup 4/5 > Create standalone DPS while Hub provisions"):
                dps = self.create_owned_resource(
                    f"iot dps create --name {dps_name} -g {rg} --location {TEST_LOCATION} --disable-local-auth true "
                    f"--user-assigned-mi {identity_resource_id}",
                    kind="dps", name=dps_name, resource_group=rg,
                ).get_output_in_json()
                dps_id = dps["id"]
                assert dps["properties"]["provisioningState"] == "Succeeded", dps

            with timed_step("Setup 5/5 > Bounded Hub readiness without service-role preparation"):
                wait_for_condition(
                    lambda: self.cmd(f"iot hub show -n {hub_name} -g {rg}").get_output_in_json(),
                    lambda resource: resource["properties"]["state"] == "Active",
                    is_terminal_failure=lambda resource: any(
                        resource["properties"].get(field) in {"Failed", "Canceled", "Cancelled"}
                        for field in ("state", "provisioningState")
                    ),
                    description="owned Hub Active",
                    timeout=600,
                    interval=30,
                    describe=lambda resource: f"Hub state={resource['properties'].get('state')}",
                )
                namespace = self.cmd(
                    f"iot adr ns show -n {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert namespace["properties"]["provisioningState"] == "Succeeded", namespace
                for section in ("messaging", "provisioning"):
                    assert not (namespace["properties"].get(section) or {}).get("endpoints"), namespace
                namespace_principal = resolve_namespace_outbound_principal(namespace)
                roles = (
                    (namespace_principal, "Contributor", dps_id),
                    (identity["principalId"], "Contributor", namespace["id"]),
                    (namespace["identity"]["principalId"], "Azure Device Registry Administrator", namespace["id"]),
                    (namespace_principal, "Contributor", hub_id),
                    (namespace_principal, "IoT Hub Data Contributor", hub_id),
                )
                _assert_service_roles(self, roles, present=False)
                _log(LogKind.OK, "Fresh targets ready; no endpoints or required service-role assignments exist")

            with timed_step("Step 1 ❯ Combined link add: DPS Succeeded before Hub submission"):
                result = self.cmd(
                    f"iot adr ns link add --ns {namespace_name} -g {rg} "
                    f"--dps-endpoint-name dps-primary --dps-id {dps_id} "
                    f"--dps-user-assigned-mi {identity_resource_id} "
                    f"--hub-endpoint-name primary --hub-id {hub_id} "
                    f"--hub-user-assigned-mi {identity_resource_id} --hub-availability Available --hub-weight 1 "
                    f"{_NATIVE_LINK_OPTIONS}"
                ).get_output_in_json()
                for section, name, resource_id in (
                    ("provisioning", "dps-primary", dps_id), ("messaging", "primary", hub_id),
                ):
                    _assert_native_link_result(
                        result, section, name, resource_id,
                        {"type": "UserAssigned", "userAssignedIdentity": identity_resource_id},
                    )
                _assert_service_roles(self, roles, present=True)
                _log(LogKind.OK, "Combined DPS-first link add returned the final Succeeded namespace")

            with timed_step("Step 2 ❯ Verify both exact endpoints remain Succeeded"):
                hubs = self.cmd(
                    f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                dpss = self.cmd(
                    f"iot adr ns link dps list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert len(hubs) == 1, f"Expected 1 hub link, got {hubs}"
                assert len(dpss) == 1, f"Expected 1 DPS link, got {dpss}"
                for endpoint, name, resource_id in (
                    (dpss[0], "dps-primary", dps_id), (hubs[0], "primary", hub_id),
                ):
                    assert endpoint["name"] == name, endpoint
                    assert endpoint["resourceId"].casefold() == resource_id.casefold(), endpoint
                    assert endpoint["linkingState"] == "Succeeded", endpoint
                    identity = endpoint["inboundCallerIdentity"]
                    assert identity["type"] == "UserAssigned", endpoint
                    assert identity["userAssignedIdentity"].casefold() == identity_resource_id.casefold(), endpoint
                assert hubs[0]["provisioning"] == {"availability": "Available", "allocationWeight": 1}, hubs
                _log(LogKind.OK, "Sequential DPS-first adds produced both exact endpoints in Succeeded")

        finally:
            self.cleanup_full_infra()


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkValidationNegatives(ADRLiveScenarioTest):
    """Client-side validation negatives for the ``iot adr ns link`` surface.

    These scenarios assert the provider's argument validation that runs *before*
    any service round trip (resource-ID parsing and the SAMI/UAMI mutually-exclusive
    guard). Because they fail client-side, they need neither real link
    infrastructure nor backend readiness — every command is expected to fail.

    This complements the lifecycle suites (which prove the happy paths) by
    exercising the rejection branches end-to-end through the CLI, not just at the
    provider unit level.
    """

    def test_adr_link_validation_negatives(self):
        _log(LogKind.TEST, "test_adr_link_validation_negatives")
        rg = TEST_RG
        # A namespace that need not exist: every command below fails during
        # argument validation, before the provider issues a namespace GET.
        ns = "validation-ns-does-not-matter"
        hub_id = (
            "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
            f"{rg}/providers/Microsoft.Devices/IotHubs/somehub"
        )
        uami_id = (
            "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
            f"{rg}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
        )

        # --- DPS resource-id parsing rejections (dps add) ---
        with timed_step("DPS add ❯ empty --dps-id rejected"):
            self.cmd(
                f'iot adr ns link dps add -n primary --ns {ns} -g {rg} --dps-id "" --mi-sa',
                expect_failure=True,
            )
        with timed_step("DPS add ❯ bare DPS name rejected"):
            self.cmd(
                f"iot adr ns link dps add -n primary --ns {ns} -g {rg} --dps-id mydps --mi-sa",
                expect_failure=True,
            )
        with timed_step("DPS add ❯ wrong resource type rejected"):
            self.cmd(
                f"iot adr ns link dps add -n primary --ns {ns} -g {rg} --dps-id {hub_id} --mi-sa",
                expect_failure=True,
            )

        # --- SAMI/UAMI mutually-exclusive guard (update paths reject first) ---
        with timed_step("Hub update ❯ SAMI + UAMI together rejected"):
            self.cmd(
                f"iot adr ns link hub update -n primary --ns {ns} -g {rg} "
                f"--mi-sa --mi-ua {uami_id}",
                expect_failure=True,
            )
        with timed_step("DPS update ❯ SAMI + UAMI together rejected"):
            self.cmd(
                f"iot adr ns link dps update -n primary --ns {ns} -g {rg} "
                f"--mi-sa --mi-ua {uami_id}",
                expect_failure=True,
            )

        _log(LogKind.OK, "All link validation negatives rejected client-side as designed")
