# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline reproductions of integration investigations 5, 7 and 8."""

from copy import deepcopy
import json
import logging
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.cli.core.commands.arm import show_exception_handler
from azure.cli.testsdk.base import ExecutionResult
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError, ServiceResponseError

from azext_iot.adr.providers.group import GroupProvider
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr import _readiness as readiness
from azext_iot.tests.adr import test_adr_group_int as groups
from azext_iot.tests.adr.test_adr_group_unit import _refresh_error
from azext_iot.tests.adr.test_adr_link_propagation_unit import Harness, NS_ID
from azext_iot.tests.adr.test_adr_link_unit import UAMI_ID
from azext_iot.tests.adr.test_adr_readiness_unit import Clock, _http


GROUP_SHOW = "iot adr ns group show --namespace ns -g rg -n group"
GROUP_ID = NS_ID + "/groups/group"
ARM = "https://centraluseuap.management.azure.com"


@pytest.fixture
def wrapper_scenario(mocker):
    # Exercise the *real* ARM show handler and testsdk wrapper, but never emit
    # telemetry or use a profile/credential/network.
    mocker.patch.object(ResourceNotFoundError, "print_error")
    mocker.patch.object(ResourceNotFoundError, "send_telemetry")
    cli = Mock(data={"subscription_id": "sub"})
    return SimpleNamespace(cli_ctx=cli, cmd=lambda text: ExecutionResult(cli, text))


def _outside_except(error):
    # Match Azure CLI command error handling: the exception is retained, but
    # its handler need not run inside the HTTP except block.
    show_exception_handler(error)


@pytest.mark.parametrize("primary_type", [AssertionError, ClientAuthenticationError, ServiceRequestError])
def test_real_arm_show_exit_retains_exact_sdk_404_during_cleanup(
    wrapper_scenario, mocked_response, primary_type,
):
    missing = {"error": {"code": "ResourceNotFound", "message": "owned resource absent"}}
    mocked_response.add("GET", ARM + GROUP_ID, status=404, json=missing)
    mocked_response.add("GET", ARM + NS_ID, status=404, json=missing)
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline", 4102444800)))
    clock = Clock()
    primary = primary_type("original refresh assertion")
    errors = []
    with DeviceRegistryMgmtClient(credential, "sub", base_url=ARM, retry_total=0) as client:
        def invoke(command, **_):
            try:
                if "group" in command:
                    client.groups.get("rg", "ns", "group")
                else:
                    client.namespaces.get("rg", "ns")
            except HttpResponseError as error:
                errors.append(error)
            _outside_except(errors[-1])

        wrapper_scenario.cli_ctx.invoke.side_effect = invoke
        with pytest.raises(primary_type) as raised:
            try:
                raise primary
            finally:
                readiness.delete_test_namespace(
                    wrapper_scenario, "ns", "rg", groups=("group",), clock=clock, sleeper=clock.sleep,
                )
        assert raised.value is primary
    assert len(errors) == 2
    assert all(error.response.status_code == 404 for error in errors)
    assert [(call.request.method, call.request.url.split("?")[0]) for call in mocked_response.calls] == [
        ("GET", ARM + GROUP_ID), ("GET", ARM + NS_ID),
    ]
    assert not clock.sleeps


@pytest.mark.parametrize("url,method,status,code", [
    ("https://foreign.invalid" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    ("https://management.azure.com.evil.invalid" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID.replace("/sub/", "/foreign/"), "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID + "-foreign", "GET", 404, "ResourceNotFound"),
    (ARM + "/prefix" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM.replace("https:", "http:") + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID, "POST", 404, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 403, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 502, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 404, "AuthorizationFailed"),
])
def test_real_show_wrapper_rejects_foreign_http_evidence(wrapper_scenario, url, method, status, code):
    original = _http(status, code, method, resource_id=GROUP_ID)
    original.response.request.url = url
    wrapper_scenario.cli_ctx.invoke.side_effect = lambda *_args, **_kwargs: _outside_except(original)
    with pytest.raises((SystemExit, AssertionError)):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)
    wrapper_scenario.cli_ctx.invoke.assert_called_once()


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError, ServiceResponseError])
def test_authentication_and_transport_evidence_is_never_404(wrapper_scenario, error_type):
    error = _http(error_type=error_type, resource_id=GROUP_ID)
    wrapper_scenario.cli_ctx.invoke.side_effect = lambda *_args, **_kwargs: _outside_except(error)
    with pytest.raises(SystemExit):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError, ServiceResponseError])
