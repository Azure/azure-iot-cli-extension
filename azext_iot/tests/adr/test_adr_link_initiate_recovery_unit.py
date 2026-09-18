# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline regressions for the two observed, target-bound linkInitiate denials."""

from copy import deepcopy
from types import MethodType
from unittest.mock import Mock
import json

import pytest
from azure.cli.core.azclierror import AzureResponseError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.base import ADRResourceStateError
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery
from azext_iot.adr.rbac import LINK_ROLE_MATRIX, resolve_namespace_outbound_principal
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr.test_adr_link_propagation_unit import Harness, KINDS, NS_ID
from azext_iot.tests.adr.test_adr_link_unit import DPS_ID, HUB_ID, UAMI_ID


SAMI = "11111111-1111-4111-8111-111111111111"
UAMI = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"


def _denial(harness, *, kind=None, principal=None, action=None, scope=None):
    kind = kind or harness.kind
    service = {"hub": "Hub", "dps": "DPS", "su": "SU"}[kind]
    action = action or KINDS[kind][1] + "/linkInitiate/action"
    principal = principal or resolve_namespace_outbound_principal(harness.namespace)
    scope = scope or harness.body["resourceId"]
    return {
        "code": "LinkInitiateFailed",
        "message": (
            f"The namespace's managed identity is not authorized to link the {service} resource. "
            "Grant it access on the resource, then resubmit the request. "
            f"({service} resource reported: [AuthorizationFailed] The client '{CLIENT}' "
            f"with object id '{principal}' does not have authorization to perform action '{action}' "
            f"over scope '{scope}' or the scope is invalid. "
            "If access was recently granted, please refresh your credentials.)"
        ),
    }


def _harness(mocker, kind="dps", identity="system", action="add"):
    h = Harness(mocker, kind, identity, action)
    h.namespace["identity"]["principalId"] = SAMI
    if identity == "user":
        h.namespace["identity"]["userAssignedIdentities"][UAMI_ID]["principalId"] = UAMI
    h.denial = _denial(h)
    h.outcomes = ["initiate", "success"]
    original_wait = h.wait

    def wait(poller, **kwargs):
        try:
            return original_wait(poller, **kwargs)
        except ADRResourceStateError:
            h.namespace["properties"][poller.section]["endpoints"][poller.name]["linkingError"] = deepcopy(h.denial)
            raise ADRResourceStateError(
                h.provider._format_failure("Failed", h.namespace, None), deepcopy(h.namespace),
            ) from None

    h.provider._await_terminal.side_effect = wait
    return h


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("identity", ["system", "user"])
@pytest.mark.parametrize("action", ["add", "update"])
def test_exact_link_initiate_authorization_recovers_with_verified_original_roles(mocker, kind, identity, action):
    h = _harness(mocker, kind, identity, action)
    verify = mocker.spy(h.provider._rbac, "verify_many")
    result = h.run(timeout_sec=120, wait_sec=1)
    section = KINDS[kind][0]
    assert result["properties"][section]["endpoints"][kind]["linkingState"] == "Succeeded"
    assert h.patches == [{section: {"endpoints": {kind: h.body}}}] * 2
    assert h.clock.delays == [30]
    assert verify.call_count == 2
    assert len(h.created) == len(LINK_ROLE_MATRIX[kind])  # No new recovery grants.


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("mutation", [
    "invalid-request", "principal", "client-is-principal", "action", "scope", "scope-prefix",
    "service", "code", "embedded-message", "trailing-message", "additional-error", "malformed-guid",
])
def test_unbound_or_other_link_initiate_failures_are_not_retried(mocker, kind, mutation):
    h = _harness(mocker, kind)
    if mutation == "invalid-request":
        h.denial["message"] = (
            "The DPS resource rejected the link request as invalid. "
            "Verify the endpoint configuration, then resubmit the request."
        )
    elif mutation == "principal":
        h.denial = _denial(h, principal=UAMI)
    elif mutation == "client-is-principal":
        h.denial = _denial(h, principal=CLIENT)
        h.denial["message"] = h.denial["message"].replace(f"client '{CLIENT}'", f"client '{SAMI}'")
    elif mutation == "action":
        h.denial = _denial(h, action=KINDS[kind][1] + "/read")
    elif mutation in {"scope", "scope-prefix"}:
        h.denial = _denial(h, scope=h.body["resourceId"] + ("/child" if mutation == "scope" else "-other"))
    elif mutation == "service":
        h.denial = _denial(h, kind="hub" if kind == "dps" else "dps")
    elif mutation == "code":
        h.denial["code"] = "AuthorizationFailed"
    elif mutation == "embedded-message":
        h.denial["message"] = "Unrelated failure: " + h.denial["message"]
    elif mutation == "trailing-message":
        h.denial["message"] += " Another error occurred."
    elif mutation == "additional-error":
        h.denial["details"] = [{"code": "OtherFailure"}]
    else:
        h.denial["message"] = h.denial["message"].replace(CLIENT, "not-a-guid")
    with pytest.raises(ADRResourceStateError):
        h.run()
    assert len(h.patches) == 1
    assert not h.clock.delays


