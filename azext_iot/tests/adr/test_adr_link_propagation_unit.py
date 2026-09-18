# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline mutation/recovery proofs with a deterministic clock and real RBAC preflight."""

from copy import deepcopy
import json
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.polling import LROPoller, NoPolling
from knack.util import CLIError

from azext_iot.adr.providers.base import ADRResourceStateError
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery
from azext_iot.adr.rbac import LINK_ROLE_IDS, LINK_ROLE_MATRIX, LinkRbacManager
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr.test_adr_link_unit import DPS_ID, HUB_ID, SU_ID, UAMI_ID

NS_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
KINDS = {
    "su": ("updating", "Microsoft.DeviceUpdate/updateInstances", SU_ID),
    "dps": ("provisioning", "Microsoft.Devices/provisioningServices", DPS_ID),
    "hub": ("messaging", "Microsoft.Devices/IotHubs", HUB_ID),
}


class Clock:
    def __init__(self):
        self.now = 0
        self.delays = []
        self.on_sleep = None

    def time(self):
        return self.now

    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay
        if self.on_sleep:
            self.on_sleep()


class Harness:
    def __init__(self, mocker, kind="su", identity="system", action="add"):
        self.kind, self.action = kind, action
        self.clock = Clock()
        self.namespace = {
            "id": NS_ID, "location": "centraluseuap",
            "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
            "properties": {"provisioningState": "Succeeded"},
        }
        self.target = {
            "location": "centraluseuap", "properties": {"provisioningState": "Succeeded"},
            "sku": {"name": "S1"},
            "identity": {"type": "SystemAssigned, UserAssigned", "principalId": "target-principal",
                         "userAssignedIdentities": {UAMI_ID: {"principalId": "target-user"}}},
        }
        self.args = {"namespace_name": "ns", "resource_group_name": "rg", "endpoint_name": kind}
        self.inbound = {"type": "SystemAssigned"}
        if identity == "user":
            self.args["mi_user_assigned"] = UAMI_ID
            self.inbound = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
            self.namespace["identity"]["userAssignedIdentities"] = {UAMI_ID: {"principalId": "namespace-user"}}
            self.namespace["properties"]["outboundIdentity"] = deepcopy(self.inbound)
        else:
            self.args["mi_system_assigned"] = True
        section, endpoint_type, resource_id = KINDS[kind]
        self.body = {"endpointType": endpoint_type, "resourceId": resource_id,
                     "inboundCallerIdentity": deepcopy(self.inbound)}
        if kind == "hub":
            self.namespace["properties"]["provisioning"] = {"endpoints": {"dps": {
                "endpointType": KINDS["dps"][1], "resourceId": DPS_ID, "linkingState": "Succeeded",
                "inboundCallerIdentity": deepcopy(self.inbound),
            }}}
            self.body["provisioning"] = {"availability": "Available", "allocationWeight": 25}
            if action == "add":
                self.args.update(availability="Available", allocation_weight=25)
        if action == "add":
            self.args[f"{kind}_resource_id"] = resource_id
        else:
            self.namespace["properties"][section] = {"endpoints": {
                kind: {**deepcopy(self.body), "linkingState": "Failed", "serviceAddress": "read-only"},
            }}
        self.client = Mock()
        self.provider = LinkProvider(Mock(cli_ctx=Mock()), client=self.client)
        self.provider._get_target = Mock(side_effect=lambda *_: deepcopy(self.target))
        self.provider._warn_if_hub_classically_linked = Mock()
        self.provider._rbac = LinkRbacManager(Mock(), clock=self.clock.time, sleeper=self.clock.sleep)
        self.assignments = []
        self.created = []
        self.provider._rbac._current_assignee_object_id = Mock(return_value="caller")
        self.provider._rbac._caller_can_assign = Mock(return_value=True)
        self.provider._rbac._invoke_json = Mock(side_effect=self.rbac)
        self.client.namespaces.get.side_effect = self.get
        self.client.namespaces.begin_update.side_effect = self.submit
        self.provider._await_terminal = Mock(side_effect=self.wait)
        self.outcomes = ["auth", "success"]
        self.patches = []
        self.get_cost = self.submit_cost = self.wait_cost = 0
        self.get_hook = None
        self.wait_error = self.submit_error = None
        mocker.patch("azext_iot.adr.providers.link.monotonic", side_effect=self.clock.time)
        mocker.patch("azext_iot.adr.providers.link.sleep", side_effect=self.clock.sleep)

    def rbac(self, command, **_):
        import shlex
        parts = shlex.split(command)
        principal = parts[parts.index("--assignee-object-id") + 1]
        role = parts[parts.index("--role") + 1]
        scope = parts[parts.index("--scope") + 1]
        assignment = {"principalId": principal, "scope": scope,
                      "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/" + LINK_ROLE_IDS[role]}
        if parts[2] == "create":
            self.assignments.append(assignment)
            self.created.append((principal, role, scope))
            return assignment
        return [item for item in self.assignments if item.get("principalId") == principal
                and item.get("scope") == scope and item.get("roleDefinitionId") == assignment["roleDefinitionId"]]

    def get(self, **_):
        self.clock.now += self.get_cost
        if self.get_hook:
            self.get_hook()
        return deepcopy(self.namespace)

    def submit(self, **kwargs):
        self.clock.now += self.submit_cost
        if self.submit_error:
            raise self.submit_error
        patch = deepcopy(kwargs["properties"]["properties"])
        self.patches.append(patch)
        section = next(iter(patch))
        for name, endpoint in patch[section]["endpoints"].items():
            self.namespace["properties"].setdefault(section, {}).setdefault("endpoints", {})[name] = {
                **endpoint, "linkingState": "InProgress",
            }
        self.namespace["properties"]["provisioningState"] = "Updating"
        return SimpleNamespace(section=section, name=next(iter(patch[section]["endpoints"])))

    def wait(self, poller, **kwargs):
        self.clock.now += self.wait_cost
        if self.wait_error:
            raise self.wait_error
        kwargs["resource_observer"](deepcopy(self.namespace))
        outcome = self.outcomes.pop(0) if self.outcomes else "auth"
        endpoint = self.namespace["properties"][poller.section]["endpoints"][poller.name]
        endpoint["linkingState"] = "Succeeded" if outcome == "success" else "Failed"
        self.namespace["properties"]["provisioningState"] = "Succeeded" if outcome == "success" else "Failed"
        if outcome != "success":
            endpoint["linkingError"] = {"code": "AdrMiNotAuthorized" if outcome == "auth" else outcome,
                                        "message": "The namespace MI is not authorized to read the linked resource."}
            raise ADRResourceStateError(self.provider._format_failure("Failed", self.namespace, None),
                                        deepcopy(self.namespace))
        return deepcopy(self.namespace)

    def run(self, **kwargs):
        return getattr(self.provider, f"{self.kind}_{self.action}")(**self.args, **kwargs)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("action", ["add", "update"])
