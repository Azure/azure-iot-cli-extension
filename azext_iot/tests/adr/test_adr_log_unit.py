# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import runpy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from azext_iot.tests.adr import _log as log
from azext_iot.tests.adr.conftest import pytest_runtest_logreport


@pytest.fixture(autouse=True)
def plain_logs(monkeypatch):
    monkeypatch.delenv("PRETTY_LOG", raising=False)


@pytest.mark.parametrize(
    "kind,prefix,color",
    [
        (log.LogKind.TEST, "\u25b6 TEST: ", "gold"),
        (log.LogKind.STEP, "", "gold"),
        (log.LogKind.CMD, "  \u203a ", "sky"),
        (log.LogKind.RESULT, "  \u21b3 ", "clay"),
        (log.LogKind.OK, "  \u2713 ", "sage"),
        (log.LogKind.WARN, "  \u26a0 ", "terra"),
        ("_pass", "\u2713 PASS ", "sage"),
        ("_fail", "\u2717 FAIL ", "terra"),
        ("_time", "  \u0394 ", "dim"),
    ],
)
@pytest.mark.parametrize("pretty", [False, True])
def test_log_format(kind, prefix, color, pretty, monkeypatch, capsys, caplog):
    if pretty:
        monkeypatch.setenv("PRETTY_LOG", "1")
    with patch.object(log, "_ts", return_value="17:21:30"):
        log._log(kind, "example %s", "message")

    text = prefix + "example message"
    if kind == log.LogKind.STEP:
        text += " \u00b7 17:21:30"
    output = capsys.readouterr()
    assert not output.err
    if pretty:
        separator = "\n" if kind in (log.LogKind.TEST, log.LogKind.STEP) else ""
        assert output.out == f"{separator}{log._ANSI[color]}{text}{log._ANSI_RESET}\n"
        assert not caplog.records
    else:
        assert not output.out
        assert [(record.levelname, record.getMessage()) for record in caplog.records] == [
            ("WARNING", text)
        ]
        assert "\033[" not in caplog.text


@pytest.mark.parametrize("value", [None, "", "0", "false", "1"])
def test_pretty_log_requires_explicit_opt_in(value, monkeypatch):
    if value is not None:
        monkeypatch.setenv("PRETTY_LOG", value)
    assert log._pretty_log_enabled() is (value == "1")


def test_unknown_log_kind_is_rejected(capsys, caplog):
    with pytest.raises(ValueError, match="Unknown log type"):
        log._log("unknown", "message")
    assert not capsys.readouterr().out
    assert not caplog.records


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0.0s"), (12.34, "12.3s"), (60, "1m0s"), (90, "1m30s")],
)
def test_duration_format(seconds, expected):
    assert log._fmt_duration(seconds) == expected


@pytest.mark.parametrize("fails", [False, True])
def test_timed_step_reports_delta_and_preserves_failure(fails, caplog):
    error = RuntimeError("step failed")
    with patch.object(log, "_ts", return_value="17:21:30"), patch.object(
        log.time, "monotonic", side_effect=[100, 112.3]
    ):
        if fails:
            with pytest.raises(RuntimeError) as raised, log.timed_step("Step %s > Create", 1):
                raise error
            assert raised.value is error
        else:
            with log.timed_step("Step %s > Create", 1):
                pass

    assert caplog.messages == [
        "Step 1 > Create \u00b7 17:21:30",
        "  \u0394 (12.3s)",
    ]


@pytest.mark.parametrize(
    "outcome,reason,expected",
    [
        ("passed", "", "\u2713 PASS test_example"),
        ("failed", "___ traceback ___\n\n  AssertionError: example", "\u2717 FAIL test_example -- AssertionError: example"),
        ("failed", "", "\u2717 FAIL test_example"),
        ("failed", "x" * 220, "\u2717 FAIL test_example -- " + "x" * 200),
    ],
)
def test_pretty_test_outcome(outcome, reason, expected, monkeypatch, capsys):
    monkeypatch.setenv("PRETTY_LOG", "1")
    report = SimpleNamespace(
        when="call",
        nodeid="test_example_int.py::TestExample::test_example",
        passed=outcome == "passed",
        failed=outcome == "failed",
        longreprtext=reason,
    )

    pytest_runtest_logreport(report)

    color = "sage" if outcome == "passed" else "terra"
    assert capsys.readouterr().out == f"{log._ANSI[color]}{expected}{log._ANSI_RESET}\n"


