# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Selection contract for separately scheduled DPS integration phases (no Azure calls)."""

import os

import pytest
from azext_iot.tests.dps._phase_manifest import expected_nodeids, normalize_nodeid, resource_kinds

PHASE_ENV = "azext_iot_dps_test_phase"
REGULAR = "regular"
SERVICE_SAS = "service-sas"
LOCAL_AUTH_TOGGLE = "local-auth-toggle"
SERVICE_SAS_MARKER = "dps_service_sas"
LOCAL_AUTH_TOGGLE_MARKER = "dps_local_auth_toggle"
SERVICE_SAS_NODEIDS = expected_nodeids(SERVICE_SAS)
PENDING_CERTIFICATE_TESTS = {
    "test_dps_enrollment_adr_certificate_reference_round_trip",
    "test_dps_enrollment_group_adr_certificate_reference_round_trip",
    "test_register_and_issue_certificate_contract",
}


def get_phase():
    phase = os.environ.get(PHASE_ENV, REGULAR).strip()
    try:
        resource_kinds(phase)
    except ValueError as error:
        raise pytest.UsageError(
            f"Unknown {PHASE_ENV}={phase!r}; expected {REGULAR!r}, {SERVICE_SAS!r}, or {LOCAL_AUTH_TOGGLE!r}."
        ) from error
    return phase


def local_auth_disabled():
    return get_phase() != SERVICE_SAS


def configure(config):
    get_phase()  # Fail before fixture setup, including for a misspelled phase.
    config.addinivalue_line(
        "markers", f"{SERVICE_SAS_MARKER}: DPS service-policy SAS coverage; requires the isolated service-sas phase."
    )
    config.addinivalue_line(
        "markers", f"{LOCAL_AUTH_TOGGLE_MARKER}: DPS auth-policy toggle coverage; requires its serial owned phase."
    )
    if get_phase() == LOCAL_AUTH_TOGGLE and config.getoption("numprocesses", default=None) not in (None, 0):
        raise pytest.UsageError("The DPS local-auth-toggle phase must run serially with -n 0.")


def select_items(config, items):
    phase = get_phase()
    explicit_phase = PHASE_ENV in os.environ
    selected, deselected = [], []
    for item in items:
        service_sas = item.get_closest_marker(SERVICE_SAS_MARKER) is not None
        local_auth_toggle = item.get_closest_marker(LOCAL_AUTH_TOGGLE_MARKER) is not None
        pending_certificate = (
            explicit_phase and item.nodeid.rsplit("::", 1)[-1].partition("[")[0] in PENDING_CERTIFICATE_TESTS
        )
        item_phase = LOCAL_AUTH_TOGGLE if local_auth_toggle else SERVICE_SAS if service_sas else REGULAR
        (selected if not pending_certificate and item_phase == phase else deselected).append(item)
    if phase != REGULAR or explicit_phase:
        expected = expected_nodeids(phase)
        actual = {
            normalize_nodeid(item.nodeid)
            for item in selected
        }
        if actual != expected or len(selected) != len(expected):
            raise pytest.UsageError(
                f"The {phase} phase requires exactly {len(expected)} cases. Run the complete DPS integration tree "
                "without additional -k/-m/node filters. "
                f"Missing: {sorted(expected - actual)}; unexpected: {sorted(actual - expected)}."
            )
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)


def require_requested_coverage(item, report):
    """A requested capability missing at runtime is a failure, not a green skipped phase."""
    if not report.skipped:
        return
    requested = PHASE_ENV in os.environ and (
        get_phase() == REGULAR or item.get_closest_marker(SERVICE_SAS_MARKER)
        or item.get_closest_marker(LOCAL_AUTH_TOGGLE_MARKER)
    )
    if requested and report.skipped:
        report.outcome = "failed"
        report.longrepr = (
            f"Requested {get_phase()} coverage cannot be skipped. Satisfy its resource/authentication "
            f"prerequisites before rerunning the phase. Original skip: {report.longrepr}"
        )
        if hasattr(report, "wasxfail"):
            del report.wasxfail
