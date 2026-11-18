# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exact DPS debug/attempt selection, loaded explicitly before initial conftests."""

import os
from pathlib import Path
import re

import pytest

from azext_iot.tests import _focused_live as focused
from azext_iot.tests import _integration_target as target
from azext_iot.tests._hub_suite_plugin import PhaseReceipt, validate_args


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    phase = os.getenv("azext_iot_dps_test_phase")
    try:
        debug = focused.from_environment(os.environ, "DPS", phase)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    if debug is None:
        raise pytest.UsageError("The focused DPS plugin requires an explicit controller debug selection.")
    parallel = "attempt" in debug and phase != "local-auth-toggle"
    validate_args(early_config, tuple(debug["requestedNodes"]), early=True, parallel=parallel)
    folder = os.getenv("azext_iot_dps_phase_receipts")
    uid = os.getenv("azext_iot_dps_run_uid", "")
    if not folder or not Path(folder).is_absolute() or not re.fullmatch(r"[0-9a-f]{32}", uid):
        raise pytest.UsageError("Focused DPS requires a controller receipt directory and run UID.")
    runtime = PhaseReceipt("DPS", phase, debug["requestedNodes"], Path(folder) / "pytest.json", uid,
                           debug=debug, parallel=parallel)
    early_config.pluginmanager.register(runtime, "dps-focused-receipt")


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef):
    if (fixturedef.argname != "provisioned_iot_dps_local_auth_module"
            or os.getenv(target.ENDPOINT_ENV) != target.CHINA_ARM
            or os.getenv("azext_iot_dps_test_phase") != "local-auth-toggle"):
        yield
        return
    selection = focused.from_environment(os.environ, "DPS", "local-auth-toggle")
    if not selection or not set(selection["requestedNodes"]) <= focused.DPS_LOCAL_AUTH_MANAGEMENT_NODES:
        yield
        return
    namespace = fixturedef.func.__globals__
    target.check_cloud(namespace["cli"].az_cli, target.CHINA_ARM)
    original = namespace["_wait_for_current_user_data_plane"]

    def wait_for_data_plane(role, scope):
        if role == namespace["DPS_USER_ROLE"]:
            namespace["logger"].info(
                "Mooncake ARM-only local-auth tests do not require a DPS data-plane readiness probe: %s",
                focused.DPS_MOONCAKE_TLS_REASON,
            )
            return None
        return original(role, scope)

    # Adapt current and frozen fixtures identically, only during this module's
    # setup. Keep ARM provisioning, RBAC assignment/visibility, assertions and
    # cleanup unchanged; never suppress TLS errors from a selected data-plane test.
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(namespace, "_wait_for_current_user_data_plane", wait_for_data_plane)
        yield
