# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the repo root for license information.
# --------------------------------------------------------------------------------------------

"""Per-operation guided-linking execution behavior."""

from azext_iot.adr.ui.screens.onboard.execution import (
    ExecutionRecord,
    ExecutionState,
    execute_records,
)
from azext_iot.adr.ui.screens.onboard.flow import PlanItem


def test_execution_tracks_mutation_polling_and_success():
    seen = []
    item = PlanItem(
        key="link",
        description="Link DPS",
        invoke=lambda _session, _context: None,
        verify=lambda _session, _context, notify: notify("linkingState: Succeeded"),
    )
    record = ExecutionRecord(item)
    assert execute_records(
        [record],
        object(),
        {},
        lambda _poller: None,
        lambda current: seen.append(current.state),
    )
    assert ExecutionState.RUNNING in seen
    assert ExecutionState.POLLING in seen
    assert record.state is ExecutionState.SUCCEEDED
    assert record.detail == "linkingState: Succeeded"


def test_critical_failure_skips_remaining_operations():
    def fail(_session, _context):
        raise RuntimeError("role assignment denied")

    records = [
        ExecutionRecord(PlanItem(key="grant", description="Grant role", invoke=fail)),
        ExecutionRecord(
            PlanItem(
                key="link",
                description="Link Hub",
                invoke=lambda _session, _context: None,
            )
        ),
    ]
    assert not execute_records(records, object(), {}, lambda _poller: None)
    assert records[0].state is ExecutionState.FAILED
    assert records[1].state is ExecutionState.SKIPPED