@pytest.mark.parametrize("identity", ["system", "user"])
def test_fresh_roles_recover_exact_persisted_endpoint_update(mocker, kind, action, identity):
    h = Harness(mocker, kind, identity, action)
    result = h.run()
    section = KINDS[kind][0]
    assert result["properties"][section]["endpoints"][kind]["linkingState"] == "Succeeded"
    assert h.patches == [{section: {"endpoints": {kind: h.body}}}] * 2
    assert h.clock.delays == [30]
    assert len(h.created) == len(LINK_ROLE_MATRIX[kind])
    assert len(h.assignments) == len(h.created)  # recovery verifies, never grants again
    inbound_principal = "target-user" if identity == "user" else "target-principal"
    outbound_principal = "namespace-user" if identity == "user" else "namespace-principal"
    assert h.created == [
        (outbound_principal if rule.principal == "namespace" else inbound_principal,
         rule.role, KINDS[kind][2] if rule.scope == "target" else NS_ID)
        for rule in LINK_ROLE_MATRIX[kind]
    ]


def test_repeated_auth_failure_uses_shared_deadline_and_clamped_backoff(mocker):
    h = Harness(mocker)
    h.outcomes = ["auth"] * 10
    with pytest.raises(AzureResponseError, match="timed out.*AdrMiNotAuthorized"):
        h.run(timeout_sec=100)
    assert h.clock.delays == [30, 60, 10]
    assert len(h.patches) == 3
    assert h.clock.now == 100