@pytest.mark.parametrize(
    "pretty,when,outcome",
    [
        ("0", "call", "passed"),
        ("", "call", "failed"),
        ("1", "setup", "failed"),
        ("1", "teardown", "failed"),
        ("1", "call", "skipped"),
    ],
)
def test_outcome_hook_preserves_standard_pytest_reporting(pretty, when, outcome, monkeypatch, capsys):
    monkeypatch.setenv("PRETTY_LOG", pretty)
    report = SimpleNamespace(
        when=when,
        nodeid="test_example_int.py::TestExample::test_example",
        passed=outcome == "passed",
        failed=outcome == "failed",
    )

    pytest_runtest_logreport(report)

    assert not capsys.readouterr().out


@pytest.mark.parametrize("wait_fails,cleanup_fails", [(False, False), (True, False), (True, True)])
def test_namespace_lifecycle_logging_preserves_commands_and_cleanup(wait_fails, cleanup_fails, caplog, mocker):
    from azext_iot.tests.adr import test_adr_namespace_crud_int as scenario

    test = scenario.TestADRNamespaceCrud.__new__(scenario.TestADRNamespaceCrud)
    test._testMethodName = "test_namespace_crud_lifecycle"
    test.kwargs = {}
    test.cli_ctx = Mock()
    test.cmd = Mock(wraps=test.cmd)
    mocker.patch.object(scenario, "TEST_RG", "test-rg")
    mocker.patch.object(scenario, "TEST_SUBSCRIPTION", None)
    execution = mocker.patch("azure.cli.testsdk.base.execute", autospec=True)
    namespace_name = "test-namespace"
    created = {
        "name": namespace_name,
        "location": scenario.TEST_LOCATION,
        "identity": {"type": "SystemAssigned"},
        "properties": {"provisioningState": "Succeeded"},
    }
    execution.return_value.assert_with_checks.return_value.get_output_in_json.side_effect = [
        {"id": "test-sub"},
        {"endpoints": {"resourceManager": "https://management.azure.com/"}},
        created,
        [created],
        {"tags": {"env": "test", "purpose": "ci"}},
        {"tags": {"owner": "adr-tests"}},
        {"properties": {"messaging": {"endpoints": {}}}},
        {"type": "None"},
        {"type": "SystemAssigned"},
    ]
    error = RuntimeError("authentication failed")
    if wait_fails:
        execution.side_effect = [
            *[execution.return_value] * 5,
            error,
            RuntimeError("cleanup failed") if cleanup_fails else execution.return_value,
        ]

    with patch.object(scenario, "generate_adr_namespace_name", return_value=namespace_name):
        if wait_fails:
            with pytest.raises(RuntimeError) as raised:
                scenario.TestADRNamespaceCrud.test_namespace_crud_lifecycle(test)
            assert raised.value is error
        else:
            scenario.TestADRNamespaceCrud.test_namespace_crud_lifecycle(test)

    commands = [call.args[0] for call in test.cmd.call_args_list]
    assert commands[4] == (
        f"iot adr ns create -n {namespace_name} -g {scenario.TEST_RG} "
        f"--location {scenario.TEST_LOCATION} --no-wait"
    )
    assert commands[5] == f"iot adr ns wait -n {namespace_name} -g {scenario.TEST_RG} --created"
    assert caplog.messages[0] == "\u25b6 TEST: test_namespace_crud_lifecycle"
    command_logs = [message for message in caplog.messages if message.startswith("  \u203a az ")]
    assert len(command_logs) == len(commands)
    durations = [message for message in caplog.messages if message.startswith("  \u0394 (")]
    if wait_fails:
        assert commands[6:] == [f"iot adr ns delete -n {namespace_name} -g {scenario.TEST_RG} --yes"]
        assert len(durations) == 3
        assert not any(message.startswith("  \u2713 ") for message in caplog.messages)
        assert any("cleanup failed" in message for message in caplog.messages) is cleanup_fails
    else:
        assert len(commands) == 23
        assert commands[-2] == f"iot adr ns wait -n {namespace_name} -g {scenario.TEST_RG} --deleted"
        assert [index for index, call in enumerate(test.cmd.call_args_list) if call.kwargs] == [9, 22]
        assert all(
            call.kwargs == {"expect_failure": True}
            for call in test.cmd.call_args_list if call.kwargs
        )
        assert len(durations) == 6
        assert "  \u2713 Namespace deleted" in caplog.messages


