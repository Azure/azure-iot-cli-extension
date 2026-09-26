# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Read-only and fail-closed edges of the existing ADR recovery implementation."""

from copy import deepcopy
import logging
import shlex
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers import base
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery
from azext_iot.adr.rbac import LINK_ROLE_IDS, LinkRbacManager, _assignment_scope_applies, _scope_subscription
from azext_iot.tests.adr.test_adr_base_unit import _resource_poller
from azext_iot.tests.adr.test_adr_link_propagation_unit import Clock, Harness, KINDS, NS_ID
from azext_iot.tests.adr.test_adr_link_rbac_unit import NS_SCOPE, TARGET_SCOPE, _result


def _assert_initial_su_roles_only(harness):
    assert harness.created == [
        ("namespace-principal", "Contributor", KINDS["su"][2]),
        ("target-principal", "Azure Device Registry Contributor", NS_ID),
    ]
    assert len(harness.assignments) == 2


@pytest.mark.parametrize("invalid", ["outbound", "collection", "namespace-state", "success-with-error"])
def test_inspection_rejects_malformed_or_contradictory_state_without_writes(mocker, invalid):
    harness = Harness(mocker, action="update")
    verify = Mock()
    recovery = LinkRecovery(
        harness.provider, harness.namespace, "updating", "su", harness.body,
        LinkDeadline(clock=harness.clock.time, sleeper=harness.clock.sleep), verify,
    )
    namespace = deepcopy(harness.namespace)
    properties = namespace["properties"]
    if invalid == "outbound":
        properties["outboundIdentity"] = "SystemAssigned"
        message = "Malformed namespace outboundIdentity"
    elif invalid == "collection":
        properties["updating"] = []
        message = "Malformed namespace endpoint collection"
    elif invalid == "namespace-state":
        properties["provisioningState"] = 123
        message = "Malformed namespace provisioningState"
    else:
        properties["updating"]["endpoints"]["su"].update(
            linkingState="Succeeded", linkingError={"code": "AdrMiNotAuthorized"},
        )
        message = "Succeeded with a linkingError"
    original = deepcopy(namespace)

    with pytest.raises(AzureResponseError, match=message):
        recovery.inspect(namespace)

    assert namespace == original
    verify.assert_not_called()
    harness.client.namespaces.begin_update.assert_not_called()
    harness.client.namespaces.get.assert_not_called()
    assert not harness.created and not harness.clock.delays


def test_no_wait_preserves_structured_submission_failure_without_observation(mocker):
    harness = Harness(mocker)
    error = base.ADRResourceStateError("Original submission rejected", deepcopy(harness.namespace))
    harness.submit_error = error

    with pytest.raises(base.ADRResourceStateError) as raised:
        harness.run(no_wait=True)

    assert raised.value is error
    harness.client.namespaces.begin_update.assert_called_once()
    harness.provider._await_terminal.assert_not_called()
    assert harness.client.namespaces.get.call_count == 1  # Preliminary discovery only.
    assert not harness.patches and not harness.clock.delays
    _assert_initial_su_roles_only(harness)


def test_recovery_does_not_replace_original_failure_with_unrelated_failed_read(mocker):
    harness = Harness(mocker)

    def change_error_after_submission():
        if harness.patches:
            harness.namespace["properties"]["updating"]["endpoints"]["su"]["linkingError"]["code"] = "UnrelatedFailure"

    harness.get_hook = change_error_after_submission
    with pytest.raises(base.ADRResourceStateError, match="AdrMiNotAuthorized") as raised:
        harness.run()

    assert raised.value.body["properties"]["updating"]["endpoints"]["su"]["linkingError"]["code"] == "AdrMiNotAuthorized"
    assert harness.namespace["properties"]["updating"]["endpoints"]["su"]["linkingError"]["code"] == "UnrelatedFailure"
    assert len(harness.patches) == 1 and not harness.clock.delays
    _assert_initial_su_roles_only(harness)


