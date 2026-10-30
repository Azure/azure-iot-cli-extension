# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from azext_iot.tests import helpers
from azext_iot.tests.conftest import pytest_runtest_protocol


@pytest.fixture
def budget_clock(mocker):
    clock = SimpleNamespace(now=0)
    mocker.patch.object(helpers, "monotonic", side_effect=lambda: clock.now)
    return clock


def test_nested_waits_share_elapsed_time_and_preserve_cleanup(budget_clock):
    budget = helpers.ScenarioBudget(100, cleanup=20)
    assert budget.remaining(60) == 60
    budget_clock.now = 70
    assert budget.remaining(60) == 10
    budget_clock.now = 80
    with pytest.raises(AssertionError, match="budget exhausted"):
        budget.remaining()
    budget.begin_cleanup()
    assert budget.remaining() == 20
    budget_clock.now = 95
    budget.begin_cleanup()
    assert budget.remaining(60) == 5


@pytest.mark.parametrize("elapsed", [79.5, 80, 100])
def test_expired_work_never_starts_a_call_or_returns_zero_timeout(budget_clock, elapsed):
    budget = helpers.ScenarioBudget(100, cleanup=20)
    budget_clock.now = elapsed
    command = Mock()
    with pytest.raises(AssertionError, match="budget exhausted"):
        budget.call(command)
    command.assert_not_called()


def test_late_success_is_rejected_and_cleanup_does_not_get_a_fresh_budget(budget_clock):
    budget = helpers.ScenarioBudget(100, cleanup=20)

    def slow_command():
        budget_clock.now = 85
        return "succeeded"

    with pytest.raises(AssertionError, match="budget exhausted"):
        budget.call(slow_command)
    budget.begin_cleanup()
    assert budget.remaining() == 15
    budget_clock.now = 100
    cleanup = Mock()
    with pytest.raises(AssertionError, match="budget exhausted"):
        budget.call(cleanup)
    cleanup.assert_not_called()


def test_service_failure_is_not_replaced_or_retried(budget_clock):
    budget = helpers.ScenarioBudget(100, cleanup=20)
    error = RuntimeError("service failure")
    command = Mock(side_effect=error)
    with pytest.raises(RuntimeError) as raised:
        budget.call(command, "--no-wait")
    assert raised.value is error
    command.assert_called_once_with("--no-wait")


@pytest.mark.parametrize("hook_error", [False, True])
def test_scenario_clock_includes_cold_fixtures_and_resets_even_on_hook_error(budget_clock, hook_error):
    item = SimpleNamespace(
        path=SimpleNamespace(name="test_budget_int.py"),
        get_closest_marker=lambda _name: SimpleNamespace(args=(100,), kwargs={"func_only": False}),
    )
    protocol = pytest_runtest_protocol(item)
    next(protocol)
    budget_clock.now = 60
    budget = helpers.ScenarioBudget(100, cleanup=20)
    assert budget.remaining() == 20
    budget.begin_cleanup()
    assert budget.remaining() == 40
    if hook_error:
        with pytest.raises(RuntimeError, match="hook failed"):
            protocol.throw(RuntimeError("hook failed"))
    else:
        with pytest.raises(StopIteration):
            next(protocol)
    assert helpers.ScenarioBudget(100, cleanup=20).remaining() == 80