def test_timestamp_is_utc():
    assert len(log._ts()) == 8


@pytest.mark.parametrize("pretty", [False, True])
def test_raw_log_with_and_without_arguments(pretty, monkeypatch, caplog, capsys):
    monkeypatch.setenv("PRETTY_LOG", "1" if pretty else "0")
    log._raw_log()
    log._raw_log("literal")
    log._raw_log("value %s", "example")
    if pretty:
        assert capsys.readouterr().out == "\nliteral\nvalue example\n"
    else:
        assert caplog.messages == ["literal", "value example"]


def test_pretty_log_without_color(monkeypatch, capsys):
    monkeypatch.setenv("PRETTY_LOG", "1")
    monkeypatch.setitem(log._STYLES, "plain", ("prefix ", "missing"))
    log._log("plain", "value")
    assert capsys.readouterr().out == "prefix value\n"


def test_pretty_step_without_arguments(monkeypatch, capsys):
    monkeypatch.setenv("PRETTY_LOG", "1")
    with patch.object(log, "_ts", return_value="17:21:30"):
        log._log(log.LogKind.STEP, "Step")
    assert "Step \u00b7 17:21:30" in capsys.readouterr().out


def test_namespace_scenario_requires_config(mocker):
    from azext_iot.tests.adr import test_adr_namespace_crud_int as scenario
    mocker.patch.object(scenario, "TEST_RG", None)
    test = scenario.TestADRNamespaceCrud.__new__(scenario.TestADRNamespaceCrud)
    with pytest.raises(pytest.skip.Exception, match="azext_iot_testrg"):
        scenario.TestADRNamespaceCrud.test_namespace_crud_lifecycle(test)


def test_preflight_uses_explicit_configuration_and_does_not_provision(mocker):
    from azext_iot.tests.adr import test_adr_namespace_crud_int as scenario
    mocker.patch.object(scenario, "TEST_RG", "test group")
    mocker.patch.object(scenario, "TEST_SUBSCRIPTION", "selected-sub")
    mocker.patch.object(scenario, "TEST_LOCATION", "selected-location")
    mocker.patch.object(scenario, "TEST_API_VERSION", "selected-api")
    test = scenario.TestADRNamespaceCrud.__new__(scenario.TestADRNamespaceCrud)
    test.cmd = Mock()
    test.cmd.return_value.get_output_in_json.side_effect = [
        {"id": "selected-sub"},
        {"endpoints": {"resourceManager": "https://management.example/"}},
    ]
    error = RuntimeError("preflight failure")
    test.cmd.side_effect = [test.cmd.return_value, test.cmd.return_value, test.cmd.return_value, error]
    with pytest.raises(RuntimeError) as raised:
        scenario.TestADRNamespaceCrud.test_namespace_crud_lifecycle(test)
    assert raised.value is error
    commands = [call.args[0] for call in test.cmd.call_args_list]
    assert commands == [
        "account show --subscription selected-sub", "cloud show",
        "group show -n 'test group' --subscription selected-sub",
        "rest --method get --url 'https://management.example/subscriptions/selected-sub/resourceGroups/test%20group/"
        "providers/Microsoft.DeviceRegistry/namespaces?api-version=selected-api'",
    ]


def test_namespace_name_generation():
    from azext_iot.tests.adr.conftest import generate_adr_namespace_name
    name = generate_adr_namespace_name()
    assert name.startswith("testadr")
    assert len(name) == 15


@pytest.mark.parametrize("adr_group", [None, "", "adr-group"])
def test_adr_resource_group_override_and_fallback(monkeypatch, adr_group):
    from azext_iot.tests.adr import conftest

    monkeypatch.setenv("azext_iot_testrg", "shared-group")
    monkeypatch.delenv("azext_iot_adr_resource_group", raising=False)
    if adr_group is not None:
        monkeypatch.setenv("azext_iot_adr_resource_group", adr_group)
    settings = runpy.run_path(conftest.__file__)
    assert settings["TEST_RG"] == (adr_group or "shared-group")
