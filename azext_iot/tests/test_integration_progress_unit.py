# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace

import pytest

from azext_iot.tests import _integration_progress as subject


@pytest.fixture
def progress(mocker):
    config = SimpleNamespace(pluginmanager=mocker.Mock())
    thread = mocker.patch.object(subject, "Thread")
    clock = mocker.Mock(return_value=10.0)
    plugin = subject.IntegrationProgress(config, interval=60, clock=clock)
    plugin.pytest_sessionstart()
    yield plugin, config.pluginmanager.getplugin.return_value, clock, thread
    plugin.pytest_unconfigure()


def test_progress_reports_phases_and_durations_without_parameter_values(progress):
    plugin, reporter, clock, _ = progress
    nodeid = "test_example_int.py::test_example[credential-value]"
    plugin.pytest_runtest_logstart(nodeid)
    for when, outcome, now in (("setup", "passed", 20), ("call", "failed", 40), ("teardown", "passed", 45)):
        clock.return_value = now
        plugin.pytest_runtest_logreport(
            SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, duration=now - 10)
        )
    lines = [call.args[0] for call in reporter.write_line.call_args_list]
    assert len(lines) == 4
    assert "START setup" in lines[0]
    assert "END setup passed" in lines[1]
    assert "END call failed" in lines[2]
    assert "END teardown passed" in lines[3]
    assert all("credential-value" not in line for line in lines)
    assert reporter.flush.call_count == 4
    assert not plugin._active


def test_heartbeat_identifies_unfinished_phase_without_claiming_progress(progress, mocker):
    plugin, reporter, clock, _ = progress
    nodeid = "test_example_int.py::test_example"
    plugin.pytest_runtest_logstart(nodeid)
    clock.return_value = 15
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid=nodeid, when="setup", outcome="passed", duration=5)
    )
    reporter.reset_mock()
    clock.return_value = 75
    mocker.patch.object(plugin._stop, "wait", side_effect=[False, True])
    plugin._heartbeat()
    lines = [call.args[0] for call in reporter.write_line.call_args_list]
    assert "1 active test(s)" in lines[0]
    assert "not proof of service progress" in lines[0]
    assert "WAIT call" in lines[1]
    assert "test 65.0s, phase 60.0s without a completed phase report" in lines[1]


def test_idle_heartbeat_does_not_claim_tests_are_running(progress, mocker):
    plugin, reporter, _, _ = progress
    mocker.patch.object(plugin._stop, "wait", side_effect=[False, True])
    plugin._heartbeat()
    reporter.write_line.assert_called_once_with(
        "[integration progress] No active integration test reported; collecting or awaiting workers."
    )


@pytest.mark.parametrize("outcome", ["failed", "skipped"])
def test_unsuccessful_setup_transitions_to_teardown(progress, outcome):
    plugin, _, _, _ = progress
    nodeid = "test_example_int.py::test_example"
    plugin.pytest_runtest_logstart(nodeid)
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid=nodeid, when="setup", outcome=outcome, duration=1)
    )
    assert plugin._active[nodeid].phase == "teardown"


def test_negative_progress_interval_is_rejected(mocker):
    from azext_iot.tests.conftest import pytest_configure

    config = SimpleNamespace(getoption=lambda _: -1, pluginmanager=mocker.Mock())
    with pytest.raises(pytest.UsageError, match="must be nonnegative"):
        pytest_configure(config)
    config.pluginmanager.register.assert_not_called()


@pytest.mark.parametrize("case", ["disabled", "worker", "no-terminal"])
def test_progress_does_not_start_a_thread_when_disabled_or_on_workers(mocker, case):
    config = SimpleNamespace(pluginmanager=mocker.Mock())
    if case == "worker":
        config.workerinput = {}
    if case == "no-terminal":
        config.pluginmanager.getplugin.return_value = None
    thread = mocker.patch.object(subject, "Thread")
    plugin = subject.IntegrationProgress(config, interval=0 if case == "disabled" else 60)
    plugin.pytest_sessionstart()
    plugin.pytest_runtest_logstart("test_example_int.py::test_example")
    thread.assert_not_called()
    assert not plugin._active


def test_progress_ignores_unit_cases_and_untracked_reports(progress):
    plugin, reporter, _, _ = progress
    plugin.pytest_runtest_logstart("test_example_unit.py::test_example[test_example_int.py]")
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid="test_example_int.py::test_unknown", when="call")
    )
    reporter.write_line.assert_not_called()
    assert not plugin._active


def test_finish_and_crashed_worker_report_clear_active_test(progress):
    plugin, _, _, _ = progress
    nodeid = "test_example_int.py::test_example"
    plugin.pytest_runtest_logstart(nodeid)
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid=nodeid, when="???", outcome="failed", duration=0)
    )
    assert not plugin._active
    plugin.pytest_runtest_logstart(nodeid)
    plugin.pytest_runtest_logfinish(nodeid)
    assert not plugin._active


def test_progress_thread_stops_once_on_session_finish_and_unconfigure(progress):
    plugin, _, _, thread = progress
    thread.assert_called_once_with(
        target=plugin._heartbeat, name="iot-integration-progress", daemon=True,
    )
    thread.return_value.start.assert_called_once_with()
    plugin.pytest_sessionfinish()
    plugin.pytest_unconfigure()
    assert plugin._stop.is_set()
    thread.return_value.join.assert_called_once_with(timeout=1)
