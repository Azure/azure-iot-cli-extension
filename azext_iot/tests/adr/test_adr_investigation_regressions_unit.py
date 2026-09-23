# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline regressions for ADR group refresh acknowledgements."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ServiceRequestError

from azext_iot.adr.providers.group import GroupProvider
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr import test_adr_group_int as groups
from azext_iot.tests.adr.test_adr_group_unit import _refresh_error
from azext_iot.tests.adr.test_adr_link_propagation_unit import NS_ID


GROUP_ID = NS_ID + "/groups/group"
ARM = "https://centraluseuap.management.azure.com"


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