def test_su_does_not_inherit_unobserved_link_initiate_recovery(mocker):
    h = _harness(mocker, "su")
    with pytest.raises(ADRResourceStateError):
        h.run()
    assert len(h.patches) == 1 and not h.clock.delays


def test_link_initiate_recovery_accepts_only_arm_identifier_casing_variation(mocker):
    h = _harness(mocker)
    h.denial = _denial(h, action=(KINDS["dps"][1] + "/linkInitiate/action").upper(),
                       scope=h.body["resourceId"].upper(), principal=SAMI.upper())
    h.run()
    assert len(h.patches) == 2


@pytest.mark.parametrize("mutation", ["principal", "role", "target", "identity", "settings", "dependency", "preflight"])
def test_link_initiate_recovery_still_rejects_drift_before_second_patch(mocker, mutation):
    h = _harness(mocker, "hub")

    def change():
        if mutation == "principal":
            h.namespace["identity"]["principalId"] = UAMI
        elif mutation == "role":
            h.assignments.clear()
        elif mutation == "preflight":
            h.target["identity"]["principalId"] = UAMI
        else:
            endpoint = h.namespace["properties"]["messaging"]["endpoints"]["hub"]
            if mutation == "target":
                endpoint["resourceId"] += "-other"
            elif mutation == "identity":
                endpoint["inboundCallerIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
            elif mutation == "settings":
                endpoint["provisioning"]["allocationWeight"] = 99
            else:
                h.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] = "Failed"

    h.clock.on_sleep = change
    with pytest.raises(AzureResponseError):
        h.run()
    assert len(h.patches) == 1
    assert len(h.created) == len(LINK_ROLE_MATRIX["hub"])


def test_repeated_link_initiate_denial_uses_original_deadline_and_backoff(mocker):
    h = _harness(mocker)
    h.outcomes = ["initiate"] * 10
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(timeout_sec=100)
    assert h.clock.delays == [30, 60, 10]
    assert h.clock.now == 100 and len(h.patches) == 3


@pytest.mark.parametrize("mutation", ["missing", "principal", "namespace", "target", "kind"])
def test_observed_error_requires_the_original_preflight_binding(mocker, mutation):
    h = _harness(mocker)
    request = {
        "link_type": "dps", "namespace_scope": NS_ID, "target_scope": DPS_ID,
        "namespace_principal_id": SAMI,
    }
    if mutation == "missing":
        request = None
    else:
        field = {"principal": "namespace_principal_id", "namespace": "namespace_scope",
                 "target": "target_scope", "kind": "link_type"}[mutation]
        request[field] = UAMI if mutation == "principal" else request[field] + "-other"
    recovery = LinkRecovery(
        h.provider, h.namespace, "provisioning", "dps", h.body,
        LinkDeadline(clock=h.clock.time, sleeper=h.clock.sleep), Mock(), authorization_request=request,
    )
    assert not recovery.authorized_failure({"linkingState": "Failed", "linkingError": h.denial})


