# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect

import pytest

from azext_iot.tests.iothub.message_endpoint import test_iothub_message_endpoint_int as endpoints
from azext_iot.tests.iothub.state import test_hub_state_int as state


def _assert_lifecycle_budget(scenario, seconds):
    markers = [mark for mark in getattr(scenario, "pytestmark", []) if mark.name == "timeout"]
    assert len(markers) == 1
    assert markers[0].args == (seconds,)
    assert markers[0].kwargs == {"func_only": False}


def test_every_controlplane_fixture_consumer_can_initialize_the_shared_resources():
    consumers = [
        scenario for name, scenario in vars(state).items()
        if name.startswith("test_") and inspect.isfunction(scenario)
        and "setup_hub_states_controlplane" in inspect.signature(scenario).parameters
    ]
    assert consumers
    for scenario in consumers:
        _assert_lifecycle_budget(scenario, 2700)


@pytest.mark.parametrize("scenario,seconds", [
    (state.test_export_cosmosdb_endpoint_resource_name_starting_with_scheme_char, 2700),
    (endpoints.test_iot_endpoint_force_delete, 2100),
])
def test_expensive_last_items_include_shared_resource_teardown(scenario, seconds):
    _assert_lifecycle_budget(scenario, seconds)


@pytest.mark.parametrize("scenario", [
    state.test_migrate_dataplane,
    state.test_mirgate_hub_dataplane_error,
    state.test_export_import_migrate_missing_hubs_error,
    endpoints.test_iot_eventhub_endpoint_lifecycle,
])
def test_ordinary_scenarios_keep_the_default_timeout(scenario):
    assert not any(mark.name == "timeout" for mark in getattr(scenario, "pytestmark", []))
