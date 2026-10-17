# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Operations tray and command preview (step 10)."""

import pytest

from azext_iot.adr.ui.core.commands import quote, render, wrap
from azext_iot.adr.ui.core.ops import OperationTracker, OpState


class FakePoller:
    def result(self):
        return {"provisioningState": "Succeeded"}


@pytest.fixture
def tracker():
    return OperationTracker(provider_waiter=lambda poller: poller.result())


# -- tracking ------------------------------------------------------------------------


def test_started_operation_is_running(tracker):
    operation = tracker.start("Delete", "device-1")
    assert operation.state is OpState.RUNNING
    assert tracker.running == [operation]


def test_poller_success_marks_terminal(tracker):
    operation = tracker.start("Delete", "device-1")
    tracker.await_poller(operation, FakePoller())
    assert operation.state is OpState.SUCCEEDED
    assert operation.finished_at is not None


def test_poller_failure_records_the_reason(tracker):
    def waiter(poller):
        raise RuntimeError("endpoint 'dr-hub': not authorized")

    failing = OperationTracker(provider_waiter=waiter)
    operation = failing.start("Link", "dr-hub")
    failing.await_poller(operation, FakePoller())
    assert operation.state is OpState.FAILED
    assert "not authorized" in operation.error


def test_failure_detail_is_preserved(tracker):
    class Detailed(RuntimeError):
        detail = "correlation 7f3a"

    def waiter(poller):
        raise Detailed("link failed")

    failing = OperationTracker(provider_waiter=waiter)
    operation = failing.start("Link", "hub")
    failing.await_poller(operation, FakePoller())
    assert operation.detail == "correlation 7f3a"


def test_inline_completion_counts_as_success(tracker):
    """Some providers return the resource directly rather than a poller."""
    operation = tracker.start("Update", "group-1")
    tracker.await_poller(operation, {"name": "group-1"})
    assert operation.state is OpState.SUCCEEDED


def test_tracker_without_a_waiter_fails_loudly():
    tracker = OperationTracker()
    operation = tracker.start("Delete", "x")
    tracker.await_poller(operation, FakePoller())
    assert operation.state is OpState.FAILED
    assert "waiter" in operation.error


# -- lifecycle -----------------------------------------------------------------------


def test_succeeded_operations_are_pruned(tracker):
    operation = tracker.start("Delete", "device-1")
    tracker.await_poller(operation, FakePoller())
    tracker.prune(keep_seconds=0)
    assert tracker.operations == []


def test_failures_persist_until_acknowledged():
    failing = OperationTracker(provider_waiter=lambda p: (_ for _ in ()).throw(RuntimeError("no")))
    operation = failing.start("Link", "hub")
    failing.await_poller(operation, FakePoller())
    failing.prune(keep_seconds=0)
    assert failing.failed, "a failure must not vanish before the user has seen it"
    failing.acknowledge(operation.id)
    failing.prune(keep_seconds=0)
    assert not failing.operations


def test_tracking_is_bounded(tracker):
    for index in range(80):
        tracker.start("Delete", f"d{index}")
    assert len(tracker.operations) <= 50


def test_refresh_targets_come_from_succeeded_operations(tracker):
    operation = tracker.start("Delete", "d1", refreshes=("device", "group"))
    tracker.await_poller(operation, FakePoller())
    assert set(tracker.refresh_targets()) == {"device", "group"}


def test_summary_mentions_running_work(tracker):
    tracker.start("Link", "hub-a")
    tracker.start("Schedule", "job-a")
    assert "running" in tracker.summary()


def test_summary_is_blank_when_idle(tracker):
    assert tracker.summary() == ""


# -- command rendering ---------------------------------------------------------------


def test_render_builds_a_scoped_command():
    command = render(
        "iot adr ns registry-device delete",
        name="edge-01",
        scope={"namespace_name": "ns1", "resource_group_name": "rg1"},
        flags=("--yes",),
    )
    assert command == "az iot adr ns registry-device delete -n edge-01 --ns ns1 -g rg1 --yes"


def test_render_includes_options():
    command = render(
        "iot adr ns registry-device update",
        name="edge-01",
        scope={"namespace_name": "ns1"},
        options={"enablement_state": "Disabled"},
    )
    assert "--enablement-state Disabled" in command


def test_render_skips_empty_values():
    command = render("iot adr ns list", scope={"resource_group_name": None},
                     options={"tags": ""})
    assert command == "az iot adr ns list"


def test_render_does_not_duplicate_the_name_flag():
    command = render("iot adr ns job run show", name="run-1",
                     scope={"run_name": "run-1", "job_name": "job-1"})
    assert command.count("-n ") == 1
    assert "--job-name job-1" in command


def test_quote_only_when_needed():
    assert quote("simple") == "simple"
    assert quote("has space") == "'has space'"
    assert quote("properties.manufacturer = 'Contoso'").startswith("'")
    assert quote("") == "''"


def test_quote_blocks_shell_expansion():
    assert quote("$(touch /tmp/owned)") == "'$(touch /tmp/owned)'"
    assert quote("`touch /tmp/owned`") == "'`touch /tmp/owned`'"
    assert quote("$HOME") == "'$HOME'"


def test_wrap_leaves_short_commands_alone():
    assert wrap("az iot adr ns list") == "az iot adr ns list"


def test_wrap_uses_shell_continuations():
    long_command = render(
        "iot adr ns link dps add",
        scope={"namespace_name": "a-very-long-namespace-name-here", "resource_group_name": "rg"},
        options={"endpoint_name": "dps", "dps_id": "/subscriptions/x/resourceGroups/y/providers/z"},
    )
    wrapped = wrap(long_command, width=60)
    assert " \\\n" in wrapped
    assert wrapped.replace(" \\\n", " ").replace("    ", " ").split() == long_command.split()


def test_wrap_preserves_intentional_command_substitution():
    command = (
        'az role assignment create --assignee-object-id "$(az resource show '
        '--ids /subscriptions/sub/resourceGroups/rg/providers/type/resource '
        '--query identity.principalId --output tsv)" '
        "--assignee-principal-type ServicePrincipal --role Contributor "
        "--scope /subscriptions/sub/resourceGroups/rg/providers/type/target"
    )
    wrapped = wrap(command, width=72)
    assert '"$(az resource show ' in wrapped
    assert "'$(az resource show " not in wrapped
    assert wrapped.replace(" \\\n    ", " ") == command
