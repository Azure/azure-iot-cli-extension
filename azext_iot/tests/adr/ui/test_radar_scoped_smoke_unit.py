# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Keep the opt-in pagination isolation explicit, scoped, and read-only."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from azext_iot.tests.adr import test_adr_radar_int as radar
from azext_iot.tests.adr.ui.test_radar_smoke_contract_unit import PREFIX, _smoke_session


@pytest.mark.parametrize("value, expected", [
    ("", False), ("false", False), ("0", False), ("unexpected", False),
    ("true", True), ("TRUE", True), ("yes", True), ("1", True),
])
def test_namespace_list_is_only_skipped_by_explicit_opt_in(monkeypatch, value, expected):
    monkeypatch.setenv("azext_iot_adr_radar_skip_namespace_list", value)
    assert radar._skip_namespace_list() is expected


def test_scoped_smoke_reads_owned_namespace_and_all_child_collections(monkeypatch):
    monkeypatch.setenv("azext_iot_adr_radar_skip_namespace_list", "true")
    network = Mock(side_effect=AssertionError("offline scoped smoke attempted network I/O"))
    monkeypatch.setattr("requests.sessions.Session.request", network)
    namespace = {
        "name": "owned", "location": "eastus2", "resourceGroup": "rg",
        "id": PREFIX + "Microsoft.DeviceRegistry/namespaces/owned",
        "properties": {"provisioningState": "Succeeded"},
    }
    session = _smoke_session(namespace)
    session.provider("namespace").list.side_effect = AssertionError("namespace collection must be skipped")
    asyncio.run(radar._browse_readonly_namespace(session, namespace))
    session.provider("namespace").list.assert_not_called()
    session.provider("namespace").show.assert_called_once_with(namespace_name="owned", resource_group_name="rg")
    session.provider("link").list_all.assert_called_once_with(namespace_name="owned", resource_group_name="rg")
    for name in ("group", "job", "certificate_authority"):
        session.provider(name).list.assert_called_once_with(namespace_name="owned", resource_group_name="rg")
    assert set(session._providers) == {"namespace", "link", "group", "job", "certificate_authority"}
    for provider in session._providers.values():
        assert all(call[0] in ("show", "list", "list_all") for call in provider.mock_calls)
    network.assert_not_called()


def test_scoped_scenario_skips_materialization_but_still_owns_and_cleans_namespace(monkeypatch):
    monkeypatch.setenv("azext_iot_adr_radar_skip_namespace_list", "true")
    network = Mock(side_effect=AssertionError("offline scoped smoke attempted network I/O"))
    monkeypatch.setattr("requests.sessions.Session.request", network)
    namespace = {"name": "owned", "location": radar.TEST_LOCATION, "properties": {"provisioningState": "Succeeded"}}
    session = _smoke_session(namespace)
    session.scope.subscription_id = radar.TEST_SUBSCRIPTION
    scenario = radar.TestADRRadar("test_radar_readonly_namespace_smoke")
    scenario._resource_is_absent = Mock(return_value=True)
    scenario._delete_owned_resource = Mock()
    owned = ("namespace", namespace["name"], radar.TEST_RG)

    def command(text):
        if text == "account show":
            return SimpleNamespace(get_output_in_json=lambda: {"id": radar.TEST_SUBSCRIPTION})
        assert owned in scenario._owned_resources
        return SimpleNamespace(get_output_in_json=dict)

    scenario.cmd = Mock(side_effect=command)
    monkeypatch.setattr(radar, "generate_adr_namespace_name", lambda: namespace["name"])
    monkeypatch.setattr(radar, "Session", Mock(return_value=session))
    listed = Mock(side_effect=AssertionError("materialization must not enumerate namespaces"))
    monkeypatch.setattr(radar, "wait_for_listed_resource", listed)
    browser = AsyncMock()
    monkeypatch.setattr(radar, "_browse_readonly_namespace", browser)
    scenario.test_radar_readonly_namespace_smoke()
    listed.assert_not_called()
    browser.assert_awaited_once_with(session, namespace)
    scenario._delete_owned_resource.assert_called_once_with(*owned)
    assert not scenario._owned_resources
    network.assert_not_called()
