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
from azure.core.exceptions import ServiceRequestError, ServiceResponseError

from azext_iot.adr.providers import base
from azext_iot.adr.providers.link_recovery import (
    TRANSPORT_RETRY_DELAY, LinkDeadline, LinkRecovery,
)
from azext_iot.adr.providers.wait import DEFAULT_WAIT_INTERVAL
from azext_iot.adr.rbac import LINK_ROLE_IDS, LinkRbacManager, _assignment_scope_applies, _scope_subscription
from azext_iot.tests.adr.test_adr_link_propagation_unit import Clock, Harness, KINDS, NS_ID
from azext_iot.tests.adr.test_adr_link_rbac_unit import NS_SCOPE, TARGET_SCOPE, _result


def _assert_initial_dps_roles_only(harness):
    assert harness.created == [
        ("namespace-principal", "Contributor", KINDS["dps"][2]),
        ("target-principal", "Contributor", NS_ID),
        ("namespace-principal", "Azure Device Registry Administrator", NS_ID),
    ]
    assert len(harness.assignments) == 3


@pytest.mark.parametrize("invalid", ["outbound", "collection", "namespace-state", "success-with-error"])
def test_inspection_rejects_malformed_or_contradictory_state_without_writes(mocker, invalid):
    harness = Harness(mocker, action="update")
    verify = Mock()
    recovery = LinkRecovery(
        harness.provider, harness.namespace, "provisioning", "dps", harness.body,
        LinkDeadline(clock=harness.clock.time, sleeper=harness.clock.sleep), verify,
    )
    namespace = deepcopy(harness.namespace)
    properties = namespace["properties"]
    if invalid == "outbound":
        properties["outboundIdentity"] = "SystemAssigned"
        message = "Malformed namespace outboundIdentity"
    elif invalid == "collection":
        properties["provisioning"] = []
        message = "Malformed namespace endpoint collection"
    elif invalid == "namespace-state":
        properties["provisioningState"] = 123
        message = "Malformed namespace provisioningState"
    else:
        properties["provisioning"]["endpoints"]["dps"].update(
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
    _assert_initial_dps_roles_only(harness)


def test_recovery_does_not_replace_original_failure_with_unrelated_failed_read(mocker):
    harness = Harness(mocker)

    def change_error_after_submission():
        if harness.patches:
            harness.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingError"]["code"] = "UnrelatedFailure"

    harness.get_hook = change_error_after_submission
    with pytest.raises(base.ADRResourceStateError, match="AdrMiNotAuthorized") as raised:
        harness.run()

    assert raised.value.body["properties"]["provisioning"]["endpoints"]["dps"]["linkingError"]["code"] == "AdrMiNotAuthorized"
    assert harness.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingError"]["code"] == "UnrelatedFailure"
    assert len(harness.patches) == 1 and not harness.clock.delays
    _assert_initial_dps_roles_only(harness)


@pytest.mark.parametrize("location", ["namespace", "properties", "endpoint"])
def test_additional_service_error_stops_authorization_recovery_before_backoff(mocker, location):
    harness = Harness(mocker)
    extra = {"code": "AdditionalFailure", "message": "Do not retry this mutation"}

    def add_error():
        if harness.patches:
            containers = {
                "namespace": harness.namespace,
                "properties": harness.namespace["properties"],
                "endpoint": harness.namespace["properties"]["provisioning"]["endpoints"]["dps"],
            }
            containers[location]["error"] = deepcopy(extra)

    harness.get_hook = add_error
    with pytest.raises(base.ADRResourceStateError, match="additional service error.*AdditionalFailure") as raised:
        harness.run()

    assert raised.value.body == harness.namespace
    assert len(harness.patches) == 1 and not harness.clock.delays
    _assert_initial_dps_roles_only(harness)


@pytest.mark.parametrize("collection", [None, {"endpoints": None}])
def test_null_unrelated_endpoint_collections_do_not_block_bounded_recovery(mocker, collection):
    harness = Harness(mocker)

    def unrelated_collection():
        if harness.patches:
            harness.namespace["properties"]["messaging"] = deepcopy(collection)

    harness.get_hook = unrelated_collection
    result = harness.run(timeout_sec=31)

    assert result["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] == "Succeeded"
    assert result["properties"]["messaging"] == collection
    assert harness.patches == [{"provisioning": {"endpoints": {"dps": harness.body}}}] * 2
    assert harness.clock.delays == [30] and harness.clock.now == 30
    _assert_initial_dps_roles_only(harness)


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
    fixture_adr_provider, timeout,
):
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


@pytest.mark.parametrize("stage", ["operation", "namespace-read"])
def test_link_failure_reports_the_target_endpoint_not_an_older_failed_one(mocker, stage):
    harness = Harness(mocker, kind="dps")
    harness.namespace["properties"]["messaging"] = {"endpoints": {"primary-hub": {
        "endpointType": KINDS["hub"][1], "resourceId": KINDS["hub"][2], "linkingState": "Failed",
        "linkingError": {"code": "LinkInitiateFailed", "message": "stale hub failure"},
    }}}
    submit = harness.submit

    def fail_target(**kwargs):
        submit(**kwargs)
        harness.namespace["properties"]["provisioningState"] = "Failed"
        harness.namespace["properties"]["provisioning"]["endpoints"]["dps"].update(
            linkingState="Failed", linkingError={"code": "LinkOrphaned", "message": "orphaned"},
        )
        body = deepcopy(harness.namespace)
        if stage == "namespace-read":
            body["properties"]["provisioningState"] = "Succeeded"
        return SimpleNamespace(done=lambda: True, result=lambda: body)

    harness.client.namespaces.begin_update.side_effect = fail_target
    del harness.provider._await_terminal  # exercise the real operation-failure formatter

    with pytest.raises(base.ADRResourceStateError) as raised:
        harness.run()

    assert "endpoint 'dps': LinkOrphaned: orphaned." in str(raised.value)
    assert "stale hub failure" not in str(raised.value)
    assert len(harness.patches) == 1


def _connection_reset():
    return ServiceResponseError("('Connection aborted.', RemoteDisconnected('Remote end closed connection'))")


def _fail_submits(harness, count, landed=False):
    """Fail the first ``count`` PATCHes without a response, optionally after they took effect."""
    submit = harness.submit

    def flaky(**kwargs):
        if len(harness.client.namespaces.begin_update.call_args_list) <= count:
            if landed:
                submit(**kwargs)
            raise _connection_reset()
        return submit(**kwargs)

    harness.client.namespaces.begin_update.side_effect = flaky


def _on_nth_sleep(harness, n, action):
    def hook():
        if len(harness.clock.delays) == n:
            action()

    harness.clock.on_sleep = hook


@pytest.mark.parametrize("kind", ["dps", "hub", "dps"])
@pytest.mark.parametrize("action", ["add", "update"])
def test_connection_reset_on_an_unchanged_namespace_is_never_resubmitted(mocker, kind, action):
    harness = Harness(mocker, kind=kind, action=action)
    _fail_submits(harness, 1)

    with pytest.raises(AzureResponseError, match="outcome is unknown; the namespace shows no change yet") as raised:
        harness.run()

    assert f"iot adr ns link {kind} show" in str(raised.value)
    harness.client.namespaces.begin_update.assert_called_once()
    assert harness.clock.delays == [TRANSPORT_RETRY_DELAY]


def test_applied_patch_connection_reset_is_tracked_without_a_second_write(mocker):
    harness = Harness(mocker)
    _fail_submits(harness, 1, landed=True)

    def finish():
        harness.namespace["properties"]["provisioningState"] = "Succeeded"
        harness.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] = "Succeeded"

    _on_nth_sleep(harness, 2, finish)

    result = harness.run()

    assert result["properties"]["provisioning"]["endpoints"]["dps"]["linkingState"] == "Succeeded"
    harness.client.namespaces.begin_update.assert_called_once()
    harness.provider._await_terminal.assert_not_called()
    assert harness.clock.delays == [TRANSPORT_RETRY_DELAY, DEFAULT_WAIT_INTERVAL]


