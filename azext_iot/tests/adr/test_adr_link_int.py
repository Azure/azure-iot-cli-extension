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

from copy import deepcopy
import json
import os
import re
import shlex
from time import monotonic, sleep
from typing import Optional
from urllib.parse import urlsplit

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, InvalidArgumentValueError
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from azext_iot._factory import _ADR_DPS_API_VERSION, adr_service_factory
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    ROLE_PROPAGATION_DELAY,
    wait_for_condition,
    wait_for_resource_absent,
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
from azext_iot.tests.helpers import ScenarioBudget
from azext_iot.tests.settings import HUB_TEST_LOCATION
from azext_iot.adr.topology import (
    DPS_CAP_EXCEEDED_MSG,
    endpoint_settings_match,
    endpoint_update_body,
)
from azext_iot.adr.rbac import (
    ADR_CONTRIBUTOR_ROLE,
    CONTRIBUTOR_ROLE,
    HUB_DATA_ROLE,
    required_assignments,
    resolve_namespace_outbound_principal,
)


_LINKING_POLL_ATTEMPTS = int(os.getenv("azext_iot_adr_su_link_poll_attempts", "240"))
_LINKING_POLL_INTERVAL_SECONDS = 10
_NATIVE_LINK_TIMEOUT = 1200
_NATIVE_LINK_INTERVAL = 10
_HUB_IDENTITY_ROTATION_BACKOFFS = (30, 60, 120)
_HUB_IDENTITY_ROTATION_BUDGET_SECONDS = 600
_HUB_ROTATION_REJECTED_CHAIN = re.compile(r"\(IdentityRotationUpdateFailed\) " + _LINK_INITIATE_REJECTED.pattern)
_HUB_ROTATION_REJECTED_MESSAGE = re.compile(r"(?:IdentityRotationUpdateFailed: )?" + _LINK_INITIATE_REJECTED.pattern)
_HUB_ROTATION_CURRENT_MESSAGE = (
    "The Hub link request was rejected. Contact support with the namespace resource "
    "ID and the time of the request. Include the original request's correlation ID "
    "if available. (Hub resource reported: [400913])"
)
_HUB_ROTATION_CURRENT_CHAIN = re.compile(
    r"\(IdentityRotationUpdateFailed\) " + re.escape(_HUB_ROTATION_CURRENT_MESSAGE) + r"(?=$|\n)"
)
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


def _error_chain(error):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)


def _error_chain_text(error):
    texts = []
    for current in _error_chain(error):
        texts.append(str(current))
        detail = getattr(current, "error", None)
        code = detail.get("code") if isinstance(detail, dict) else getattr(detail, "code", None)
        if isinstance(code, str):
            texts.append(code)
    return "\n".join(texts)


def _structured_hub_rotation_rejection(endpoint):
    """Persisted form, held to the same structural guards as the DPS readiness classifier."""
    properties = _link_properties(endpoint or {})
    error = properties.get("linkingError")
    if properties.get("linkingState") != "Failed" or not isinstance(error, dict) or set(error) - {"code", "message"}:
        return False
    message = error.get("message")
    match = _HUB_ROTATION_REJECTED_MESSAGE.fullmatch(message) if isinstance(message, str) else None
    return bool(error.get("code") == "IdentityRotationUpdateFailed" and (
        (match and match["service"] == "Hub")
        or message in (_HUB_ROTATION_CURRENT_MESSAGE, "IdentityRotationUpdateFailed: " + _HUB_ROTATION_CURRENT_MESSAGE)
    ))