@pytest.mark.parametrize("outcome", ["Unauthorized", "Forbidden", "BadRequest", "InternalServerError", "unknown"])
def test_other_endpoint_errors_are_never_retried(mocker, outcome):
    h = Harness(mocker)
    h.outcomes = [outcome]
    with pytest.raises(ADRResourceStateError, match=outcome):
        h.run()
    assert len(h.patches) == 1
    assert not h.clock.delays


@pytest.mark.parametrize("stage", ["submit", "wait", "get"])
@pytest.mark.parametrize("code", [400, 401, 403, 404, 500, 503, None])
def test_unrelated_http_errors_propagate_unchanged_without_retry(mocker, stage, code):
    h = Harness(mocker)
    error = HttpResponseError("original service context")
    error.status_code = code
    if stage == "get":
        def fail():
            if h.patches:
                raise error
        h.get_hook = fail
    elif stage == "submit":
        h.submit_error = error
    else:
        h.wait_error = error
    with pytest.raises(HttpResponseError) as caught:
        h.run()
    assert caught.value is error
    assert len(h.patches) <= 1
    assert not h.clock.delays
    if stage == "get":
        assert isinstance(caught.value.__cause__, ADRResourceStateError)


@pytest.mark.parametrize("mutation", [
    "resourceId", "endpointType", "inboundCallerIdentity", "provisioning", "outboundIdentity",
    "namespacePrincipal", "targetPrincipal", "state", "error", "otherEndpoint",
])
def test_concurrent_mutations_are_not_overwritten(mocker, mutation):
    h = Harness(mocker, "hub")

    def change():
        endpoint = h.namespace["properties"]["messaging"]["endpoints"]["hub"]
        if mutation == "outboundIdentity":
            h.namespace["properties"][mutation] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        elif mutation == "namespacePrincipal":
            h.namespace["identity"]["principalId"] = "rotated"
        elif mutation == "targetPrincipal":
            h.target["identity"]["principalId"] = "rotated"
        elif mutation == "state":
            endpoint["linkingState"] = "Succeeded"
            endpoint.pop("linkingError")
        elif mutation == "error":
            endpoint["linkingError"]["code"] = "Different"
        elif mutation == "otherEndpoint":
            h.namespace["properties"]["provisioning"]["endpoints"]["new"] = {"endpointType": "Future"}
        elif mutation == "provisioning":
            endpoint[mutation]["allocationWeight"] = 100
        elif mutation == "inboundCallerIdentity":
            endpoint[mutation] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        else:
            endpoint[mutation] += "-other"

    if mutation == "targetPrincipal":
        h.get_hook = lambda: change() if h.patches else None
    else:
        h.clock.on_sleep = change
    with pytest.raises(AzureResponseError, match="changed"):
        h.run()
    assert len(h.patches) == 1


@pytest.mark.parametrize("phase", ["submit", "get", "wait"])
@pytest.mark.parametrize("no_wait", [False, True])
def test_expired_rpc_rejects_late_success_and_stops_next_operation(mocker, phase, no_wait):
    h = Harness(mocker)
    h.outcomes = ["success"]
    if no_wait and phase != "submit":
        h.run(no_wait=True, timeout_sec=3)
        h.provider._await_terminal.assert_not_called()
        assert h.client.namespaces.get.call_count == 1
        return
    if phase == "get":
        h.get_hook = lambda: setattr(h.clock, "now", 3) if h.patches else None
    else:
        setattr(h, phase + "_cost", 3)
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(timeout_sec=3, no_wait=no_wait)
    assert len(h.patches) == 1
    assert h.client.namespaces.get.call_count == (2 if phase == "get" else 1)
    if phase == "submit":
        h.provider._await_terminal.assert_not_called()


@pytest.mark.parametrize("kind", KINDS)
def test_already_effective_authorization_has_no_propagation_delay(mocker, kind):
    h = Harness(mocker, kind)
    h.outcomes = ["success"]
    h.run()
    assert not h.clock.delays
    assert len(h.patches) == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("action", ["add", "update"])
def test_standalone_no_wait_returns_final_poller_without_observation(mocker, kind, action):
    h = Harness(mocker, kind, action=action)
    result = h.run(no_wait=True)
    assert result.section == KINDS[kind][0]
    h.provider._await_terminal.assert_not_called()
    assert h.client.namespaces.get.call_count == 1
    assert not h.clock.delays
    assert "polling" not in h.client.namespaces.begin_update.call_args.kwargs