def test_tracked_submission_reports_an_authorization_failure_without_another_write(mocker, caplog):
    harness = Harness(mocker)
    harness.outcomes = ["success"]
    _fail_submits(harness, 1, landed=True)

    def fail_authorization():
        harness.namespace["properties"]["provisioningState"] = "Failed"
        harness.namespace["properties"]["provisioning"]["endpoints"]["dps"].update(
            linkingState="Failed", linkingError={"code": "AdrMiNotAuthorized", "message": "not authorized"},
        )

    _on_nth_sleep(harness, 1, fail_authorization)

    with caplog.at_level(logging.WARNING), pytest.raises(base.ADRResourceStateError, match="AdrMiNotAuthorized"):
        harness.run()

    harness.client.namespaces.begin_update.assert_called_once()
    assert harness.clock.delays == [TRANSPORT_RETRY_DELAY]
    assert "No rollback was attempted" in caplog.text


def test_connection_reset_on_a_failed_endpoint_with_only_a_tag_change_reports_unknown_outcome(mocker):
    harness = Harness(mocker, action="update")
    harness.namespace["properties"]["provisioningState"] = "Failed"
    harness.namespace["properties"]["provisioning"]["endpoints"]["dps"].update(
        linkingState="Failed", linkingError={"code": "AdrMiNotAuthorized", "message": "not authorized"},
    )
    _fail_submits(harness, 1)
    _on_nth_sleep(harness, 1, lambda: harness.namespace.update(tags={"changed": "elsewhere"}))

    with pytest.raises(AzureResponseError, match="outcome is unknown") as raised:
        harness.run()

    assert "shows no change yet" not in str(raised.value)
    harness.client.namespaces.begin_update.assert_called_once()
    assert harness.clock.delays == [TRANSPORT_RETRY_DELAY]


