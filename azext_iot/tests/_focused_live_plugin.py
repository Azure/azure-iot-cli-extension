# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""DPS debug selection guard, loaded explicitly before initial conftests."""

import os
from pathlib import Path
import re

import pytest

from azext_iot.tests import _focused_live as focused
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
    validate_args(early_config, tuple(debug["requestedNodes"]), early=True)
    folder = os.getenv("azext_iot_dps_phase_receipts")
    uid = os.getenv("azext_iot_dps_run_uid", "")
    if not folder or not Path(folder).is_absolute() or not re.fullmatch(r"[0-9a-f]{32}", uid):
        raise pytest.UsageError("Focused DPS requires a controller receipt directory and run UID.")
    runtime = PhaseReceipt("DPS", phase, debug["requestedNodes"], Path(folder) / "pytest.json", uid, debug=debug)
    early_config.pluginmanager.register(runtime, "dps-focused-receipt")
