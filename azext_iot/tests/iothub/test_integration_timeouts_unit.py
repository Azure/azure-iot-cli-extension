# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect

import pytest

from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES, DEVICE_TYPES
from azext_iot.tests.iothub.devices import test_iothub_devices_int as devices
from azext_iot.tests.iothub.devices import test_iothub_nested_edge_int as nested
from azext_iot.tests.iothub.jobs import test_iothub_jobs_int as jobs
from azext_iot.tests.iothub.message_endpoint import test_iothub_message_endpoint_int as endpoints
from azext_iot.tests.iothub.modules import test_iothub_modules_int as modules
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
    state.test_custom_scenarios_controlplane,
    state.test_mirgate_hub_dataplane_error,
    state.test_export_import_migrate_missing_hubs_error,
    endpoints.test_iot_eventhub_endpoint_lifecycle,
])
def test_ordinary_scenarios_keep_the_default_timeout(scenario):
    assert not any(mark.name == "timeout" for mark in getattr(scenario, "pytestmark", []))


@pytest.mark.parametrize("scenario,windows", [
    (devices.TestIoTHubDevices.test_iothub_device_identity, len(DATAPLANE_AUTH_TYPES) * len(DEVICE_TYPES)),
    (modules.TestIoTHubModules.test_iothub_module_identity, len(DATAPLANE_AUTH_TYPES) * len(DEVICE_TYPES)),
    (nested.TestIoTHubNestedEdge.test_iothub_nested_edge, 3 * len(DATAPLANE_AUTH_TYPES)),
    (jobs.TestIoTHubJobs.test_jobs, 2 * len(DATAPLANE_AUTH_TYPES)),
    (state.test_migrate_dataplane, 1 + len(DATAPLANE_AUTH_TYPES)),
    (state.test_export_import_dataplane, 1 + len(DATAPLANE_AUTH_TYPES)),
])
def test_query_scenarios_budget_each_sequential_window_and_the_existing_lifecycle(scenario, windows):
    _assert_lifecycle_budget(scenario, 900 + 1800 * windows)


@pytest.mark.parametrize("scenario_class,heavy", [
    (devices.TestIoTHubDevices, "test_iothub_device_identity"),
    (modules.TestIoTHubModules, "test_iothub_module_identity"),
    (nested.TestIoTHubNestedEdge, "test_iothub_nested_edge"),
])
def test_other_identity_methods_do_not_inherit_query_timeouts(scenario_class, heavy):
    ordinary = [
        scenario for name, scenario in vars(scenario_class).items()
        if name.startswith("test_") and name != heavy
    ]
    assert ordinary
    for scenario in ordinary:
        assert not any(mark.name == "timeout" for mark in getattr(scenario, "pytestmark", []))