def test_recovery_resubmission_reset_compares_against_the_recovery_snapshot(mocker):
    harness = Harness(mocker)
    submit = harness.submit

    def reset_second(**kwargs):
        if harness.client.namespaces.begin_update.call_count == 2:
            raise _connection_reset()
        return submit(**kwargs)

    harness.client.namespaces.begin_update.side_effect = reset_second

    # The failed endpoint differs from the pre-add read but equals the recovery baseline.
    with pytest.raises(AzureResponseError, match="shows no change yet"):
        harness.run()

    assert harness.client.namespaces.begin_update.call_count == 2
    assert harness.clock.delays == [30, TRANSPORT_RETRY_DELAY]


@pytest.mark.parametrize("error_type", [ServiceRequestError, ServiceResponseError])
def test_either_transport_error_reports_unknown_outcome_with_its_cause(mocker, caplog, error_type):
    harness = Harness(mocker)
    harness.client.namespaces.begin_update.side_effect = error_type("connection reset")

    with caplog.at_level(logging.WARNING), pytest.raises(AzureResponseError, match="outcome is unknown") as raised:
        harness.run()

    assert isinstance(raised.value.__cause__, error_type)
    harness.client.namespaces.begin_update.assert_called_once()
    assert "got no service response" in caplog.text
    assert "No rollback was attempted" in caplog.text


@pytest.mark.parametrize("no_wait", [False, True])
def test_connection_reset_with_an_unrelated_namespace_change_reports_unknown_outcome(mocker, no_wait):
    harness = Harness(mocker)
    _fail_submits(harness, 1)
    _on_nth_sleep(harness, 1, lambda: harness.namespace.update(tags={"changed": "elsewhere"}))

    with pytest.raises(AzureResponseError, match="outcome is unknown") as raised:
        harness.run(no_wait=no_wait)

    assert "iot adr ns link dps show" in str(raised.value)
    harness.client.namespaces.begin_update.assert_called_once()
    harness.provider._await_terminal.assert_not_called()


@pytest.mark.parametrize("read_error", [AzureResponseError("read denied"), ServiceResponseError("read reset")])
def test_connection_reset_without_a_confirming_read_does_not_resubmit(mocker, read_error):
    harness = Harness(mocker)
    _fail_submits(harness, 1)
    reads = harness.client.namespaces.get.side_effect

    def fail_after_reset(**kwargs):
        if harness.client.namespaces.begin_update.called:
            raise read_error
        return reads(**kwargs)

    harness.client.namespaces.get.side_effect = fail_after_reset

    with pytest.raises(AzureResponseError, match="could not be read to confirm") as raised:
        harness.run()

    assert isinstance(raised.value.__cause__, ServiceResponseError)
    harness.client.namespaces.begin_update.assert_called_once()


@pytest.mark.parametrize("landed", [False, True])
def test_no_wait_connection_reset_is_never_resubmitted_or_tracked(mocker, landed):
    harness = Harness(mocker)
    _fail_submits(harness, 1, landed=landed)

    with pytest.raises(AzureResponseError, match="outcome is unknown"):
        harness.run(no_wait=True)

    harness.client.namespaces.begin_update.assert_called_once()
    harness.provider._await_terminal.assert_not_called()


def test_tracked_submission_ignores_stale_pre_submit_failure_reads(mocker):
    harness = Harness(mocker, action="update")
    harness.namespace["properties"]["provisioningState"] = "Failed"
    harness.namespace["properties"]["provisioning"]["endpoints"]["dps"]["linkingError"] = {
        "code": "AdrMiNotAuthorized", "message": "not authorized",
    }
    before = deepcopy(harness.namespace)
    _fail_submits(harness, 1, landed=True)
    _on_nth_sleep(harness, 2, lambda: setattr(harness, "namespace", deepcopy(before)))

    with pytest.raises(AzureResponseError, match="timed out"):
        harness.run(timeout_sec=100)

    harness.client.namespaces.begin_update.assert_called_once()
    assert harness.clock.delays[0] == TRANSPORT_RETRY_DELAY


@pytest.mark.parametrize(
    "namespace",
    [
        None,
        {"properties": []},
        {"properties": {"provisioningState": "Succeeded", "provisioning": []}},
        {"properties": {"provisioningState": "Succeeded", "provisioning": {"endpoints": []}}},
        {"properties": {"provisioningState": "Succeeded", "provisioning": {"endpoints": {"dps": "invalid"}}}},
        {"properties": {"provisioningState": "Succeeded", "provisioning": {"endpoints": {"other": {}}}}},
    ],
)
def test_submission_evidence_ignores_malformed_or_missing_endpoints(mocker, namespace):
    harness = Harness(mocker)
    recovery = LinkRecovery(
        harness.provider, harness.namespace, "provisioning", "dps", harness.body,
        LinkDeadline(clock=harness.clock.time, sleeper=harness.clock.sleep), Mock(),
    )

    assert recovery._shows_submission(namespace) is False