@pytest.mark.parametrize("location", ["namespace", "properties", "endpoint"])
def test_additional_service_error_stops_authorization_recovery_before_backoff(mocker, location):
    harness = Harness(mocker)
    extra = {"code": "AdditionalFailure", "message": "Do not retry this mutation"}

    def add_error():
        if harness.patches:
            containers = {
                "namespace": harness.namespace,
                "properties": harness.namespace["properties"],
                "endpoint": harness.namespace["properties"]["updating"]["endpoints"]["su"],
            }
            containers[location]["error"] = deepcopy(extra)

    harness.get_hook = add_error
    with pytest.raises(base.ADRResourceStateError, match="additional service error.*AdditionalFailure") as raised:
        harness.run()

    assert raised.value.body == harness.namespace
    assert len(harness.patches) == 1 and not harness.clock.delays
    _assert_initial_su_roles_only(harness)


@pytest.mark.parametrize("collection", [None, {"endpoints": None}])
def test_null_unrelated_endpoint_collections_do_not_block_bounded_recovery(mocker, collection):
    harness = Harness(mocker)

    def unrelated_collection():
        if harness.patches:
            harness.namespace["properties"]["messaging"] = deepcopy(collection)

    harness.get_hook = unrelated_collection
    result = harness.run(timeout_sec=31)

    assert result["properties"]["updating"]["endpoints"]["su"]["linkingState"] == "Succeeded"
    assert result["properties"]["messaging"] == collection
    assert harness.patches == [{"updating": {"endpoints": {"su": harness.body}}}] * 2
    assert harness.clock.delays == [30] and harness.clock.now == 30
    _assert_initial_su_roles_only(harness)


@pytest.mark.parametrize("collection", ["invalid", {"endpoints": []}])
def test_malformed_unrelated_endpoint_collections_prevent_retry_patch(mocker, collection):
    # DPS is inspected before messaging, so its real service-error detail is
    # retained before recovery validates the unrelated malformed collection.
    harness = Harness(mocker, kind="dps")

    def unrelated_collection():
        if harness.patches:
            harness.namespace["properties"]["messaging"] = deepcopy(collection)

    harness.get_hook = unrelated_collection
    with pytest.raises(AzureResponseError, match="Malformed namespace endpoint collection"):
        harness.run()

    assert harness.namespace["properties"]["messaging"] == collection
    assert len(harness.patches) == 1 and not harness.clock.delays
    assert harness.created == [
        ("namespace-principal", "Contributor", KINDS["dps"][2]),
        ("target-principal", "Contributor", NS_ID),
        ("namespace-principal", "Azure Device Registry Administrator", NS_ID),
    ]
    assert len(harness.assignments) == 3


def test_json_object_allowlist_accepts_supported_properties_without_mutation():
    body = {"required": {"nested": [1, None]}, "optional": False}
    original = deepcopy(body)
    result = base.parse_json_object(
        body, "--body", allowed_keys=frozenset({"required", "optional"}), required_keys=frozenset({"required"}),
    )
    assert result is body and body == original


@pytest.mark.parametrize("timeout", [3, 5])
def test_bounded_sdk_wait_checks_pending_poller_again_and_never_returns_timeout_none(
    fixture_adr_provider, monkeypatch, timeout,
):
    monkeypatch.setattr(base, "POLL_PROVISIONING_STATE_WORKAROUND", False)
    clock = Clock()
    deadline = LinkDeadline(timeout=timeout, interval=2, clock=clock.time, sleeper=clock.sleep)
    result = {"properties": {"provisioningState": "Succeeded"}}
    poller = SimpleNamespace(done=lambda: clock.now >= 4, result=Mock(return_value=result))
    kwargs = {"deadline_guard": deadline.remaining, "sleeper": deadline.pause, "wait_sec": 2}

    if timeout == 5:
        assert fixture_adr_provider._await_terminal(poller, **kwargs) is result
        assert clock.delays == [2, 2]
        poller.result.assert_called_once_with()
    else:
        with pytest.raises(AzureResponseError, match="timed out after 3 seconds"):
            fixture_adr_provider._await_terminal(poller, **kwargs)
        assert clock.delays == [2, 1] and clock.now == 3
        poller.result.assert_not_called()
    fixture_adr_provider.client.send_request.assert_not_called()