@pytest.mark.parametrize("failure", ["missing", "condition", "permission"])
def test_recovery_rbac_is_read_only_and_fail_closed(mocker, failure):
    h = Harness(mocker)
    original = h.get

    def get(**kwargs):
        result = original(**kwargs)
        if h.patches:
            if failure == "missing":
                h.assignments.clear()
            elif failure == "condition":
                h.assignments[0]["condition"] = "restricted"
            else:
                h.provider._rbac._invoke_json.side_effect = AzureResponseError("Permission denied")
        return result

    h.client.namespaces.get.side_effect = get
    with pytest.raises(AzureResponseError):
        h.run()
    assert len(h.patches) == 1
    assert len(h.created) == 2
    assert not h.clock.delays


@pytest.mark.parametrize("option", ["timeout_sec", "wait_sec"])
@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("action", ["add", "update"])
def test_positive_options_checked_before_any_preflight(mocker, kind, action, option, value):
    h = Harness(mocker, kind, action=action)
    with pytest.raises(InvalidArgumentValueError):
        h.run(**{option: value})
    h.client.namespaces.get.assert_not_called()
    assert not h.created


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("outcomes,sections", [
    (["auth", "success", "success"], ["provisioning", "provisioning", "messaging"]),
    (["success", "auth", "success"], ["provisioning", "messaging", "messaging"]),
])
def test_combined_dependency_and_hub_recovery_do_not_replay_successful_dps(mocker, no_wait, outcomes, sections):
    h = Harness(mocker, "dps")
    h.outcomes = outcomes[:]
    result = h.provider.link_add(
        namespace_name="ns", resource_group_name="rg", dps_endpoint_name="dps", dps_resource_id=DPS_ID,
        hub_endpoint_name="hub", hub_resource_id=HUB_ID,
        dps_mi_system_assigned=True, hub_mi_system_assigned=True, no_wait=no_wait,
    )
    expected_sections = sections[:2] if no_wait and sections[1] == "messaging" else sections
    assert [next(iter(patch)) for patch in h.patches] == expected_sections
    assert h.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] == "Succeeded"
    if no_wait:
        assert result.section == "messaging"
    else:
        assert result["properties"]["messaging"]["endpoints"]["hub"]["linkingState"] == "Succeeded"


def test_combined_dps_auth_deadline_prevents_hub(mocker, caplog):
    h = Harness(mocker, "dps")
    h.outcomes = ["auth"] * 5
    with pytest.raises(AzureResponseError, match="timed out"):
        h.provider.link_add(
            namespace_name="ns", resource_group_name="rg", dps_endpoint_name="dps", dps_resource_id=DPS_ID,
            hub_endpoint_name="hub", hub_resource_id=HUB_ID, dps_mi_system_assigned=True,
            no_wait=True, timeout_sec=60,
        )
    assert all("messaging" not in patch for patch in h.patches)
    assert "Hub link was NOT submitted" in caplog.text


def test_real_azure_core_poller_result_is_not_replaced_with_timeout_none(mocker):
    h = Harness(mocker)
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", False)
    h.provider._await_terminal = MethodType(LinkProvider._await_terminal, h.provider)
    response = {"real": "result"}
    poller = LROPoller(Mock(), response, lambda value: value, NoPolling())
    budget = LinkDeadline(10, 1, clock=h.clock.time, sleeper=h.clock.sleep)
    assert h.provider._wait(poller, "wait", deadline_guard=budget.remaining, sleeper=budget.pause) == response


def test_unknown_cli_error_is_not_treated_as_structured_authorization(mocker):
    h = Harness(mocker)
    h.wait_error = CLIError("AdrMiNotAuthorized")
    with pytest.raises(CLIError) as caught:
        h.run()
    assert caught.value is h.wait_error
    assert len(h.patches) == 1 and not h.clock.delays