def _is_identity_rotation_authorization_failure(*, error=None, endpoint=None):
    detail = _link_failure_detail(endpoint or {}) if endpoint else {}
    properties = _link_properties(endpoint or {})
    if properties.get("error") or any(
        (properties.get(key) or {}).get("error") for key in ("status", "provisioningStatus")
    ):
        return False
    if detail and (
        properties.get("linkingState") != "Failed"
        or detail.get("code") != "IdentityRotationUpdateFailed"
        or set(detail) - {"code", "message"}
    ):
        return False
    chain = _error_chain_text(error) if error else ""
    if set(re.findall(r"\(([A-Za-z][A-Za-z0-9]+)\)", chain)) - {"LinkingFailed", "IdentityRotationUpdateFailed"}:
        return False
    text = " ".join(filter(None, [detail.get("code"), detail.get("message"), chain]))
    if "IdentityRotationUpdateFailed" not in text:
        return False
    # The generic "rejected as invalid" text is otherwise a permanent configuration error; accept it only
    # when the service attributes it to identity rotation, either in the error chain or the persisted state.
    rejected = _HUB_ROTATION_REJECTED_CHAIN.search(chain)
    return bool(
        (rejected and rejected["service"] == "Hub")
        or _HUB_ROTATION_CURRENT_CHAIN.search(chain)
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


def _current_rotation_rejection(error, namespace_id, endpoint_name):
    chain = list(_error_chain(error))
    if any(isinstance(value, (ServiceRequestError, ServiceResponseError)) for value in chain):
        return False
    subscription = namespace_id.split("/")[2]
    for value in chain:
        if not isinstance(value, HttpResponseError) or value.status_code != 200:
            continue
        response = value.response
        request = getattr(response, "request", None)
        if getattr(request, "method", None) != "GET" or not re.fullmatch(
            rf"/subscriptions/{re.escape(subscription)}/providers/Microsoft\.DeviceRegistry/"
            r"locations/[^/]+/(?:asyncOperationStatuses|operationStatuses)/[^/]+",
            urlsplit(getattr(request, "url", "")).path, re.IGNORECASE,
        ):
            continue
        if not callable(getattr(response, "json", None)):
            return False
        try:
            body = response.json()
        except (ValueError, TypeError):
            return False
        if not isinstance(body, dict) or body.get("status") != "Failed":
            return False
        detail = body.get("error")
        if not isinstance(detail, dict):
            return False
        if detail.get("code") == "LinkingFailed":
            details = detail.get("details")
            if set(detail) - {"code", "message", "details"} or not isinstance(details, list) or len(details) != 1:
                return False
            detail = details[0]
        if not isinstance(detail, dict):
            return False
        detail = dict(detail)
        if "target" in detail and detail.pop("target") != f"properties.messaging.endpoints[{endpoint_name}]":
            return False
        return _is_identity_rotation_authorization_failure(
            endpoint={"linkingState": "Failed", "linkingError": detail},
        )
    return False


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


def _assert_hub_rotation_retry_safe(endpoint, hub_id, previous_user_identity, baseline):
    properties = _link_properties(endpoint)
    assert properties.get("resourceId", "").casefold() == hub_id.casefold(), "Hub rotation resourceId changed."
    identity = properties.get("inboundCallerIdentity") or {}
    identity_type = identity.get("type")
    assert identity_type in {"SystemAssigned", "UserAssigned"}, "Hub rotation identity type changed."
    if identity_type == "UserAssigned":
        assert identity.get("userAssignedIdentity", "").casefold() == previous_user_identity.casefold(), (
            "Hub rotation user-assigned identity changed."
        )
    actual = endpoint_update_body(properties, {"type": "SystemAssigned"})
    expected = endpoint_update_body(baseline, {"type": "SystemAssigned"})
    for projection in (actual, expected):
        for key in ("resourceId", "endpointType"):
            if isinstance(projection.get(key), str):
                projection[key] = projection[key].casefold()
    assert endpoint_settings_match(actual, expected), "Hub rotation endpoint settings changed; recovery stopped."


def _assert_hub_sami_rotation_grants(test_case, namespace_name, resource_group_name, hub_id, baseline):
    namespace = test_case.cmd(
        f"iot adr ns show -n {namespace_name} -g {resource_group_name}"
    ).get_output_in_json()
    assert namespace["id"].casefold() == baseline["id"].casefold()
    assert namespace["properties"]["provisioningState"] in {"Succeeded", "Failed"}, "Namespace mutation is still active."
    assert namespace["identity"] == baseline["identity"], "Namespace identity changed during rotation."
    assert namespace["properties"].get("outboundIdentity") == baseline["properties"].get("outboundIdentity")
    hub = test_case.cmd(
        f"iot hub show --ids {shlex.quote(hub_id)}"
    ).get_output_in_json()
    namespace_principal = resolve_namespace_outbound_principal(namespace)
    hub_principal = hub["identity"]["principalId"]
    _assert_service_roles(
        test_case,
        [
            (namespace_principal, CONTRIBUTOR_ROLE, hub_id),
            (namespace_principal, HUB_DATA_ROLE, hub_id),
            (hub_principal, ADR_CONTRIBUTOR_ROLE, namespace["id"]),
            (hub_principal, "Reader", namespace["id"]),
            (namespace_principal, "Azure Device Registry Administrator", namespace["id"]),
            (namespace_principal, "Reader", namespace["id"].split("/providers/")[0]),
            (namespace_principal, "Reader", hub_id.split("/providers/")[0]),
        ],
        present=True,
    )


def _update_hub_to_sami_with_recovery(
    test_case, update_cmd, namespace_name, resource_group_name, endpoint_name, hub_id, previous_user_identity,
):
    deadline = monotonic() + _HUB_IDENTITY_ROTATION_BUDGET_SECONDS
    namespace = test_case.cmd(
        f"iot adr ns show -n {namespace_name} -g {resource_group_name}"
    ).get_output_in_json()
    snapshot = deepcopy(namespace["properties"]["messaging"]["endpoints"][endpoint_name])
    assert namespace["properties"]["provisioningState"] == "Succeeded"
    assert _link_observation(snapshot) == ("Succeeded", "UserAssigned"), "Expected a healthy UAMI link before rotation."
    _assert_hub_rotation_retry_safe(snapshot, hub_id, previous_user_identity, snapshot)

    def submit():
        # Bound the synchronous link wait so a slow mutation cannot outlive the recovery budget.
        timeout = int(deadline - monotonic())
        if timeout < 1:
            raise AssertionError("Hub identity rotation authorization recovery budget exhausted")
        try:
            test_case.cmd(f"{update_cmd} --timeout {timeout}")
        except (HttpResponseError, AzureResponseError) as error:
            if not _current_rotation_rejection(error, namespace["id"], endpoint_name):
                raise
            return error
        return None

    first_error = submit()
    for attempt in range(len(_HUB_IDENTITY_ROTATION_BACKOFFS) + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        endpoint = _wait_for_link_terminal(
            test_case, "hub", namespace_name, resource_group_name, endpoint_name, timeout=remaining,
        )
        if monotonic() >= deadline:
            break
        state, identity_type = _link_observation(endpoint)
        if state == "Succeeded" and identity_type == "SystemAssigned":
            _assert_hub_rotation_retry_safe(endpoint, hub_id, previous_user_identity, snapshot)
            return endpoint
        recoverable = first_error is not None and _is_identity_rotation_authorization_failure(
            error=first_error, endpoint=endpoint,
        )
        if state not in {"Failed", "Succeeded"} or not recoverable:
            if first_error is not None:
                raise first_error
            raise AssertionError(f"Non-recoverable Hub identity rotation failure: {_link_failure_detail(endpoint)}")
        if attempt == len(_HUB_IDENTITY_ROTATION_BACKOFFS):
            break
        _assert_hub_rotation_retry_safe(endpoint, hub_id, previous_user_identity, snapshot)
        snapshot = deepcopy(_link_properties(endpoint))
        _assert_hub_sami_rotation_grants(test_case, namespace_name, resource_group_name, hub_id, namespace)
        sleep_for = _HUB_IDENTITY_ROTATION_BACKOFFS[attempt]
        # Never start another mutation that could not be observed within the recovery budget.
        if deadline - monotonic() <= sleep_for:
            break
        sleep(sleep_for)
        if int(deadline - monotonic()) < 1:
            break
        first_error = submit()
    raise AssertionError("Hub identity rotation authorization recovery budget exhausted") from first_error


def _assert_service_roles(test_case, roles, *, present):
    for principal, role, scope in dict.fromkeys(roles):
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
                    f"--system-assigned-mi --user-assigned-mi {identity_resource_id}"
                )
                _log(LogKind.CMD, "az %s", cmd)
                self.create_owned_resource(cmd, kind="dps", name=dps_name, resource_group=rg)
                _log(LogKind.RESULT, "DPS '%s' created", dps_name)

                dps_show = self.cmd(f"iot dps show --name {dps_name} -g {rg}").get_output_in_json()
                dps_id = dps_show["id"]
                dps_system_principal = dps_show["identity"]["principalId"]
                dps_user_principal = next(
                    details["principalId"] for resource_id, details in
                    dps_show["identity"]["userAssignedIdentities"].items()
                    if resource_id.casefold() == identity_resource_id.casefold()
                )
                _log(LogKind.RESULT, "dps_id=%s", dps_id)
                namespace = self.cmd(
                    f"iot adr ns show -n {namespace_name} -g {rg}"
                ).get_output_in_json()
                self_role = (
                    resolve_namespace_outbound_principal(namespace), "Azure Device Registry Administrator", namespace["id"],
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
                _assert_service_roles(self, [(dps_user_principal, "IoT Hub Data Contributor", hub_id)], present=False)
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
                _assert_service_roles(self, [(dps_user_principal, "IoT Hub Data Contributor", hub_id)], present=True)

            with timed_step("Repair only the owned DPS-to-Hub assignment through Hub update"):
                assignments = self.cmd(
                    f"role assignment list --assignee-object-id {dps_user_principal} "
                    f"--role 'IoT Hub Data Contributor' --scope '{hub_id}' --fill-principal-name false"
                ).get_output_in_json()
                exact = [assignment for assignment in assignments
                         if assignment["scope"].casefold() == hub_id.casefold()
                         and assignment["principalId"].casefold() == dps_user_principal.casefold()]
                assert len(exact) == 1, "Expected exactly one owned DPS-to-Hub assignment."
                self.cmd(f"role assignment delete --ids {shlex.quote(exact[0]['id'])}")
                _assert_service_roles(self, [(dps_user_principal, "IoT Hub Data Contributor", hub_id)], present=False)
                self.cmd(
                    f"iot adr ns link hub update --ns {namespace_name} -g {rg} "
                    f"-n {secondary_endpoint} --user-assigned-mi {identity_resource_id}"
                )
                _assert_service_roles(self, [(dps_user_principal, "IoT Hub Data Contributor", hub_id)], present=True)

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
                _assert_service_roles(
                    self, [(dps_user_principal, "IoT Hub Data Contributor", tertiary_hub_id)], present=True,
                )

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
                roles = [(dps_system_principal, "IoT Hub Data Contributor", scope)
                         for scope in (hub_id, tertiary_hub_id)]
                _assert_service_roles(self, roles, present=False)
                self.cmd(
                    f"iot adr ns link dps update --ns {namespace_name} -g {rg} "
                    f"-n {dps_endpoint} --system-assigned-mi"
                )
                _wait_for_linking_succeeded(
                    self, "dps", namespace_name, rg, dps_endpoint, expected_identity_type="SystemAssigned",
                )
                _assert_service_roles(self, roles, present=True)
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
                _assert_service_roles(self, roles, present=True)
                _assert_service_roles(
                    self, [(dps_user_principal, "IoT Hub Data Contributor", scope)
                           for scope in (hub_id, tertiary_hub_id)], present=True,
                )
                _log(LogKind.OK, "DPS identity rotated UAMI to SAMI and back; existing grants retained")

            _log(LogKind.OK, "Link lifecycle passed")

        finally:
            self.cleanup_full_infra()


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkBrownfieldRecovery(ADRFullInfraHelper, ADRLiveScenarioTest):
    @pytest.mark.timeout(3600, func_only=False)
    def test_adr_link_brownfield_recovery(self):
        self._scenario_budget = ScenarioBudget(3600, cleanup=900)
        budget = self._scenario_budget
        rg, namespace_name = TEST_RG, generate_adr_namespace_name()
        hub_names = [generate_hub_name(), generate_hub_name()]
        dps_name, identity_name = generate_dps_name(), generate_identity_name()
        client = adr_service_factory(self.cli_ctx)
        self.addCleanup(client.close)

        def show():
            return self.cmd(f"iot adr ns show -n {namespace_name} -g {rg}").get_output_in_json()

        def etag():
            return budget.call(
                client.namespaces.get, rg, namespace_name,
                cls=lambda response, _body, _headers: response.http_response.headers["ETag"],
            )

        def prepare_roles(namespace, dps, hubs, identity_principal, *, with_namespace_data=True):
            common = {
                "namespace_scope": namespace["id"],
                "namespace_principal_id": resolve_namespace_outbound_principal(namespace),
                "dps_principal_id": dps["identity"]["principalId"],
                "hub_scopes": [hub["id"] for hub in hubs],
            }
            requests = [{
                **common, "link_type": "dps", "target_scope": dps["id"],
                "linked_principal_id": dps["identity"]["principalId"],
                "namespace_system_principal_id": namespace["identity"]["principalId"],
            }, *[{
                **common, "link_type": "hub", "target_scope": hub["id"],
                "linked_principal_id": identity_principal,
            } for hub in hubs]]
            assignments = {assignment for request in requests for _rule, assignment in required_assignments(request)}
            for principal, role, scope in sorted(assignments):
                if not with_namespace_data and principal == common["namespace_principal_id"] and role == HUB_DATA_ROLE:
                    continue
                assert self.assign_role(principal, role, scope, assignee_type="ServicePrincipal")
            budget.call(sleep, ROLE_PROPAGATION_DELAY)

        def seed_classic_hubs(hubs):
            linked = self.cmd(f"iot dps linked-hub list --dps-name {dps_name} -g {rg}").get_output_in_json()
            existing = {hub["name"].casefold() for hub in linked}
            for name, hub in zip(hub_names, hubs):
                if hub["properties"]["hostName"].casefold() not in existing:
                    self.cmd(
                        f"iot dps linked-hub create --dps-name {dps_name} -g {rg} "
                        f"--hub-name {name} --hub-resource-group {rg} "
                        "--hostname-type classic --authentication-type SystemAssigned"
                    )

        def submit_failed_patch(properties, expected_errors):
            with pytest.raises(HttpResponseError) as raised:
                poller = budget.call(
                    client.namespaces.begin_update, rg, namespace_name,
                    {"properties": properties}, retry_total=0,
                )
                budget.call(poller.result, timeout=budget.remaining(600))
            assert raised.value.status_code == 200, "The deliberate write must fail through its LRO, not at admission."

            def failed_as_requested(resource):
                if resource["properties"]["provisioningState"] != "Failed":
                    return False
                for section, endpoints in expected_errors.items():
                    observed = (resource["properties"].get(section) or {}).get("endpoints") or {}
                    for name, code in endpoints.items():
                        endpoint = observed.get(name) or {}
                        if endpoint.get("linkingState") != "Failed" or (endpoint.get("linkingError") or {}).get("code") != code:
                            return False
                return True

            return wait_for_condition(
                show, failed_as_requested,
                description="deliberate namespace link failure", timeout=budget.remaining(120), interval=5,
            )

        try:
            infra = self.setup_full_infra(
                rg, namespace_name, hub_names[0], identity_name, assign_setup_roles=False,
            )
            identity_id = infra["identity_resource_id"]
            hubs = [self.cmd(f"iot hub show -n {hub_names[0]} -g {rg}").get_output_in_json()]
            hubs.append(self.create_owned_resource(
                f"iot hub create -n {hub_names[1]} -g {rg} --location {HUB_TEST_LOCATION} --sku S1 "
                f"--user-assigned-mi {identity_id} --disable-local-auth true",
                kind="hub", name=hub_names[1], resource_group=rg,
            ).get_output_in_json())
            dps = self.create_owned_resource(
                f"iot dps create -n {dps_name} -g {rg} --location {TEST_LOCATION} "
                "--system-assigned-mi --disable-local-auth true",
                kind="dps", name=dps_name, resource_group=rg,
            ).get_output_in_json()
            bad_identity_name = generate_identity_name()
            bad_identity = self.create_owned_resource(
                f"identity create -n {bad_identity_name} -g {rg} --location {TEST_LOCATION}",
                kind="identity", name=bad_identity_name, resource_group=rg,
            ).get_output_in_json()
            self.cmd(f"iot hub identity assign -n {hub_names[0]} -g {rg} --user {bad_identity['id']}")
            prepare_roles(show(), dps, hubs, infra["identity_principal_id"], with_namespace_data=False)
            seed_classic_hubs(hubs)
            dps_body = {
                "endpointType": "Microsoft.Devices/provisioningServices", "resourceId": dps["id"],
                "inboundCallerIdentity": {"type": "SystemAssigned"},
            }
            hub_bodies = {
                f"hub-{index}": {
                    "endpointType": "Microsoft.Devices/IotHubs", "resourceId": hub["id"],
                    "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": identity_id},
                    "provisioning": {"availability": "Available", "allocationWeight": index + 1},
                } for index, hub in enumerate(hubs)
            }
            with pytest.raises(InvalidArgumentValueError, match="classic Hubs"):
                self.cmd(
                    f"iot adr ns link dps add --ns {namespace_name} -g {rg} -n dps "
                    f"--dps-id {dps['id']} --system-assigned-mi"
                )
            assert not show()["properties"].get("provisioning", {}).get("endpoints")

            # Raw invalid writes reproduce persisted failures that the fixed CLI prevents.
            dps_failure = {"provisioning": {"dps": "DpsHubsNotInNamespace"}}
            submit_failed_patch({"provisioning": {"endpoints": {"dps": dps_body}}}, dps_failure)
            failed = submit_failed_patch(
                {"provisioning": {"endpoints": {"dps": dps_body}}, "messaging": {"endpoints": hub_bodies}},
                {"messaging": {name: "AdrMiNotAuthorized" for name in hub_bodies}},
            )
            for name in hub_bodies:
                assert failed["properties"]["messaging"]["endpoints"][name]["linkingState"] == "Failed"
            prepare_roles(failed, dps, hubs, infra["identity_principal_id"])
            with pytest.raises(AzureResponseError, match="DPS link 'dps'.*Failed"):
                self.cmd(
                    f"iot adr ns link wait --ns {namespace_name} -g {rg} "
                    "--dps-endpoint-name dps --hub-endpoint-name absent --timeout 30 --interval 1"
                )
            self.cmd(
                f"iot adr ns link dps remove --ns {namespace_name} -g {rg} -n dps --yes"
            )
            after = show()
            assert not after["properties"].get("provisioning", {}).get("endpoints")
            assert after["properties"]["messaging"] == failed["properties"]["messaging"]
            submit_failed_patch({"provisioning": {"endpoints": {"dps": dps_body}}}, dps_failure)
            self.cmd(
                f"iot adr ns link update --ns {namespace_name} -g {rg} "
                f"--dps-endpoint-name dps --hub-endpoint-name hub-0 hub-1 --timeout {budget.remaining(600)} --interval 5"
            )
            linked = show()
            for name, body in hub_bodies.items():
                _assert_native_link_result(linked, "messaging", name, body["resourceId"], body["inboundCallerIdentity"])
                assert linked["properties"]["messaging"]["endpoints"][name]["provisioning"] == body["provisioning"]
            _assert_native_link_result(linked, "provisioning", "dps", dps["id"], {"type": "SystemAssigned"})

            self.cmd(
                f"iot adr ns link hub update --ns {namespace_name} -g {rg} -n hub-0 "
                "--availability Disabled --allocation-weight 3"
            )
            updated = show()
            assert updated["properties"]["messaging"]["endpoints"]["hub-0"]["provisioning"] == {
                "availability": "Disabled", "allocationWeight": 3,
            }
            assert (
                updated["properties"]["messaging"]["endpoints"]["hub-0"]["inboundCallerIdentity"]
                == linked["properties"]["messaging"]["endpoints"]["hub-0"]["inboundCallerIdentity"]
            )
            assert (
                updated["properties"]["messaging"]["endpoints"]["hub-1"]
                == linked["properties"]["messaging"]["endpoints"]["hub-1"]
            )
            before_etag = etag()
            recreated = self.cmd(f"iot adr ns create -n {namespace_name} -g {rg}").get_output_in_json()
            assert recreated["properties"] == updated["properties"]
            assert etag() == before_etag

            rotation = deepcopy(hub_bodies["hub-0"])
            rotation["inboundCallerIdentity"]["userAssignedIdentity"] = bad_identity["id"]
            failed = submit_failed_patch({"messaging": {"endpoints": {"hub-0": rotation}}}, {})
            assert failed["properties"]["messaging"]["endpoints"]["hub-0"]["linkingState"] == "Succeeded"
            for command in ("link wait", "link hub wait -n hub-0"):
                with pytest.raises(AzureResponseError, match="terminal provisioningState 'Failed'"):
                    self.cmd(f"iot adr ns {command} --ns {namespace_name} -g {rg} --timeout 30 --interval 1")
            before_etag = etag()
            with pytest.raises(AzureResponseError, match="No changes were submitted"):
                self.cmd(f"iot adr ns create -n {namespace_name} -g {rg}")
            assert etag() == before_etag

            self.cleanup_namespace(namespace_name, rg)
            wait_for_resource_absent(
                self, f"iot adr ns show -n {namespace_name} -g {rg}", timeout=budget.remaining(120),
            )
            namespace_name = generate_adr_namespace_name()
            namespace = self.create_owned_resource(
                f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION} "
                f"--outbound-user-assigned-mi {identity_id}",
                kind="namespace", name=namespace_name, resource_group=rg,
            ).get_output_in_json()
            prepare_roles(namespace, dps, hubs, infra["identity_principal_id"])
            seed_classic_hubs(hubs)
            additional = deepcopy(hub_bodies["hub-1"])
            additional.pop("endpointType")
            self.kwargs["brownfield_hubs"] = shlex.quote(json.dumps({"hub-1": additional}))
            self.cmd(
                f"iot adr ns link add --ns {namespace_name} -g {rg} --dps-endpoint-name dps "
                f"--dps-resource-id {dps['id']} --dps-system-assigned-mi "
                f"--hub-endpoint-name hub-0 --hub-resource-id {hubs[0]['id']} --hub-user-assigned-mi {identity_id} "
                "--hub-endpoints {brownfield_hubs} "
                f"--timeout {budget.remaining(600)} --interval 5"
            )
            linked = show()
            for name, body in hub_bodies.items():
                _assert_native_link_result(linked, "messaging", name, body["resourceId"], body["inboundCallerIdentity"])
            _assert_native_link_result(linked, "provisioning", "dps", dps["id"], {"type": "SystemAssigned"})
        finally:
            budget.begin_cleanup()
            self.cleanup_full_infra()