@pytest.mark.parametrize("status", [400, 403, 500])
def test_http_error_text_is_not_a_current_structured_endpoint_denial(mocker, status):
    h = _harness(mocker)
    h.submit_error = HttpResponseError(h.denial["message"])
    h.submit_error.status_code = status
    h.submit_error.error = Mock(code="LinkInitiateFailed")
    with pytest.raises(HttpResponseError) as caught:
        h.run()
    assert caught.value is h.submit_error
    assert not h.patches and not h.clock.delays


def test_stale_link_initiate_failure_does_not_replay_an_accepted_recovery(mocker):
    h = _harness(mocker)
    original_submit = h.submit

    def submit(**kwargs):
        failed = deepcopy(h.namespace) if h.patches else None
        poller = original_submit(**kwargs)
        if failed:
            h.namespace = failed
        return poller

    h.client.namespaces.begin_update.side_effect = submit
    h.outcomes = ["initiate"] * 5
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(timeout_sec=65, wait_sec=10)
    assert len(h.patches) == 2 and h.clock.delays == [30, 10, 10, 10, 5]


def test_no_wait_does_not_start_link_initiate_observation_or_recovery(mocker):
    h = _harness(mocker)
    result = h.run(no_wait=True)
    assert result.section == "provisioning"
    assert len(h.patches) == 1 and not h.clock.delays
    h.provider._await_terminal.assert_not_called()


def test_combined_add_recovers_dps_before_hub_using_one_deadline(mocker):
    h = _harness(mocker)
    h.outcomes = ["initiate", "success", "success"]
    h.provider.link_add(
        namespace_name="ns", resource_group_name="rg", dps_endpoint_name="dps", dps_resource_id=DPS_ID,
        hub_endpoint_name="hub", hub_resource_id=HUB_ID, dps_mi_system_assigned=True, timeout_sec=120,
    )
    assert [next(iter(patch)) for patch in h.patches] == ["provisioning", "provisioning", "messaging"]
    assert h.clock.delays == [30]


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_generated_sdk_namespace_status_binds_link_initiate_denial(mocker, mocked_response, kind):
    h = _harness(mocker, kind)
    h.provider._await_terminal = MethodType(LinkProvider._await_terminal, h.provider)
    section = KINDS[kind][0]
    patches = []
    url = "https://centraluseuap.management.azure.com" + NS_ID

    def respond(request):
        if request.method == "PATCH":
            patches.append(json.loads(request.body))
            succeeded = len(patches) == 2
            h.namespace["properties"]["provisioningState"] = "Succeeded" if succeeded else "Failed"
            endpoint = {**deepcopy(h.body), "linkingState": "Succeeded" if succeeded else "Failed"}
            if not succeeded:
                endpoint["linkingError"] = h.denial
            h.namespace["properties"][section] = {"endpoints": {kind: endpoint}}
            return 202, {"Content-Type": "application/json"}, json.dumps(h.namespace)
        return 200, {"Content-Type": "application/json"}, json.dumps(h.namespace)

    mocked_response.add_callback("PATCH", url, callback=respond)
    mocked_response.add_callback("GET", url, callback=respond)
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-unit-token", 4102444800)
    with DeviceRegistryMgmtClient(
        credential, "sub", base_url="https://centraluseuap.management.azure.com", retry_total=0,
    ) as client:
        h.provider.client = client
        result = h.run(timeout_sec=120, wait_sec=1)
    assert result["properties"][section]["endpoints"][kind]["linkingState"] == "Succeeded"
    assert patches == [{"properties": {section: {"endpoints": {kind: h.body}}}}] * 2
    assert len(h.created) == len(LINK_ROLE_MATRIX[kind])