def _real_resource_pollers(h, mocker):
    """Real Azure Core pollers with canary metadata; no background network."""
    h.provider._await_terminal = MethodType(LinkProvider._await_terminal, h.provider)
    pollers = []
    url = "https://centraluseuap.management.azure.com" + NS_ID + "?api-version=2026-11-02-preview"

    def submit(**kwargs):
        endpoint = h.submit(**kwargs)
        request = SimpleNamespace(url=url, method="PATCH")
        initial = SimpleNamespace(
            http_request=request,
            http_response=Mock(status_code=202, headers={
                "Azure-AsyncOperation": "https://control-plane.prod.centraluseuap.iotadr.net/broken-status",
            }),
        )
        poller = LROPoller(Mock(), initial, lambda value: value, NoPolling())
        poller.endpoint = endpoint
        mocker.spy(poller, "result")
        pollers.append(poller)
        return poller

    def read(request):
        assert request.method == "GET" and request.url == url
        try:
            h.wait(pollers[-1].endpoint, resource_observer=lambda _: None)
        except ADRResourceStateError:
            pass  # Return the structured service body to the real resource waiter.
        return Mock(status_code=200, headers={}, json=Mock(return_value=deepcopy(h.namespace)))

    h.client.namespaces.begin_update.side_effect = submit
    h.client.send_request.side_effect = read
    return pollers


def test_real_azure_core_poller_canary_resource_failure_recovers_without_async_status_call(mocker):
    h = Harness(mocker)
    pollers = _real_resource_pollers(h, mocker)
    result = h.run(wait_sec=1)
    assert result["properties"]["updating"]["endpoints"]["su"]["linkingState"] == "Succeeded"
    assert len(h.patches) == len(pollers) == 2
    assert h.clock.delays == [1, 30, 1]
    assert h.client.send_request.call_count == 2
    for poller in pollers:
        poller.result.assert_not_called()
    assert all(call.kwargs["polling"] is False for call in h.client.namespaces.begin_update.call_args_list)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_real_canary_wait_does_not_retry_unrelated_http_failures(mocker, status):
    h = Harness(mocker)
    _real_resource_pollers(h, mocker)
    error = HttpResponseError(f"original HTTP {status}")
    error.status_code = status
    error.error = SimpleNamespace(code="AdrMiNotAuthorized")
    h.client.send_request.side_effect = None
    h.client.send_request.return_value = Mock(status_code=status, raise_for_status=Mock(side_effect=error))
    with pytest.raises(HttpResponseError) as caught:
        h.run(wait_sec=1)
    assert caught.value is error
    assert len(h.patches) == 1
    assert h.client.send_request.call_count == 1
    assert h.client.namespaces.get.call_count == 1
    assert h.clock.delays == [1]


def test_real_canary_late_success_is_rejected_before_endpoint_get_or_retry(mocker):
    h = Harness(mocker)
    h.outcomes = ["success"]
    _real_resource_pollers(h, mocker)
    h.wait_cost = 3
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(wait_sec=1, timeout_sec=3)
    assert h.client.send_request.call_count == 1
    assert h.client.namespaces.get.call_count == 1
    assert len(h.patches) == 1


def test_expired_before_canary_poll_does_not_issue_resource_get(mocker):
    h = Harness(mocker)
    _real_resource_pollers(h, mocker)
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(wait_sec=30, timeout_sec=3)
    h.client.send_request.assert_not_called()
    assert h.client.namespaces.get.call_count == 1
    assert h.clock.delays == [3]


@pytest.mark.parametrize("mutation", ["target", "assignment"])
def test_principals_and_grants_are_reverified_after_backoff(mocker, mutation):
    h = Harness(mocker)

    def change():
        if mutation == "target":
            h.target["identity"]["principalId"] = "different-principal"
        else:
            h.assignments.clear()

    h.clock.on_sleep = change
    with pytest.raises(AzureResponseError) as caught:
        h.run()
    assert isinstance(caught.value.__cause__, ADRResourceStateError)
    assert len(h.patches) == 1
    assert h.clock.delays == [30]


def test_get_failure_after_backoff_preserves_original_service_error(mocker):
    h = Harness(mocker)
    error = HttpResponseError("reread failed; original correlation ID")
    h.clock.on_sleep = lambda: setattr(h.client.namespaces.get, "side_effect", error)
    with pytest.raises(HttpResponseError) as caught:
        h.run()
    assert caught.value is error
    assert "AdrMiNotAuthorized" in str(caught.value.__cause__)
    assert len(h.patches) == 1


def test_slow_recovery_preflight_expires_before_assignment_reads_or_retry(mocker):
    h = Harness(mocker)
    target_reads = h.provider._get_target

    def target(*_):
        if target_reads.call_count > 1:
            h.clock.now += 3
        return deepcopy(h.target)

    target_reads.side_effect = target
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(timeout_sec=3)
    assert len(h.patches) == 1
    assert not h.clock.delays
    assert h.client.namespaces.get.call_count == 2


