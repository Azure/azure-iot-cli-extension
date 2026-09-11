# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace

import pytest
from _pytest.reports import TestReport as Report

from azext_iot.tests.conftest import ImmediateIntegrationReports


@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
@pytest.mark.parametrize("outcome", ["failed", "rerun"])
def test_integration_failures_are_flushed_immediately_on_controller(mocker, when, outcome):
    report = Report(
        nodeid="test_example_int.py::test_example",
        location=("test_example_int.py", 1, "test_example"),
        keywords={}, outcome=outcome, longrepr="AzureResponseError: original service failure", when=when,
    )
    config = SimpleNamespace(pluginmanager=mocker.Mock())
    reporter = config.pluginmanager.getplugin.return_value
    assert ImmediateIntegrationReports(config).pytest_runtest_logreport(report) is None
    reporter.write_sep.assert_called_once_with(
        "=", f"Immediate {outcome} ({when}): {report.nodeid}",
    )
    reporter.write_line.assert_called_once_with(report.longreprtext)
    reporter.flush.assert_called_once_with()


@pytest.mark.parametrize("case", ["worker", "unit", "passed", "skipped", "no-terminal"])
def test_immediate_reports_do_not_duplicate_workers_or_change_other_outcomes(mocker, case):
    config = SimpleNamespace(pluginmanager=mocker.Mock())
    report = SimpleNamespace(nodeid="test_example_int.py::test_example", outcome="failed")
    reporter = config.pluginmanager.getplugin.return_value
    if case == "worker":
        config.workerinput = {}
    elif case == "unit":
        report.nodeid = "test_example_unit.py::test_example[test_example_int.py]"
    elif case in ("passed", "skipped"):
        report.outcome = case
    else:
        config.pluginmanager.getplugin.return_value = None
    assert ImmediateIntegrationReports(config).pytest_runtest_logreport(report) is None
    reporter.write_sep.assert_not_called()
    reporter.write_line.assert_not_called()
    reporter.flush.assert_not_called()