@pytest.mark.usefixtures("set_cwd")
class TestADRLinkSequentialAdd(ADRFullInfraHelper, ADRLiveScenarioTest):
    """The combined command links DPS successfully before submitting the Hub link.

    Provision fresh targets without service-role grants, leaving the namespace
    empty. One native combined invocation owns RBAC, propagation recovery and
    DPS-first sequencing. No fixture repair or preauthorization delay is allowed.
    """

    @pytest.mark.timeout(1500, func_only=False)
    def test_adr_link_sequential_add(self):
        self._scenario_budget = ScenarioBudget(1500, cleanup=300)
        budget = self._scenario_budget
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
                    timeout=budget.remaining(120),
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
                    timeout=budget.remaining(600),
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
                    (identity["principalId"], "Azure Device Registry Contributor", namespace["id"]),
                    (identity["principalId"], "Reader", namespace["id"]),
                    (namespace_principal, "Azure Device Registry Administrator", namespace["id"]),
                    (namespace_principal, "Reader", namespace["id"].split("/providers/")[0]),
                    (namespace_principal, "Contributor", hub_id),
                    (namespace_principal, "IoT Hub Data Contributor", hub_id),
                    (identity["principalId"], "IoT Hub Data Contributor", hub_id),
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
                    f"--timeout {budget.remaining(_NATIVE_LINK_TIMEOUT)} --interval {_NATIVE_LINK_INTERVAL}"
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
            budget.begin_cleanup()
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

    @pytest.mark.timeout(300, func_only=False)
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