@pytest.mark.parametrize("suppressed", [False, True])
def test_handler_traceback_never_discards_new_lookup_errors(wrapper_scenario, error_type, suppressed):
    missing = _http(resource_id=GROUP_ID)
    lookup_error = error_type("new lookup failure")

    def invoke(*_args, **_kwargs):
        try:
            raise lookup_error
        except error_type:
            try:
                _outside_except(missing)
            except SystemExit as error:
                if suppressed:
                    raise error from None
                raise

    wrapper_scenario.cli_ctx.invoke.side_effect = invoke
    with pytest.raises(SystemExit) as raised:
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)
    assert raised.value.__context__ is lookup_error


def test_real_handler_with_non_http_argument_and_bare_exit_cannot_prove_absence(wrapper_scenario):
    for error in (SimpleNamespace(status_code=404, message="missing"), SystemExit(3)):
        def invoke(*_args, **_kwargs):
            if isinstance(error, SystemExit):
                raise error
            _outside_except(error)
        wrapper_scenario.cli_ctx.invoke.side_effect = invoke
        with pytest.raises(SystemExit):
            readiness._get_resource(wrapper_scenario, GROUP_SHOW)


@pytest.mark.parametrize("conflict", ["cause", "status", "response"])
def test_exit_metadata_cannot_override_contradictory_lookup_evidence(wrapper_scenario, conflict):
    def invoke(*_args, **_kwargs):
        try:
            _outside_except(_http(resource_id=GROUP_ID))
        except SystemExit as error:
            if conflict == "cause":
                raise error from ClientAuthenticationError("lookup denied")
            if conflict == "status":
                error.status_code = 403
            else:
                error.response = SimpleNamespace(status_code=403)
            raise
    wrapper_scenario.cli_ctx.invoke.side_effect = invoke
    with pytest.raises(SystemExit):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)