def test_stale_failed_after_recovery_never_causes_another_update_without_progress(mocker):
    h = Harness(mocker)
    original_submit = h.submit
    failed = []

    def submit(**kwargs):
        if h.patches:
            failed.append(deepcopy(h.namespace))
        poller = original_submit(**kwargs)
        if failed:
            h.namespace = failed[-1]
        return poller

    h.client.namespaces.begin_update.side_effect = submit
    h.outcomes = ["auth"] * 5
    with pytest.raises(AzureResponseError, match="timed out"):
        h.run(timeout_sec=65, wait_sec=10)
    assert len(h.patches) == 2
    assert h.clock.delays == [30, 10, 10, 10, 5]


@pytest.mark.parametrize("mutation", ["namespace", "endpoint", "state", "error", "error-message", "collection"])
def test_malformed_current_state_never_succeeds_or_retries(mocker, mutation):
    h = Harness(mocker)

    def corrupt():
        if not h.patches:
            return
        if mutation == "namespace":
            h.namespace["properties"] = []
        elif mutation == "collection":
            h.namespace["properties"]["updating"]["endpoints"] = []
        else:
            endpoints = h.namespace["properties"]["updating"]["endpoints"]
            if mutation == "endpoint":
                endpoints["su"] = "invalid"
            elif mutation == "state":
                endpoints["su"]["linkingState"] = "Mystery"
            elif mutation == "error-message":
                endpoints["su"]["linkingError"]["message"] = 123
            else:
                endpoints["su"]["linkingError"] = "AdrMiNotAuthorized"

    h.get_hook = corrupt
    with pytest.raises(AzureResponseError, match="Malformed"):
        h.run()
    assert len(h.patches) == 1 and not h.clock.delays


@pytest.mark.parametrize("field", ["resourceId", "endpointType", "inboundCallerIdentity", "provisioning"])
def test_first_observation_must_match_original_target_identity_and_requested_settings(mocker, field):
    h = Harness(mocker, "hub")
    recovery = LinkRecovery(
        h.provider, deepcopy(h.namespace), "messaging", "hub", h.body,
        LinkDeadline(clock=h.clock.time, sleeper=h.clock.sleep), Mock(),
    )
    current = deepcopy(h.namespace)
    endpoint = {**deepcopy(h.body), "linkingState": "Failed", "linkingError": {"code": "AdrMiNotAuthorized"}}
    current["properties"]["messaging"] = {"endpoints": {"hub": endpoint}}
    endpoint[field] = {"different": "value"} if field in {"inboundCallerIdentity", "provisioning"} else "different"
    with pytest.raises(AzureResponseError, match="changed"):
        recovery.inspect(current)


def test_combined_hub_cannot_get_a_fresh_timeout_budget(mocker):
    h = Harness(mocker, "dps")
    h.outcomes = ["success", "success"]
    h.wait_cost = 2
    with pytest.raises(AzureResponseError, match="timed out"):
        h.provider.link_add(
            namespace_name="ns", resource_group_name="rg", dps_endpoint_name="dps", dps_resource_id=DPS_ID,
            hub_endpoint_name="hub", hub_resource_id=HUB_ID, dps_mi_system_assigned=True, timeout_sec=3,
        )
    assert len(h.patches) == 2
    assert h.client.namespaces.get.call_count == 2  # Initial preflight and exact DPS readback only.


@pytest.mark.parametrize("field,value", [
    ("principalId", "other"), ("roleDefinitionId", "/roles/other"), ("scope", NS_ID + "/child"),
    ("condition", "restricted"), ("conditionVersion", "2.0"),
])
def test_recovery_role_verification_checks_exact_assignment_fields(mocker, field, value):
    h = Harness(mocker)
    assignment = {"principalId": "principal", "roleDefinitionId": "/roles/" + LINK_ROLE_IDS["Contributor"], "scope": NS_ID}
    assignment[field] = value
    h.provider._rbac._invoke_json.return_value = [assignment]
    h.provider._rbac._invoke_json.side_effect = None
    assert not h.provider._rbac._assignment_exists("principal", "Contributor", NS_ID, strict=True)


