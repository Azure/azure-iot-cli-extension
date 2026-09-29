# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Dataplane state scenarios own a separate module-scoped pool of plain Hubs."""

from shlex import quote

import pytest

from azext_iot.tests.iothub import set_cmd_auth_type
from azext_iot.tests.iothub.state import _state_helpers as state


setup_hub_states_dataplane = state.setup_hub_states_dataplane


@pytest.mark.hub_infrastructure(count=2)
@pytest.mark.timeout(state.DATAPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_migrate_dataplane(setup_hub_states_dataplane):
    origin_name = setup_hub_states_dataplane[0]["name"]
    origin_rg = setup_hub_states_dataplane[0]["rg"]
    origin_auth = state._hub_auth(setup_hub_states_dataplane[0])
    dest_name = setup_hub_states_dataplane[1]["name"]
    dest_auth = state._hub_auth(setup_hub_states_dataplane[1])
    for phase_index, auth_phase in enumerate(state.DATAPLANE_AUTH_TYPES):
        state._invoke_state(
            set_cmd_auth_type(
                f"iot hub state migrate --origin-hub {origin_name} --origin-resource-group {origin_rg} "
                f"--destination-hub {dest_name} --destination-resource-group {origin_rg} -r --aspects {state.DATAPLANE}",
                auth_type=auth_phase,
                cstring=None
            ),
        )
        state._wait_for_dataplane_query(dest_auth, setup_hub_states_dataplane[0]["state_data"])
        state.compare_hubs_dataplane(origin_auth, dest_auth, setup_hub_states_dataplane[0]["state_data"])
        # Keep the final owned dataset for the fixture's checked teardown.
        if phase_index + 1 < len(state.DATAPLANE_AUTH_TYPES):
            state.clean_up_hub_dataplane(setup_hub_states_dataplane[1])


@pytest.mark.hub_infrastructure(count=1)
@pytest.mark.timeout(state.DATAPLANE_LIFECYCLE_TIMEOUT, func_only=False)
def test_export_import_dataplane(setup_hub_states_dataplane):
    filename = setup_hub_states_dataplane[0]["filename"]
    hub_name = setup_hub_states_dataplane[0]["name"]
    hub_rg = setup_hub_states_dataplane[0]["rg"]
    hub_auth = state._hub_auth(setup_hub_states_dataplane[0])
    for auth_phase in state.DATAPLANE_AUTH_TYPES:
        state._invoke_state(
            set_cmd_auth_type(
                f"iot hub state export -n {hub_name} -f {quote(filename)} -g {hub_rg} -r --aspects {state.DATAPLANE}",
                auth_type=auth_phase,
                cstring=None
            ),
        )
        state.compare_hub_dataplane_to_file(filename, hub_auth, setup_hub_states_dataplane[0]["state_data"])

    for auth_phase in state.DATAPLANE_AUTH_TYPES:
        state.clean_up_hub_dataplane(setup_hub_states_dataplane[0])
        state._invoke_state(
            set_cmd_auth_type(
                f"iot hub state import -n {hub_name} -f {quote(filename)} -g {hub_rg} -r --aspects {state.DATAPLANE}",
                auth_type=auth_phase,
                cstring=None
            ),
        )
        state._wait_for_dataplane_query(hub_auth, setup_hub_states_dataplane[0]["state_data"])
        state.compare_hub_dataplane_to_file(filename, hub_auth, setup_hub_states_dataplane[0]["state_data"])