@pytest.mark.parametrize("expired", [False, True])
def test_inline_resource_result_checks_deadline_before_observing_success(fixture_adr_provider, expired):
    clock = Clock()
    deadline = LinkDeadline(timeout=1, clock=clock.time, sleeper=clock.sleep)
    body = {"properties": {"provisioningState": "Succeeded"}}
    poller = _resource_poller(status_code=200, body=body)
    observer = Mock()
    if expired:
        clock.now = 1
        with pytest.raises(AzureResponseError, match="timed out"):
            fixture_adr_provider._poll_provisioning_state(
                poller, deadline_guard=deadline.remaining, resource_observer=observer,
            )
        observer.assert_not_called()
    else:
        assert fixture_adr_provider._poll_provisioning_state(
            poller, deadline_guard=deadline.remaining, resource_observer=observer,
        ) is body
        observer.assert_called_once_with(body)
    poller.result.assert_not_called()
    fixture_adr_provider.client.send_request.assert_not_called()
    assert not clock.delays


def test_guarded_resource_read_rejects_non_error_http_redirect_status(fixture_adr_provider):
    # raise_for_status does not normally raise for 3xx; that is still not a
    # valid resource observation and must never authorize a recovery mutation.
    response = Mock(status_code=304, reason="Not Modified", headers={})
    response.raise_for_status.return_value = None
    fixture_adr_provider.client.send_request.return_value = response
    clock = Clock()
    deadline = LinkDeadline(timeout=3, clock=clock.time, sleeper=clock.sleep)

    with pytest.raises(HttpResponseError, match="Unexpected resource-status HTTP 304") as raised:
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(), wait_sec=1, clock=clock.time, sleeper=clock.sleep, deadline_guard=deadline.remaining,
        )

    assert raised.value.adr_resource_read_failure is True
    assert raised.value.response is response
    response.raise_for_status.assert_called_once_with()
    assert fixture_adr_provider.client.send_request.call_count == 1 and clock.delays == [1]


def test_unguarded_resource_transport_error_is_preserved_without_reclassification(fixture_adr_provider):
    error = HttpResponseError("Original resource GET transport failure")
    fixture_adr_provider.client.send_request.side_effect = error
    clock = Clock()

    with pytest.raises(HttpResponseError) as raised:
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(), wait_sec=1, clock=clock.time, sleeper=clock.sleep,
        )

    assert raised.value is error and not hasattr(error, "adr_resource_read_failure")
    assert fixture_adr_provider.client.send_request.call_count == 1 and clock.delays == [1]
    request = fixture_adr_provider.client.send_request.call_args.args[0]
    assert request.method == "GET" and request.url == "https://management.azure.com/resource"


@pytest.mark.parametrize("assignment_scope,scope", [("", NS_SCOPE), (NS_SCOPE, ""), (None, NS_SCOPE)])
def test_empty_scope_never_proves_an_inherited_assignment(assignment_scope, scope):
    assert not _assignment_scope_applies(assignment_scope, scope, inherited_at_scope=True)


@pytest.mark.parametrize("assignments", [{}, [None], [{"scope": NS_SCOPE}, "invalid"]])
def test_strict_assignment_verification_rejects_malformed_list_before_any_write(assignments):
    cli = Mock()
    cli.invoke.return_value = _result(assignments)
    manager = LinkRbacManager(Mock(), cli=cli)
    with pytest.raises(AzureResponseError, match="Malformed role-assignment response"):
        manager._assignment_exists("namespace-principal", "Contributor", NS_SCOPE, strict=True)
    cli.invoke.assert_called_once()
    args = shlex.split(cli.invoke.call_args.args[0])
    assert args[:3] == ["role", "assignment", "list"]
    assert args[args.index("--scope") + 1] == NS_SCOPE
    assert "--include-inherited" in args and "--fill-principal-name" in args


def test_hub_recovery_without_inbound_identity_only_verifies_two_outbound_roles():
    cli = Mock()
    requests = []

    def invoke(command, **kwargs):
        args = shlex.split(command)
        assert args[:3] == ["role", "assignment", "list"]
        role = args[args.index("--role") + 1]
        principal = args[args.index("--assignee-object-id") + 1]
        scope = args[args.index("--scope") + 1]
        requests.append((principal, role, scope))
        assert kwargs == {"subscription": "sub"}
        return _result([{
            "scope": scope, "principalId": principal,
            "roleDefinitionId": "/providers/Microsoft.Authorization/roleDefinitions/" + LINK_ROLE_IDS[role],
        }])

    cli.invoke.side_effect = invoke
    manager = LinkRbacManager(Mock(), cli=cli)
    guard = Mock()
    manager.verify_many([{
        "link_type": "hub", "namespace_principal_id": "namespace-principal", "linked_principal_id": None,
        "namespace_scope": NS_SCOPE, "target_scope": TARGET_SCOPE,
    }], guard=guard)
    assert requests == [
        ("namespace-principal", "Contributor", TARGET_SCOPE),
        ("namespace-principal", "IoT Hub Data Contributor", TARGET_SCOPE),
    ]
    assert guard.call_count == 4