def test_registered_adr_contributor_role_id_and_no_graph_or_caller_grants(mocker):
    h = Harness(mocker, identity="user")
    h.run()
    assert LINK_ROLE_IDS["Azure Device Registry Contributor"] == "a5c3590a-3a1a-4cd4-9648-ea0a32b15137"
    commands = [call.args[0] for call in h.provider._rbac._invoke_json.call_args_list]
    assert all(command.startswith("role assignment ") for command in commands)
    assert all("--fill-principal-name false" in command for command in commands if " list " in command)
    assert not any("Device Update Administrator" in command or "'caller'" in command or " ad " in command
                   for command in commands)


@pytest.mark.parametrize("kind", KINDS)
def test_namespace_lro_success_alone_is_not_endpoint_success(mocker, kind):
    h = Harness(mocker, kind)
    h.outcomes = ["success"]
    reads = []

    def get():
        if not h.patches:
            return
        reads.append(True)
        endpoint = h.namespace["properties"][KINDS[kind][0]]["endpoints"][kind]
        endpoint["linkingState"] = "InProgress" if len(reads) == 1 else "Succeeded"

    h.get_hook = get
    h.run(wait_sec=2)
    assert len(reads) == 2
    assert h.clock.delays == [2]
    assert len(h.patches) == 1


@pytest.mark.parametrize("status,code,recover", [
    (400, "AdrMiNotAuthorized", True), (None, "AdrMiNotAuthorized", True),
    (401, "AdrMiNotAuthorized", False), (403, "AdrMiNotAuthorized", False),
    (404, "AdrMiNotAuthorized", False), (500, "AdrMiNotAuthorized", False),
    (400, "OperationFailed", False), (None, "Unknown", False),
])
def test_sdk_http_failure_requires_exact_code_and_current_endpoint_evidence(mocker, status, code, recover):
    h = Harness(mocker)
    error = HttpResponseError("structured SDK error")
    error.status_code = status
    error.error = SimpleNamespace(code=code)

    def wait(poller, **kwargs):
        try:
            return h.wait(poller, **kwargs)
        except ADRResourceStateError:
            raise error

    h.provider._await_terminal.side_effect = wait
    if recover:
        h.run()
        assert len(h.patches) == 2
        assert h.clock.delays == [30]
    else:
        with pytest.raises(HttpResponseError) as caught:
            h.run()
        assert caught.value is error
        assert len(h.patches) == 1
        assert not h.clock.delays


def test_failed_lro_followed_by_unrelated_success_does_not_erase_service_error(mocker):
    h = Harness(mocker)

    def get():
        if h.patches:
            h.namespace["properties"]["provisioningState"] = "Succeeded"
            endpoint = h.namespace["properties"]["updating"]["endpoints"]["su"]
            endpoint["linkingState"] = "Succeeded"
            endpoint.pop("linkingError", None)

    h.get_hook = get
    with pytest.raises(ADRResourceStateError, match="AdrMiNotAuthorized"):
        h.run()
    assert len(h.patches) == 1
    assert not h.clock.delays


