# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import io
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
    with monkeypatch.context() as context:
        if pretty:
            context.setenv("PRETTY_LOG", "1")
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
    with monkeypatch.context() as context:
        if value is not None:
            context.setenv("PRETTY_LOG", value)
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
    report = SimpleNamespace(
        when="call",
        nodeid="test_example_int.py::TestExample::test_example",
        passed=outcome == "passed",
        failed=outcome == "failed",
        longreprtext=reason,
    )

    with monkeypatch.context() as context:
        context.setenv("PRETTY_LOG", "1")
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
    report = SimpleNamespace(
        when=when,
        nodeid="test_example_int.py::TestExample::test_example",
        passed=outcome == "passed",
        failed=outcome == "failed",
    )

    with monkeypatch.context() as context:
        context.setenv("PRETTY_LOG", pretty)
        pytest_runtest_logreport(report)

    assert not capsys.readouterr().out


def test_namespace_lifecycle_logging_preserves_ignite_commands(
    caplog, mocker
):
    from azext_iot.tests.adr import test_adr_namespace_crud_int as scenario

    test = object.__new__(scenario.TestADRNamespaceCrud)
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
        "properties": {
            "provisioningState": "Succeeded",
            "observability": {"enabled": False},
        },
    }
    execution.return_value.assert_with_checks.return_value.get_output_in_json.side_effect = [
        created,
        created,
        created,
        {"tags": {"env": "test", "purpose": "ci"}},
        {"tags": {"owner": "adr-tests"}},
    ]

    with patch.object(
        scenario, "generate_adr_namespace_name", return_value=namespace_name
    ):
        scenario.TestADRNamespaceCrud.test_namespace_crud_lifecycle(test)

    commands = [call.args[0] for call in test.cmd.call_args_list]
    assert commands[0] == (
        f"iot adr ns create -n {namespace_name} -g {scenario.TEST_RG} "
        f"--location {scenario.TEST_LOCATION} --no-wait"
    )
    assert commands[1] == (
        f"iot adr ns wait -n {namespace_name} -g {scenario.TEST_RG}"
    )
    assert not any("--messaging-endpoints" in command for command in commands)
    assert caplog.messages[0] == "\u25b6 TEST: test_namespace_crud_lifecycle"
    command_logs = [
        message
        for message in caplog.messages
        if message.startswith("  \u203a az ")
    ]
    assert len(command_logs) == len(commands)
    durations = [
        message
        for message in caplog.messages
        if message.startswith("  \u0394 (")
    ]
    assert len(commands) == 12
    assert commands[-2] == (
        f"iot adr ns wait -n {namespace_name} -g {scenario.TEST_RG} "
        "--deleted"
    )
    assert [
        index
        for index, call in enumerate(test.cmd.call_args_list)
        if call.kwargs
    ] == [4, 8, 11]
    assert all(
        call.kwargs == {"expect_failure": True}
        for call in test.cmd.call_args_list
        if call.kwargs
    )
    assert len(durations) == 4
    assert "  \u2713 Namespace deleted" in caplog.messages


@pytest.mark.parametrize(
    "method_name,list_command",
    [
        ("test_namespace_list_by_resource_group", "iot adr ns list -g test-rg"),
        ("test_namespace_list_by_subscription", "iot adr ns list"),
    ],
)
def test_namespace_list_scenarios_preserve_both_scopes(method_name, list_command, mocker):
    from azext_iot.tests.adr import test_adr_namespace_crud_int as scenario

    test = object.__new__(scenario.TestADRNamespaceCrud)
    test._testMethodName = method_name
    test.kwargs = {}
    test.cli_ctx = Mock()
    test.cmd = Mock(wraps=test.cmd)
    mocker.patch.object(scenario, "TEST_RG", "test-rg")
    mocker.patch.object(scenario, "TEST_SUBSCRIPTION", None)
    mocker.patch.object(scenario, "generate_adr_namespace_name", return_value="test-namespace")
    execution = mocker.patch("azure.cli.testsdk.base.execute", autospec=True)
    execution.return_value.assert_with_checks.return_value.get_output_in_json.return_value = [
        {"name": "test-namespace"}
    ]

    getattr(test, method_name)()

    commands = [call.args[0].strip() for call in test.cmd.call_args_list]
    assert len(commands) == 3
    assert commands[1] == list_command
    assert commands[2] == "iot adr ns delete -n test-namespace -g test-rg --yes"


def test_timestamp_is_utc():
    assert len(log._ts()) == 8


@pytest.mark.parametrize("pretty", [False, True])
def test_raw_log_with_and_without_arguments(pretty, monkeypatch, caplog, capsys):
    with monkeypatch.context() as context:
        context.setenv("PRETTY_LOG", "1" if pretty else "0")
        log._raw_log()
        log._raw_log("literal")
        log._raw_log("value %s", "example")
    if pretty:
        assert capsys.readouterr().out == "\nliteral\nvalue example\n"
    else:
        assert caplog.messages == ["literal", "value example"]


def test_pretty_log_without_color(monkeypatch, capsys):
    with monkeypatch.context() as context:
        context.setenv("PRETTY_LOG", "1")
        context.setitem(log._STYLES, "plain", ("prefix ", "missing"))
        log._log("plain", "value")
    assert capsys.readouterr().out == "prefix value\n"