def test_subscriptionless_assignment_summary_does_not_invent_subscription():
    scope = "/providers/Microsoft.Management/managementGroups/parent"
    assignment = ("namespace-principal", "Contributor", scope)
    assert _scope_subscription(scope) is None
    assert LinkRbacManager._assignment_summary([assignment], {assignment: "required service role"}) == (
        f"- required service role; principalId=namespace-principal; scope={scope}"
    )


@pytest.mark.parametrize("outcome", ["empty", "visible", "timeout"])
def test_assignment_visibility_has_only_early_success_or_bounded_timeout_exits(outcome):
    clock = Clock()
    cli = Mock()
    cli.invoke.return_value = _result([{"id": "visible"}] if outcome == "visible" else [])
    manager = LinkRbacManager(Mock(), cli=cli, clock=clock.time, sleeper=clock.sleep, propagation_timeout=3)
    assignment = ("namespace-principal", "Contributor", TARGET_SCOPE)
    assignments = [] if outcome == "empty" else [assignment]
    original = list(assignments)

    if outcome == "timeout":
        with pytest.raises(AzureResponseError, match="No namespace mutation was submitted") as raised:
            manager._wait_for_assignments(assignments)
        assert clock.delays == [2, 1] and clock.now == 3
        assert "--role 'Contributor'" in str(raised.value)
        assert f"--scope '{TARGET_SCOPE}'" in str(raised.value)
        assert cli.invoke.call_count == 3
    else:
        assert manager._wait_for_assignments(assignments) is None
        assert not clock.delays
        assert cli.invoke.call_count == (0 if outcome == "empty" else 1)
    assert assignments == original
    assert all(call.args[0].startswith("role assignment list ") for call in cli.invoke.call_args_list)


def test_all_assignment_creations_racing_with_another_actor_need_no_visibility_wait(mocker, caplog):
    caplog.set_level(logging.WARNING, logger="azext_iot.adr.rbac")
    cli = Mock()
    clock = Clock()
    manager = LinkRbacManager(Mock(), cli=cli, clock=clock.time, sleeper=clock.sleep)
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="offline-caller")
    mocker.patch.object(manager, "_caller_can_assign", return_value=True)
    token = mocker.patch.object(manager, "_access_token", side_effect=AssertionError("Token lookup is forbidden"))
    raced, reads = [], []

    def invoke(command, **kwargs):
        args = shlex.split(command)
        assignment = tuple(args[args.index(option) + 1] for option in ("--assignee-object-id", "--role", "--scope"))
        assert kwargs == {"subscription": "sub"}
        if args[:3] == ["role", "assignment", "create"]:
            assert assignment not in raced
            assert args[args.index("--assignee-principal-type") + 1] == "ServicePrincipal"
            raced.append(assignment)
            raise AzureResponseError("Another actor created this exact assignment")
        assert args[:3] == ["role", "assignment", "list"]
        reads.append(assignment)
        return _result([{"id": "existing-assignment"}] if assignment in raced else [])

    cli.invoke.side_effect = invoke
    manager.ensure(
        "dps", NS_SCOPE, TARGET_SCOPE, "namespace-principal", "dps-principal",
        namespace_system_principal_id="namespace-system",
    )

    assert raced == [
        ("namespace-principal", "Contributor", TARGET_SCOPE),
        ("dps-principal", "Contributor", NS_SCOPE),
        ("namespace-system", "Azure Device Registry Administrator", NS_SCOPE),
    ]
    assert reads == raced * 2  # Initial preflight then one race verification per role.
    assert not clock.delays
    assert "Completed these role-assignment creation requests" not in caplog.text
    token.assert_not_called()