@pytest.mark.parametrize("outbound_user", [False, True])
def test_su_recovery_supports_mixed_inbound_and_outbound_identity_types(mocker, outbound_user):
    h = Harness(mocker, identity="system" if outbound_user else "user")
    if outbound_user:
        h.namespace["identity"]["userAssignedIdentities"] = {UAMI_ID: {"principalId": "namespace-user"}}
        h.namespace["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
    else:
        h.namespace["properties"].pop("outboundIdentity")
    h.run()
    assert h.created == [
        ("namespace-user" if outbound_user else "namespace-principal", "Contributor", SU_ID),
        ("target-principal" if outbound_user else "target-user", "Azure Device Registry Contributor", NS_ID),
    ]
    assert len(h.patches) == 2


@pytest.mark.parametrize("change", ["delete", "target", "identity", "state"])
def test_hub_recovery_requires_original_succeeded_dps_dependency(mocker, change):
    h = Harness(mocker, "hub")

    def mutate():
        if not h.patches:
            return
        endpoints = h.namespace["properties"]["provisioning"]["endpoints"]
        if change == "delete":
            endpoints.clear()
        elif change == "target":
            endpoints["dps"]["resourceId"] = DPS_ID + "-other"
        elif change == "identity":
            endpoints["dps"]["inboundCallerIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        else:
            endpoints["dps"]["linkingState"] = "InProgress"

    h.get_hook = mutate
    with pytest.raises(AzureResponseError):
        h.run()
    assert len(h.patches) == 1
    assert not h.clock.delays


def test_canary_resource_get_transport_error_is_not_a_mutation_authorization_error(mocker):
    h = Harness(mocker)
    _real_resource_pollers(h, mocker)
    error = HttpResponseError("Resource GET authorization failure")
    error.status_code = 400
    error.error = SimpleNamespace(code="AdrMiNotAuthorized")
    h.client.send_request.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        h.run(wait_sec=1)
    assert caught.value is error
    assert h.client.namespaces.get.call_count == 1
    assert len(h.patches) == 1


@pytest.mark.parametrize("scenario,expected_patches", [
    ("fresh-rejection", [0, 31, 91]),
    ("repeated-rejection", [0, 31, 91]),
    ("stale-get", [0, 31]),
    ("changed-target", [0, 31]),
    ("missing-role", [0, 31]),
])
def test_generated_sdk_recovery_distinguishes_fresh_patch_rejection_from_stale_get(
    mocker, mocked_response, scenario, expected_patches,
):
    """Drive the generated client, HTTP transport, real provider and base waiter."""
    h = Harness(mocker)
    h.provider._await_terminal = MethodType(LinkProvider._await_terminal, h.provider)
    patch_times, requests, bodies = [], [], []
    base_url = "https://centraluseuap.management.azure.com"
    url = base_url + NS_ID
    error = {"code": "AdrMiNotAuthorized", "message": "Namespace MI authorization has not propagated."}

    def respond(request):
        requests.append((request.method, h.clock.now))
        if request.method == "PATCH":
            patch_times.append(h.clock.now)
            bodies.append(json.loads(request.body))
            if len(patch_times) >= 2 and (
                scenario == "repeated-rejection" or len(patch_times) == 2 and scenario != "stale-get"
            ):
                if scenario == "changed-target":
                    h.namespace["properties"]["updating"]["endpoints"]["su"]["resourceId"] += "-other"
                elif scenario == "missing-role":
                    h.assignments.clear()
                return 400, {"Content-Type": "application/json"}, json.dumps({"error": error})
            succeeded = len(patch_times) == 3
            h.namespace["properties"]["provisioningState"] = "Succeeded" if succeeded else "Failed"
            endpoint = {**deepcopy(h.body), "linkingState": "Succeeded" if succeeded else "Failed"}
            if not succeeded:
                endpoint["linkingError"] = deepcopy(error)
            h.namespace["properties"]["updating"] = {"endpoints": {"su": endpoint}}
            return 202, {
                "Content-Type": "application/json",
                "Azure-AsyncOperation": "https://control-plane.prod.centraluseuap.iotadr.net/unused",
            }, json.dumps(h.namespace)
        return 200, {"Content-Type": "application/json"}, json.dumps(h.namespace)

    mocked_response.add_callback("PATCH", url, callback=respond)
    mocked_response.add_callback("GET", url, callback=respond)
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-unit-token", 4102444800)
    verify = mocker.spy(h.provider._rbac, "verify_many")
    with DeviceRegistryMgmtClient(credential, "sub", base_url=base_url, retry_total=0) as client:
        h.provider.client = client
        if scenario == "fresh-rejection":
            result = h.run(timeout_sec=120, wait_sec=1)
            assert result["properties"]["updating"]["endpoints"]["su"]["linkingState"] == "Succeeded"
            assert h.clock.now == 92
            assert h.clock.delays == [1, 30, 60, 1]
            assert verify.call_count == 4
        else:
            message = {
                "changed-target": "changed", "missing-role": "Cannot confirm",
                "repeated-rejection": "timed out", "stale-get": "timed out",
            }[scenario]
            with pytest.raises(AzureResponseError, match=message):
                h.run(timeout_sec=120, wait_sec=1)
            if scenario == "repeated-rejection":
                assert h.clock.delays == [1, 30, 60, 29]
                assert verify.call_count == 5
            if scenario in {"stale-get", "repeated-rejection"}:
                assert h.clock.now == 120
    assert patch_times == expected_patches
    assert bodies == [{"properties": {"updating": {"endpoints": {"su": h.body}}}}] * len(patch_times)
    assert len(h.created) == 2
    assert all(at < 120 for _, at in requests)
    assert len(mocked_response.calls) == len(requests)  # No async-status/Graph/extra requests.