def test_pretty_step_without_arguments(monkeypatch, capsys):
    with monkeypatch.context() as context:
        context.setenv("PRETTY_LOG", "1")
        with patch.object(log, "_ts", return_value="17:21:30"):
            log._log(log.LogKind.STEP, "Step")
    assert "Step \u00b7 17:21:30" in capsys.readouterr().out


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "ascii"])
@pytest.mark.parametrize("raw", [False, True])
def test_pretty_output_respects_stream_encoding(encoding, raw, monkeypatch):
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding=encoding, errors="strict", newline="\n") as stream:
        with monkeypatch.context() as context:
            context.setenv("PRETTY_LOG", "1")
            context.setattr(log.sys, "stdout", stream)
            if raw:
                log._raw_log("value %s", "\u2713 caf\u00e9")
                text = "value \u2713 caf\u00e9\n"
            else:
                log._log(log.LogKind.OK, "value %s", "caf\u00e9")
                text = f"{log._ANSI['sage']}  \u2713 value caf\u00e9{log._ANSI_RESET}\n"
        # No explicit flush here: the logger must flush before returning.
        assert buffer.getvalue() == text.encode(encoding, errors="backslashreplace")


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_pretty_report_hook_on_cp1252_stream(outcome, monkeypatch):
    report = SimpleNamespace(
        when="call",
        nodeid="test_example_int.py::TestExample::test_example",
        passed=outcome == "passed",
        failed=outcome == "failed",
        longreprtext="AssertionError: caf\u00e9",
    )
    buffer = io.BytesIO()
    with io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", newline="\n") as stream:
        with monkeypatch.context() as context:
            context.setenv("PRETTY_LOG", "1")
            context.setattr(log.sys, "stdout", stream)
            pytest_runtest_logreport(report)
        first_report = buffer.getvalue()
        # The test's own call report runs before fixture teardown. Pretty mode
        # must already be restored, not just restored by monkeypatch teardown.
        with monkeypatch.context() as context:
            context.setattr(log.sys, "stdout", stream)
            pytest_runtest_logreport(report)
        assert buffer.getvalue() == first_report
    if outcome == "passed":
        expected = f"{log._ANSI['sage']}\\u2713 PASS test_example{log._ANSI_RESET}\n"
    else:
        expected = (
            f"{log._ANSI['terra']}\\u2717 FAIL test_example"
            f" -- AssertionError: caf\u00e9{log._ANSI_RESET}\n"
        )
    assert first_report == expected.encode("cp1252")


@pytest.mark.parametrize("encoding", [None, "missing"])
def test_pretty_output_without_stream_encoding(encoding, monkeypatch):
    output = io.StringIO()
    stream = SimpleNamespace(write=output.write, flush=Mock())
    if encoding is None:
        stream.encoding = None
    with monkeypatch.context() as context:
        context.setattr(log.sys, "stdout", stream)
        log._print_pretty("\u2713 caf\u00e9")
    assert output.getvalue() == "\u2713 caf\u00e9\n"
    stream.flush.assert_called_once_with()


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("error", [
    BrokenPipeError("closed pipe"),
    OSError("output unavailable"),
    UnicodeEncodeError("utf-8", "x", 0, 1, "synthetic stream failure"),
])
def test_pretty_output_does_not_retry_stream_errors(operation, error, monkeypatch):
    stream = SimpleNamespace(encoding="utf-8", write=Mock(), flush=Mock())
    getattr(stream, operation).side_effect = error
    with monkeypatch.context() as context:
        context.setattr(log.sys, "stdout", stream)
        with pytest.raises(type(error)) as raised:
            log._print_pretty("\u2713")
    assert raised.value is error
    if operation == "write":
        stream.write.assert_called_once_with("\u2713")
        stream.flush.assert_not_called()
    else:
        assert stream.write.call_count == 2  # text and newline, with no retry
        stream.flush.assert_called_once_with()


def test_pretty_output_rejects_invalid_encoding_before_writing(monkeypatch):
    stream = SimpleNamespace(encoding="not-a-real-codec", write=Mock(), flush=Mock())
    with monkeypatch.context() as context:
        context.setattr(log.sys, "stdout", stream)
        with pytest.raises(LookupError):
            log._print_pretty("\u2713")
    stream.write.assert_not_called()
    stream.flush.assert_not_called()


def test_namespace_name_generation():
    from azext_iot.tests.adr.conftest import generate_adr_namespace_name
    name = generate_adr_namespace_name()
    assert name.startswith("testadr")
    assert len(name) == 15


@pytest.mark.parametrize(
    "adr_group,expected",
    [
        (None, "cli-int-test-rg"),
        ("", ""),
        ("adr-group", "adr-group"),
    ],
)
def test_adr_resource_group_preserves_ignite_default(
    monkeypatch, adr_group, expected
):
    from azext_iot.tests.adr import conftest

    monkeypatch.setenv("azext_iot_testrg", "shared-group")
    monkeypatch.delenv("azext_iot_adr_resource_group", raising=False)
    if adr_group is not None:
        monkeypatch.setenv("azext_iot_adr_resource_group", adr_group)
    settings = runpy.run_path(conftest.__file__)
    assert settings["TEST_RG"] == expected
