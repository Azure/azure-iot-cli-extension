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
* ``link add`` bundled Hub+DPS PATCH in a single round trip
* ``link su add / update / show / list`` — Software Updates updating
  endpoints with UAMI/SAMI identity rotation. Set
  ``azext_iot_adr_update_instance_id`` to a pre-provisioned Update Instance
  resource ID to enable this test.

These tests require real Hub and DPS resources to be linked to a real ADR
namespace, so they re-use :class:`ADRFullInfraHelper` to provision the full
infrastructure once per test class and exercise the link CLI surface against
it. The Hub created by ``setup_full_infra`` already links itself to the ADR
namespace via the ``--ns-resource-id`` / ``--ns-identity-id`` flags during
``iot hub create``; we do **not** drive ``ns create`` to attach the Hub.

What is intentionally NOT covered here (covered by unit tests):
- DPS-first ordering reject (``test_hub_add_rejects_when_no_dps_linked``)
- One-DPS-per-namespace cap rejection
- MI mutually-exclusive rejection
- Invalid DPS resource id rejection
"""

import os
import re
import sys
import time
from typing import Optional

import pytest
from azure.cli.core.azclierror import ArgumentUsageError
from msrestazure.tools import parse_resource_id

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    wait_for_condition,
)
from azext_iot.tests.adr._log import LogKind, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_RG,
    generate_adr_namespace_name,
    generate_dps_name,
    generate_hub_name,
    generate_identity_name,
)
from azext_iot.adr.topology import DPS_REQUIRED_MSG, SU_CAP_EXCEEDED_MSG


_SU_UPDATE_INSTANCE_ENV = "azext_iot_adr_update_instance_id"
_SU_UPDATE_INSTANCE_ID = os.getenv(_SU_UPDATE_INSTANCE_ENV, "").strip()
_SU_UPDATE_INSTANCE_DISPOSABLE = os.getenv(
    "azext_iot_adr_update_instance_disposable", ""
).lower() in {"1", "true", "yes"}
_LINKING_POLL_ATTEMPTS = int(
    os.getenv("azext_iot_adr_su_link_poll_attempts", "240")
)
_LINKING_POLL_INTERVAL_SECONDS = 10
_ADU_FPA_OBJECT_ID = os.getenv(
    "azext_iot_adr_adu_fpa_object_id",
    "e6c17e40-1542-4a44-9e8e-971232625ea8",
).strip()


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
    def fetch():
        return test_case.cmd(
            f"iot adr ns link {link_kind} show --ns {namespace_name} "
            f"-g {resource_group_name} -n {endpoint_name}"
        ).get_output_in_json()

    def observation(shown):
        properties = shown.get("properties") or shown
        linking_state = properties.get("linkingState") or shown.get(
            "linkingState"
        )
        identity = (
            properties.get("inboundCallerIdentity")
            or shown.get("inboundCallerIdentity")
            or {}
        )
        return linking_state, identity.get("type")

    def succeeded(shown):
        linking_state, identity_type = observation(shown)
        return linking_state == "Succeeded" and (
            expected_identity_type is None
            or identity_type == expected_identity_type
        )

    return wait_for_condition(
        fetch,
        succeeded,
        description=f"{link_kind} endpoint '{endpoint_name}' linking",
        is_terminal_failure=lambda shown: observation(shown)[0] == "Failed",
        timeout=None,
        interval=_LINKING_POLL_INTERVAL_SECONDS,
        max_attempts=_LINKING_POLL_ATTEMPTS,
        describe=lambda shown: (
            f"linkingState={observation(shown)[0]!r}, "
            f"identityType={observation(shown)[1]!r}"
        ),
    )


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkLifecycle(ADRFullInfraHelper, CaptureOutputLiveScenarioTest):
    """End-to-end lifecycle of namespace-side Hub and DPS link entries.

    The flow follows the design's enforced DPS-first ordering and exercises
    both inbound caller identity variants (UAMI and SAMI):

    1. Setup: provision ADR + UAMI + primary Hub (Hub auto-links to ADR via ``iot hub create``)
    2. Step 1: create a standalone DPS, pre-register the primary Hub on it via
       ``iot dps linked-hub create`` (seeds the brownfield list), then
       ``link dps add`` to attach the DPS to the namespace
    3. Step 2: ``link dps show`` asserts ``brownfieldHubs`` enumerates the Hub
    4. Step 3-4: secondary Hub linked with **UAMI** + show/list (single entry)
    5. Step 5-6: tertiary Hub linked with **SAMI** + multi-hub list assertion
    6. Step 7-8: ``link hub update`` rotates inbound identities
    7. Step 9: ``link dps update`` rotates DPS identity
    8. Step 10: ``link dps delete`` permanently deletes the disposable DPS
       while Hub links remain, then removes only the DPS endpoint
    9. Step 11: ``link hub delete`` permanently deletes both disposable Hubs
       and removes their namespace endpoints
    """

    def test_adr_link_lifecycle(self):
        _log(LogKind.TEST, "test_adr_link_lifecycle")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        primary_hub = generate_hub_name()  # auto-linked at hub-create time
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
            )
            identity_resource_id = infra["identity_resource_id"]

            # The Hub created by setup_full_infra is linked via `iot hub create
            # --ns-resource-id` which writes a hub-side reference. The namespace's
            # `properties.messaging.endpoints` collection is what `iot adr ns link
            # hub *` manipulates and is intended to grow via the link surface, so
            # we don't make any assumptions about the auto-linked endpoint name —
            # the link tests add their own endpoints explicitly.

            # Step 1: link DPS — DPS-first ordering means this must succeed
            # before any `link hub add`. We also pre-register the primary Hub on
            # the DPS via `iot dps linked-hub create` so the `dps show` brownfield
            # enumeration in Step 2 has a real entry to surface.
            with timed_step("Step 1 ❯ link dps add (+ seed DPS-side Hub registration)"):
                cmd = (
                    f"iot dps create --name {dps_name} -g {rg} "
                    f"--location {infra['adr_resource_id'].split('/')[-3]} "
                    f"--mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", cmd)
                self.cmd(cmd)
                _log(LogKind.RESULT, "DPS '%s' created", dps_name)

                dps_show = self.cmd(f"iot dps show --name {dps_name} -g {rg}").get_output_in_json()
                dps_id = dps_show["id"]
                _log(LogKind.RESULT, "dps_id=%s", dps_id)

                # Register the primary Hub on the DPS so `iot adr ns link dps show`
                # has a non-empty `brownfieldHubs` list to surface.
                linked_hub_cmd = (
                    f"iot dps linked-hub create --dps-name {dps_name} -g {rg} "
                    f"--hub-name {primary_hub}"
                )
                _log(LogKind.CMD, "az %s", linked_hub_cmd)
                try:
                    self.cmd(linked_hub_cmd)
                    _log(LogKind.RESULT, "Primary Hub registered on DPS (seeds brownfield list)")
                except Exception as e:  # noqa: BLE001 — best-effort seed
                    _log(LogKind.WARN, "DPS linked-hub create failed (brownfield assertion may skip): %s", e)

                add_cmd = (
                    f"iot adr ns link dps add --ns {namespace_name} -g {rg} "
                    f"-n {dps_endpoint} --dps-id {dps_id} "
                    f"--mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                self.cmd(add_cmd)
                _wait_for_linking_succeeded(
                    self,
                    "dps",
                    namespace_name,
                    rg,
                    dps_endpoint,
                    expected_identity_type="UserAssigned",
                )
                self.cmd(
                    f"iot adr ns link dps wait --ns {namespace_name} "
                    f"-g {rg} --updated"
                )
                _log(LogKind.OK, "DPS link '%s' created", dps_endpoint)

            with timed_step("Step 2 ❯ link dps show (+ brownfield Hubs) / list"):
                shown = self.cmd(
                    f"iot adr ns link dps show --ns {namespace_name} -g {rg} -n {dps_endpoint}"
                ).get_output_in_json()
                assert shown.get("name") == dps_endpoint, (
                    f"link dps show did not surface name field: {shown}"
                )

                # Strengthened: assert brownfieldHubs is enumerated. The Hub was
                # registered via `iot dps linked-hub create` in Step 1, so the
                # side-GET against the DPS RP must surface it.
                brownfield = shown.get("brownfieldHubs")
                assert brownfield is not None, (
                    f"link dps show must always set 'brownfieldHubs' key (may be empty list); got: {shown}"
                )
                brownfield_names = {
                    ((h.get("name") if isinstance(h, dict) else h) or "").lower()
                    for h in (brownfield or [])
                }
                # Each entry is the iotHubs[] record from the DPS — its `name` field
                # is typically the hub hostname (e.g. `myhub.azure-devices.net`) or
                # the bare hub name depending on backend serialization. Accept either.
                primary_lower = primary_hub.lower()
                assert any(primary_lower in n for n in brownfield_names) or any(
                    primary_lower == n.split(".")[0] for n in brownfield_names
                ), (
                    f"Expected primary Hub '{primary_hub}' in brownfieldHubs, "
                    f"got: {brownfield_names}"
                )
                _log(
                    LogKind.OK,
                    "DPS link visible; brownfieldHubs contains primary Hub (%d entry/entries)",
                    len(brownfield_names),
                )

                listed = self.cmd(
                    f"iot adr ns link dps list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert len(listed or []) == 1, f"Expected exactly one DPS link, got {listed}"
                _log(LogKind.OK, "DPS list returned 1 entry")

            # Step 3: link hub (UAMI) — should now succeed since a DPS is linked.
            with timed_step("Step 3 ❯ link hub add - secondary, UAMI (DPS-first satisfied)"):
                hub_cmd = (
                    f"iot hub create -n {secondary_hub} -g {rg} --sku GEN2 "
                    f"--mi-system-assigned --mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", hub_cmd)
                hub = self.cmd(hub_cmd).get_output_in_json()
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
                    f"--mi-user-assigned {identity_resource_id} "
                    f"--availability Available --weight 1"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                self.cmd(add_cmd)
                _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    secondary_endpoint,
                    expected_identity_type="UserAssigned",
                )
                self.cmd(
                    f"iot adr ns link hub wait --ns {namespace_name} "
                    f"-g {rg} --updated"
                )
                _log(LogKind.OK, "Hub link '%s' created (UAMI)", secondary_endpoint)

            with timed_step("Step 4 ❯ link hub show / list (single entry)"):
                shown = self.cmd(
                    f"iot adr ns link hub show --ns {namespace_name} -g {rg} -n {secondary_endpoint}"
                ).get_output_in_json()
                assert shown.get("name") == secondary_endpoint, (
                    f"link hub show did not surface name field: {shown}"
                )

                listed = self.cmd(
                    f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                names = _names_in(listed)
                assert secondary_endpoint in names, (
                    f"Hub link '{secondary_endpoint}' missing from list: {names}"
                )
                _log(LogKind.OK, "Hub list returned %d entry/entries", len(names))

            # Step 5: link hub (SAMI). Provision both identities so subsequent
            # SAMI/UAMI rotations always reference identities on the Hub.
            with timed_step("Step 5 ❯ link hub add - tertiary, SAMI"):
                hub_cmd = (
                    f"iot hub create -n {tertiary_hub} -g {rg} --sku GEN2 "
                    f"--mi-system-assigned --mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", hub_cmd)
                hub = self.cmd(hub_cmd).get_output_in_json()
                tertiary_hub_id = hub["id"]
                _log(LogKind.RESULT, "Tertiary Hub '%s' created (SAMI)", tertiary_hub)

                add_cmd = (
                    f"iot adr ns link hub add --ns {namespace_name} -g {rg} "
                    f"-n {tertiary_endpoint} --hub-id {tertiary_hub_id} "
                    f"--mi-system-assigned "
                    f"--availability Available --weight 2"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                self.cmd(add_cmd)
                _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    tertiary_endpoint,
                    expected_identity_type="SystemAssigned",
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
                    f"-n {secondary_endpoint} --mi-system-assigned"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                self.cmd(update_cmd)
                updated = _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    secondary_endpoint,
                    expected_identity_type="SystemAssigned",
                )
                identity = (
                    updated.get("properties", updated).get("inboundCallerIdentity")
                    or updated.get("inboundCallerIdentity")
                    or {}
                )
                assert identity.get("type") == "SystemAssigned"
                _log(LogKind.OK, "Hub link inbound identity rotated")

            # Step 8: rotate the tertiary Hub's inbound identity SAMI → UAMI → SAMI.
            # Exercises the --mi-system-assigned / --mi-user-assigned branches of
            # hub_update.
            with timed_step("Step 8 ❯ link hub update (rotate identity SAMI → UAMI → SAMI)"):
                def _identity_type(endpoint: dict) -> Optional[str]:
                    ici = (endpoint.get("properties", endpoint).get("inboundCallerIdentity")
                           or endpoint.get("inboundCallerIdentity") or {})
                    return ici.get("type")

                # SAMI → UAMI
                update_cmd = (
                    f"iot adr ns link hub update --ns {namespace_name} -g {rg} "
                    f"-n {tertiary_endpoint} --mi-user-assigned {identity_resource_id}"
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
                    f"-n {tertiary_endpoint} --mi-system-assigned"
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
                    f"-n {dps_endpoint} --mi-user-assigned {identity_resource_id}"
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

            with timed_step(
                "Step 10 ❯ link dps delete while Hub links remain"
            ):
                self.cmd(
                    f"iot adr ns link dps delete --ns {namespace_name} "
                    f"-g {rg} -n {dps_endpoint} --yes"
                )
                self.cmd(
                    f"iot dps show --name {dps_name} -g {rg}",
                    expect_failure=True,
                )
                assert self.cmd(
                    f"iot adr ns link dps list --ns {namespace_name} -g {rg}"
                ).get_output_in_json() == []
                remaining_hubs = _names_in(
                    self.cmd(
                        f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                    ).get_output_in_json()
                )
                assert {
                    secondary_endpoint,
                    tertiary_endpoint,
                }.issubset(remaining_hubs)

                succeeded_hub = self.cmd(
                    f"iot adr ns link hub show --ns {namespace_name} "
                    f"-g {rg} -n {secondary_endpoint}"
                ).get_output_in_json()
                assert succeeded_hub.get("name") == secondary_endpoint
                assert succeeded_hub.get("resourceId") == hub_id

                for command in (
                    (
                        f"iot adr ns link hub add --ns {namespace_name} -g {rg} "
                        f"-n rejected-after-dps-delete --hub-id {hub_id}"
                    ),
                    (
                        f"iot adr ns update --namespace {namespace_name} -g {rg} "
                        "--messaging-endpoints "
                        f"'{{\"rejected-raw\":{{\"endpointType\":"
                        "\"Microsoft.Devices/IotHubs\","
                        f"\"resourceId\":\"{hub_id}\"}}}}'"
                    ),
                ):
                    _assert_cli_failure(self, command, DPS_REQUIRED_MSG)
                _log(
                    LogKind.OK,
                    "DPS deleted; successful Hubs remain readable while new "
                    "atomic and raw Hub additions are rejected",
                )

            with timed_step(
                "Step 11 ❯ link hub delete (disposable linked resources)"
            ):
                for endpoint, hub_name in (
                    (secondary_endpoint, secondary_hub),
                    (tertiary_endpoint, tertiary_hub),
                ):
                    self.cmd(
                        f"iot adr ns link hub delete --ns {namespace_name} "
                        f"-g {rg} -n {endpoint} --yes"
                    )
                    self.cmd(
                        f"iot hub show -n {hub_name} -g {rg}",
                        expect_failure=True,
                    )
                remaining_hubs = _names_in(
                    self.cmd(
                        f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                    ).get_output_in_json()
                )
                assert secondary_endpoint not in remaining_hubs
                assert tertiary_endpoint not in remaining_hubs
                _log(
                    LogKind.OK,
                    "Both linked Hub resources and selected endpoints deleted",
                )

            _log(LogKind.OK, "Link lifecycle passed")

        finally:
            self.cleanup_full_infra(
                resource_group=rg,
                hub_name=primary_hub,
                namespace_name=namespace_name,
                identity_name=identity_name,
                dps_name=dps_name,
            )
            # Best-effort cleanup of the secondary + tertiary Hubs
            for label, hub in (("secondary", secondary_hub), ("tertiary", tertiary_hub)):
                with timed_step(f"Cleanup ❯ Delete {label} Hub"):
                    try:
                        self.cmd(f"iot hub delete -n {hub} -g {rg}")
                        _log(LogKind.RESULT, "%s Hub deleted", label.capitalize())
                    except Exception as e:
                        _log(LogKind.WARN, "%s Hub cleanup failed: %s", label.capitalize(), e)


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkBundledAdd(ADRFullInfraHelper, CaptureOutputLiveScenarioTest):
    """``iot adr ns link add`` bundled Hub+DPS in one PATCH (P4).

    Tests the single round-trip variant that links both a Hub messaging endpoint
    and a DPS provisioning endpoint at once, with the DPS entry serialized first
    to satisfy the DPS-first ordering constraint server-side.
    """

    def test_adr_link_bundled_add(self):
        _log(LogKind.TEST, "test_adr_link_bundled_add")
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        dps_name = generate_dps_name()
        identity_name = generate_identity_name()

        try:
            # We need a UAMI, namespace, AND a separately created Hub and DPS to
            # link. We deliberately do NOT use setup_full_infra here because we
            # want the namespace to start with zero linked endpoints so we can
            # observe the bundled add adding both at once.
            from azext_iot.tests.adr.conftest import TEST_LOCATION

            with timed_step("Setup 1/4 ❯ Create UAMI"):
                identity = self.cmd(
                    f"identity create -n {identity_name} -g {rg} --location {TEST_LOCATION}"
                ).get_output_in_json()
                identity_resource_id = identity["id"]
                identity_principal_id = identity["principalId"]
                subscription_id = self.cmd("account show").get_output_in_json()["id"]
                self.assign_hub_rp_contributor_role(subscription_id, rg)

            with timed_step("Setup 2/4 ❯ Create ADR namespace (no Hub link)"):
                ns = self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                ).get_output_in_json()
                self.assign_adr_roles_to_identity(identity_principal_id, ns["id"])

            with timed_step("Setup 3/4 ❯ Create standalone Hub Gen2"):
                hub = self.cmd(
                    f"iot hub create -n {hub_name} -g {rg} --sku GEN2 --location {TEST_LOCATION} "
                    f"--mi-user-assigned {identity_resource_id}"
                ).get_output_in_json()
                hub_id = hub["id"]

            with timed_step("Setup 4/4 ❯ Create standalone DPS"):
                dps = self.cmd(
                    f"iot dps create --name {dps_name} -g {rg} --location {TEST_LOCATION} "
                    f"--mi-user-assigned {identity_resource_id}"
                ).get_output_in_json()
                dps_id = dps["id"]

            # Allow role assignments to propagate
            time.sleep(30)

            with timed_step("Step 1 ❯ link add (bundled Hub + DPS in one PATCH)"):
                bundled_cmd = (
                    f"iot adr ns link add --ns {namespace_name} -g {rg} "
                    f"--hub-name primary --hub-id {hub_id} "
                    f"--hub-mi-user-assigned {identity_resource_id} "
                    f"--hub-availability Available --hub-weight 1 "
                    f"--dps-name dps-primary --dps-id {dps_id} "
                    f"--dps-mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", bundled_cmd)
                self.cmd(bundled_cmd)
                self.cmd(
                    f"iot adr ns link wait --ns {namespace_name} "
                    f"-g {rg} --updated"
                )
                _wait_for_linking_succeeded(
                    self,
                    "hub",
                    namespace_name,
                    rg,
                    "primary",
                    expected_identity_type="UserAssigned",
                )
                _wait_for_linking_succeeded(
                    self,
                    "dps",
                    namespace_name,
                    rg,
                    "dps-primary",
                    expected_identity_type="UserAssigned",
                )
                _log(LogKind.OK, "Bundled link add succeeded")

            with timed_step("Step 2 ❯ Verify both endpoints landed"):
                hubs = self.cmd(
                    f"iot adr ns link hub list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                dpss = self.cmd(
                    f"iot adr ns link dps list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert len(hubs) == 1, f"Expected 1 hub link, got {hubs}"
                assert len(dpss) == 1, f"Expected 1 DPS link, got {dpss}"
                _log(LogKind.OK, "Bundled add produced both endpoints")

        finally:
            self.cleanup_full_infra(
                resource_group=rg,
                hub_name=hub_name,
                namespace_name=namespace_name,
                identity_name=identity_name,
                dps_name=dps_name,
            )


@pytest.mark.skipif(
    not _SU_UPDATE_INSTANCE_ID or not _SU_UPDATE_INSTANCE_DISPOSABLE,
    reason=(
        "Set azext_iot_adr_update_instance_id to a pre-provisioned disposable "
        "Microsoft.DeviceUpdate/updateInstances resource and set "
        "azext_iot_adr_update_instance_disposable=true. The test permanently "
        "links and then deletes that instance."
    ),
)
@pytest.mark.usefixtures("set_cwd")
class TestADRLinkSU(ADRFullInfraHelper, CaptureOutputLiveScenarioTest):
    """End-to-end lifecycle of namespace-side Software Updates link entries.

    Mirrors the Hub/DPS link lifecycle for the ``iot adr ns link su`` surface:

    1. Use the pre-provisioned ``Microsoft.DeviceUpdate/updateInstances`` resource
       supplied by ``azext_iot_adr_update_instance_id``. It must be disposable
       and have both SAMI and UAMI identities.
    2. Create an ADR namespace and authorize the update instance identities.
    3. Step 1: ``link su add`` (UAMI) attaches the Software Updates updating endpoint.
    4. Step 2: ``link su show`` / ``list`` surface the single entry.
    5. Step 3: data-plane list commands verify the materialized service address.
    6. Step 4: ``link su update`` rotates the inbound caller identity UAMI → SAMI.

    What is intentionally NOT covered here (covered by unit tests):
    - MI mutually-exclusive rejection
    - Invalid / wrong-type Update Instance resource id rejection
    """

    def test_adr_link_su_lifecycle(self):
        _log(LogKind.TEST, "test_adr_link_su_lifecycle")
        from azext_iot.tests.adr.conftest import TEST_LOCATION

        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        denied_namespace_name = generate_adr_namespace_name()
        su_endpoint = "su-primary"
        denied_endpoint = "su-no-role"
        su_deleted = False

        def _names_in(listed):
            assert isinstance(listed, list)
            return {item["name"] for item in listed}

        def _identity_type(endpoint: dict) -> Optional[str]:
            properties = endpoint.get("properties") or endpoint
            return (properties.get("inboundCallerIdentity") or {}).get("type")

        su_id = _SU_UPDATE_INSTANCE_ID
        try:
            with timed_step("Setup 1/3 ❯ Resolve Update Instance SAMI and UAMI"):
                update_instance = self.cmd(
                    f"resource show --ids {su_id}"
                ).get_output_in_json()
                identity = update_instance.get("identity") or {}
                sami_principal_id = identity.get("principalId")
                user_identities = identity.get("userAssignedIdentities") or {}
                if not sami_principal_id or not user_identities:
                    pytest.skip(
                        "The supplied update instance must have both system-assigned "
                        "and user-assigned identities."
                    )
                identity_resource_id = next(iter(user_identities))
                uami = self.cmd(
                    f"identity show --ids {identity_resource_id}"
                ).get_output_in_json()
                identity_principal_id = uami.get("principalId")
                if not identity_principal_id:
                    pytest.skip(
                        "The supplied update instance UAMI has no principalId."
                    )

            with timed_step("Setup 2/3 ❯ Verify link authorization failures"):
                self.cmd(
                    f"iot adr ns create -n {denied_namespace_name} -g {rg} "
                    f"--location {TEST_LOCATION}"
                )
                try:
                    self.cmd(
                        f"iot adr ns link su add "
                        f"--ns {denied_namespace_name} -g {rg} "
                        f"-n su-no-identity --su-id {su_id}",
                        expect_failure=True,
                    )
                    denied_command = (
                        f"iot adr ns link su add "
                        f"--ns {denied_namespace_name} -g {rg} "
                        f"-n {denied_endpoint} --su-id {su_id} "
                        "--mi-system-assigned"
                    )
                    try:
                        self.cmd(denied_command)
                    except Exception as error:  # noqa: BLE001
                        message = str(error).casefold()
                        assert any(
                            token in message
                            for token in (
                                "authorization",
                                "forbidden",
                                "permission",
                                "role",
                                "403",
                            )
                        ), f"Unexpected link authorization error: {error}"
                    else:
                        def denied_state():
                            response = self.cmd(
                                f"iot adr ns link su show "
                                f"--ns {denied_namespace_name} -g {rg} "
                                f"-n {denied_endpoint}"
                            ).get_output_in_json()
                            return response.get("linkingState")

                        wait_for_condition(
                            denied_state,
                            lambda state: state == "Failed",
                            description="unauthorized Software Updates link failure",
                            is_terminal_failure=lambda state: (
                                state == "Succeeded"
                            ),
                            timeout=None,
                            interval=_LINKING_POLL_INTERVAL_SECONDS,
                            max_attempts=_LINKING_POLL_ATTEMPTS,
                            describe=lambda state: f"linkingState={state!r}",
                        )
                finally:
                    self.cmd(
                        f"iot adr ns delete -n {denied_namespace_name} "
                        f"-g {rg} -y"
                    )

            with timed_step("Setup 3/3 ❯ Create authorized ADR namespace"):
                ns = self.cmd(
                    f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
                ).get_output_in_json()
                self.assign_adr_roles_to_identity(identity_principal_id, ns["id"])
                self.assign_adr_roles_to_identity(sami_principal_id, ns["id"])
                namespace_principal_id = (ns.get("identity") or {}).get("principalId")
                assert namespace_principal_id, "Namespace SAMI principalId is required."
                self.assign_role(namespace_principal_id, "Contributor", su_id)
                self.assign_role(_ADU_FPA_OBJECT_ID, "Contributor", su_id)

            # Allow role assignments to propagate
            time.sleep(30)

            with timed_step("Step 1 > link su add (UAMI)"):
                add_cmd = (
                    f"iot adr ns link su add --ns {namespace_name} -g {rg} "
                    f"-n {su_endpoint} --su-id {su_id} "
                    f"--mi-user-assigned {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", add_cmd)
                self.cmd(add_cmd)
                _wait_for_linking_succeeded(
                    self,
                    "su",
                    namespace_name,
                    rg,
                    su_endpoint,
                    expected_identity_type="UserAssigned",
                )
                self.cmd(
                    f"iot adr ns link su wait --ns {namespace_name} "
                    f"-g {rg} --updated"
                )
                self.cmd(add_cmd, expect_failure=True)
                for cap_command in (
                    (
                        f"iot adr ns link su add --ns {namespace_name} -g {rg} "
                        f"-n su-cap-rejected-link --su-id {su_id} "
                        "--mi-system-assigned"
                    ),
                    (
                        f"iot adr ns update --namespace {namespace_name} -g {rg} "
                        "--updating-endpoints "
                        f"'{{\"su-cap-rejected-raw\":{{\"endpointType\":"
                        "\"Microsoft.DeviceUpdate/updateInstances\","
                        f"\"resourceId\":\"{su_id}\"}}}}'"
                    ),
                ):
                    _assert_cli_failure(
                        self, cap_command, SU_CAP_EXCEEDED_MSG
                    )
                assert _names_in(
                    self.cmd(
                        f"iot adr ns link su list --ns {namespace_name} -g {rg}"
                    ).get_output_in_json()
                ) == {su_endpoint}
                _log(LogKind.OK, "Software Updates link '%s' created (UAMI)", su_endpoint)

            with timed_step("Step 2 > link su show / list (single entry)"):
                shown = self.cmd(
                    f"iot adr ns link su show --ns {namespace_name} -g {rg} -n {su_endpoint}"
                ).get_output_in_json()
                assert shown.get("name") == su_endpoint, (
                    f"link su show did not surface name field: {shown}"
                )
                assert _identity_type(shown) == "UserAssigned", (
                    f"Expected UserAssigned inbound identity, saw: {_identity_type(shown)}"
                )

                listed = self.cmd(
                    f"iot adr ns link su list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                names = _names_in(listed)
                assert su_endpoint in names, (
                    f"Software Updates link '{su_endpoint}' missing from list: {names}"
                )
                assert len(names) == 1, f"Expected exactly one Software Updates link, got {names}"
                _log(LogKind.OK, "Software Updates list returned 1 entry")

            with timed_step("Step 3 > Software Updates data-plane discovery"):
                updates = self.cmd(
                    f"iot adr ns su software-update list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                classes = self.cmd(
                    f"iot adr ns su device-class list --ns {namespace_name} -g {rg}"
                ).get_output_in_json()
                assert isinstance(updates, list)
                assert isinstance(classes, list)
                _log(
                    LogKind.OK,
                    "Software Updates data plane returned %d update(s), %d class(es)",
                    len(updates),
                    len(classes),
                )

            with timed_step("Step 4 > link su update (rotate identity UAMI to SAMI)"):
                update_cmd = (
                    f"iot adr ns link su update --ns {namespace_name} -g {rg} "
                    f"-n {su_endpoint} --mi-system-assigned"
                )
                _log(LogKind.CMD, "az %s", update_cmd)
                self.cmd(update_cmd)
                shown = _wait_for_linking_succeeded(
                    self,
                    "su",
                    namespace_name,
                    rg,
                    su_endpoint,
                    expected_identity_type="SystemAssigned",
                )
                assert _identity_type(shown) == "SystemAssigned", (
                    f"Expected SystemAssigned after rotation, saw: {_identity_type(shown)}"
                )
                _log(LogKind.OK, "Rotated UAMI to SAMI")

            with timed_step(
                "Step 5 > link su delete (disposable Update Instance)"
            ):
                self.cmd(
                    f"iot adr ns link su delete --ns {namespace_name} -g {rg} "
                    f"-n {su_endpoint} --yes"
                )
                su_deleted = True
                assert self.cmd(
                    f"iot adr ns link su list --ns {namespace_name} -g {rg}"
                ).get_output_in_json() == []
                self.cmd(
                    f"resource show --ids {su_id}",
                    expect_failure=True,
                )
                _log(
                    LogKind.OK,
                    "Update Instance resource and namespace endpoint deleted",
                )

            _log(LogKind.OK, "Software Updates link lifecycle passed")

        finally:
            active_error = sys.exc_info()[1]
            cleanup_failures = []
            with timed_step("Cleanup ❯ Delete ADR namespace"):
                try:
                    self.cmd(f"iot adr ns delete -n {namespace_name} -g {rg} -y")
                    _log(LogKind.RESULT, "ADR namespace deleted")
                except Exception as error:  # noqa: BLE001 - report after all cleanup
                    cleanup_failures.append(("namespace", error))
                    _log(LogKind.WARN, "Namespace cleanup failed: %s", error)
            with timed_step("Cleanup ❯ Delete disposable Update Instance"):
                if su_deleted:
                    _log(
                        LogKind.RESULT,
                        "Disposable Update Instance already deleted by link su delete",
                    )
                else:
                    try:
                        parsed_su_id = parse_resource_id(su_id)
                        instance_name = parsed_su_id["name"]
                        instance_rg = parsed_su_id["resource_group"]
                        self.cmd(
                            f"iot adr ns su instance delete -n {instance_name} "
                            f"-g {instance_rg} --yes --no-wait"
                        )
                        self.cmd(
                            f"iot adr ns su instance wait -n {instance_name} "
                            f"-g {instance_rg} --deleted"
                        )
                        _log(LogKind.RESULT, "Disposable Update Instance deleted")
                    except Exception as error:  # noqa: BLE001 - report after all cleanup
                        cleanup_failures.append(("Update Instance", error))
                        _log(LogKind.WARN, "Update Instance cleanup failed: %s", error)
            if cleanup_failures and active_error is None:
                detail = ", ".join(
                    f"{resource}: {error}"
                    for resource, error in cleanup_failures
                )
                raise AssertionError(
                    f"Cleanup failed: {detail}"
                ) from cleanup_failures[0][1]


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkValidationNegatives(CaptureOutputLiveScenarioTest):
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

        # --- Update Instance resource-id parsing rejections (su add) ---
        with timed_step("SU add ❯ empty --su-id rejected"):
            self.cmd(
                f'iot adr ns link su add -n primary --ns {ns} -g {rg} --su-id "" --mi-sa',
                expect_failure=True,
            )
        with timed_step("SU add ❯ bare Update Instance name rejected"):
            self.cmd(
                f"iot adr ns link su add -n primary --ns {ns} -g {rg} --su-id mysu --mi-sa",
                expect_failure=True,
            )
        with timed_step("SU add ❯ wrong resource type rejected"):
            self.cmd(
                f"iot adr ns link su add -n primary --ns {ns} -g {rg} --su-id {hub_id} --mi-sa",
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
        with timed_step("SU update ❯ SAMI + UAMI together rejected"):
            self.cmd(
                f"iot adr ns link su update -n primary --ns {ns} -g {rg} "
                f"--mi-sa --mi-ua {uami_id}",
                expect_failure=True,
            )

        _log(LogKind.OK, "All link validation negatives rejected client-side as designed")