def _rotation(mocker):
    harness = Harness(mocker, "hub", action="update")
    endpoint = harness.namespace["properties"]["messaging"]["endpoints"]["hub"]
    endpoint.update(
        linkingState="Succeeded",
        inboundCallerIdentity={"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
    )
    return harness


@pytest.mark.parametrize("view", ["converge", "stale-failure", "timeout", "terminal-old", "foreign", "regression"])
def test_real_sdk_rotation_polls_only_exact_pending_preupdate_projection(mocker, mocked_response, view):
    harness = _rotation(mocker)
    harness.provider._await_terminal = MethodType(LinkProvider._await_terminal, harness.provider)
    old = deepcopy(harness.namespace)
    desired = deepcopy(old)
    desired["properties"]["messaging"]["endpoints"]["hub"] = {
        **deepcopy(harness.body), "linkingState": "Succeeded",
    }
    pending = deepcopy(old)
    pending["properties"]["provisioningState"] = "Updating"
    if view == "stale-failure":
        pending["properties"]["messaging"]["endpoints"]["hub"].update(
            linkingState="Failed", linkingError={"code": "AdrMiNotAuthorized"},
        )
    if view == "foreign":
        pending["properties"]["messaging"]["endpoints"]["hub"]["resourceId"] += "-foreign"
    if view == "terminal-old":
        pending["properties"]["provisioningState"] = "Succeeded"
    projected = deepcopy(desired)
    projected["properties"]["provisioningState"] = "Updating"
    reads = [pending, projected, desired]
    if view == "regression":
        reads = [projected, pending]
    writes, gets = [], []

    def respond(request):
        if request.method == "PATCH":
            writes.append(json.loads(request.body))
            return 202, {
                "Content-Type": "application/json",
                "Azure-AsyncOperation": "https://foreign.invalid/must-not-poll",
            }, json.dumps(pending)
        gets.append(request.url)
        body = old if not writes else (pending if view == "timeout" else reads.pop(0) if reads else desired)
        return 200, {"Content-Type": "application/json"}, json.dumps(body)

    mocked_response.add_callback("GET", ARM + NS_ID, callback=respond)
    mocked_response.add_callback("PATCH", ARM + NS_ID, callback=respond)
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline", 4102444800)))
    verify = mocker.spy(harness.provider._rbac, "verify_many")
    with DeviceRegistryMgmtClient(credential, "sub", base_url=ARM, retry_total=0) as client:
        harness.provider.client = client
        if view in {"converge", "stale-failure"}:
            result = harness.run(timeout_sec=5, wait_sec=1)
            assert result == desired
            assert harness.clock.now < 5
        else:
            with pytest.raises(AzureResponseError, match="timed out" if view == "timeout" else "changed"):
                harness.run(timeout_sec=5, wait_sec=1)
            if view == "timeout":
                assert harness.clock.now == 5
    assert writes == [{"properties": {"messaging": {"endpoints": {"hub": harness.body}}}}]
    verify.assert_not_called()  # In particular, no replay of the stale UAMI failure.
    assert len(mocked_response.calls) == len(gets) + 1


@pytest.mark.parametrize("drift", [
    "not-pending", "target", "type", "mixed", "identity", "settings", "namespace", "outbound",
])
def test_pending_projection_never_relaxes_external_drift_and_diagnostics_are_value_free(mocker, drift):
    harness = _rotation(mocker)
    expected = deepcopy(harness.body)
    expected["provisioning"]["allocationWeight"] = 30
    recovery = LinkRecovery(
        harness.provider, harness.namespace, "messaging", "hub", expected,
        LinkDeadline(clock=harness.clock.time, sleeper=harness.clock.sleep), Mock(),
    )
    recovery.pending = drift != "not-pending"
    current = deepcopy(harness.namespace)
    current["properties"]["provisioningState"] = "Updating"
    endpoint = current["properties"]["messaging"]["endpoints"]["hub"]
    if drift == "target":
        recovery.expected["resourceId"] += "-secret-target"
    elif drift == "type":
        recovery.expected["endpointType"] = "secret-type"
    elif drift == "mixed":
        endpoint["inboundCallerIdentity"] = deepcopy(expected["inboundCallerIdentity"])
    elif drift == "identity":
        endpoint["inboundCallerIdentity"]["userAssignedIdentity"] += "-secret-identity"
    elif drift == "settings":
        endpoint["provisioning"]["availability"] = "secret-setting"
    elif drift == "namespace":
        current["id"] += "-secret-namespace"
    elif drift == "outbound":
        current["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": "secret-outbound"}
    with pytest.raises(AzureResponseError, match="changed") as raised:
        recovery.inspect(current)
    assert "secret-" not in str(raised.value)
    assert recovery.snapshot is None
    recovery.verify.assert_not_called()


@pytest.mark.parametrize("status", [202, 204, None])
def test_group_refresh_acknowledgement_is_based_on_actual_initial_response(fixture_group_provider, mocker, status):
    poller = Mock()
    fixture_group_provider.client.groups.begin_refresh_members.return_value = poller
    mocker.patch.object(
        fixture_group_provider, "_poller_initial_http_response",
        return_value=SimpleNamespace(status_code=status) if status is not None else None,
    )
    scenario = Mock()
    scenario.cmd.side_effect = lambda _text: fixture_group_provider.refresh("group", "ns", "rg", no_wait=True)
    if status is None:
        with pytest.raises(AssertionError, match="unrecognized"):
            groups._observe_group_refresh(scenario, "refresh")
    else:
        assert groups._observe_group_refresh(scenario, "refresh") == "accepted"
    fixture_group_provider.client.groups.begin_refresh_members.assert_called_once()


@pytest.mark.parametrize("code,outcome", [
    ("GroupRefreshAlreadyInProgress", "reused"), ("GroupRefreshRateLimited", "throttled"),
])
def test_group_refresh_reuse_and_throttle_are_distinct_observable_cases(fixture_group_provider, code, outcome):
    fixture_group_provider.client.groups.begin_refresh_members.side_effect = _refresh_error(409, code)
    scenario = Mock()
    scenario.cmd.side_effect = lambda _text: fixture_group_provider.refresh("group", "ns", "rg", no_wait=True)
    assert groups._observe_group_refresh(scenario, "refresh") == outcome
    fixture_group_provider.client.groups.begin_refresh_members.assert_called_once()
    assert fixture_group_provider.client.groups.get.call_count == (1 if outcome == "reused" else 0)


@pytest.mark.parametrize("status,code,outcome", [
    (202, None, "accepted"), (204, None, "accepted"),
    (409, "GroupRefreshAlreadyInProgress", "reused"),
    (409, "GroupRefreshRateLimited", "throttled"),
])
def test_generated_sdk_refresh_retains_service_acknowledgement(mocked_response, status, code, outcome):
    # Headerless 202 deliberately avoids launching a background async-status
    # request. This test observes submission only (--no-wait), not completion.
    mocked_response.add(
        "POST", ARM + GROUP_ID + "/refreshMembers", status=status,
        json={"error": {"code": code, "message": "offline rejection"}} if code else None,
    )
    if outcome == "reused":
        mocked_response.add("GET", ARM + GROUP_ID, json={"properties": {"membershipState": "Resolving"}})
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline", 4102444800)))
    with DeviceRegistryMgmtClient(credential, "sub", base_url=ARM, retry_total=0) as client:
        provider = GroupProvider(Mock(), client=client)
        scenario = SimpleNamespace(cmd=lambda _text: provider.refresh("group", "ns", "rg", no_wait=True))
        assert groups._observe_group_refresh(scenario, "refresh") == outcome
    assert [call.request.method for call in mocked_response.calls] == (
        ["POST", "GET"] if outcome == "reused" else ["POST"]
    )


@pytest.mark.parametrize("error", [
    _refresh_error(400, "GroupRefreshRateLimited"), _refresh_error(409, "UnrelatedConflict"),
    _refresh_error(403, "AuthorizationFailed"), ServiceRequestError("transport"),
])
def test_group_refresh_observation_propagates_real_failures_and_removes_handler(error):
    scenario = Mock(cmd=Mock(side_effect=error))
    before = list(groups.group_provider.logger.handlers)
    with pytest.raises(type(error)) as raised:
        groups._observe_group_refresh(scenario, "refresh")
    assert raised.value is error
    assert groups.group_provider.logger.handlers == before


@pytest.mark.parametrize("evidence", [[], [("reused", 409), ("accepted", 202)], [("accepted", 200)]])
def test_group_refresh_does_not_accept_exit_zero_without_unique_valid_evidence(evidence):
    def command(_text):
        groups.group_provider.logger.warning("unrelated warning")
        for acknowledgement in evidence:
            groups.group_provider.logger.warning("ack", extra={"adr_group_refresh": acknowledgement})
    with pytest.raises(AssertionError, match="acknowledgement"):
        groups._observe_group_refresh(SimpleNamespace(cmd=command), "refresh")


def test_group_refresh_conflicting_throttle_is_not_success():
    def command(_text):
        groups.group_provider.logger.warning("ack", extra={"adr_group_refresh": ("reused", 409)})
        raise _refresh_error(409, "GroupRefreshRateLimited")
    with pytest.raises(AssertionError, match="conflicting"):
        groups._observe_group_refresh(SimpleNamespace(cmd=command), "refresh")


def test_refresh_handler_ignores_unrelated_records():
    handler = groups._RefreshEvidence()
    handler.emit(logging.makeLogRecord({"msg": "unrelated"}))
    assert not handler.acknowledgements


@pytest.mark.parametrize("outcome", ["accepted", "reused", "throttled", "unexpected"])
def test_group_lifecycle_accepts_supported_refresh_outcomes(mocker, outcome):
    mocker.patch.object(groups, "delete_test_namespace")
    mocker.patch.object(groups, "_observe_group_refresh", return_value=outcome)
    mocker.patch.object(groups, "_generate_group_name", return_value="group")
    scenario = Mock()

    def command(text, **_kwargs):
        if "group create" in text:
            value = {"name": "group", "properties": {"groupType": "RegistryDevice", "queryFilter": "*"}}
        elif "group show" in text:
            value = {"name": "group"}
        elif "group list-members" in text:
            value = []
        elif "group list" in text:
            value = [{"name": "group"}]
        elif "group count" in text:
            value = 0
        else:
            value = {
                "properties": {"displayName": "Test group", "description": "integration test"}, "tags": {"env": "ci"},
            }
        return Mock(get_output_in_json=lambda: value)

    scenario.cmd.side_effect = command
    if outcome == "unexpected":
        with pytest.raises(AssertionError, match="Unexpected group refresh outcome"):
            groups.TestADRGroupLifecycle.test_adr_group_lifecycle(scenario)
    else:
        groups.TestADRGroupLifecycle.test_adr_group_lifecycle(scenario)
    assert any("group update" in call.args[0] for call in scenario.cmd.call_args_list) is (outcome != "unexpected")
