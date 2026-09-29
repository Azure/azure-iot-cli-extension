# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import textwrap
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
import yaml

from azext_iot.tests._integration_progress import IntegrationProgress
from azext_iot.tests._integration_results import IntegrationResults


ROOT = Path(__file__).resolve().parents[2]
NODE = "test_sample_int.py::test_example"
SECRET = "secret-bearing-parameter-and-error"


def _report(writer, nodeid=NODE, when="call", outcome="passed"):
    writer.report(SimpleNamespace(
        nodeid=nodeid, when=when, outcome=outcome, duration=1.2345,
        longreprtext=SECRET, sections=[("Captured output", SECRET)],
    ))


def _read(directory):
    return json.loads((directory / "integration-outcomes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("failed_phase", ["setup", "call", "teardown"])
def test_phase_failures_survive_before_session_exit_without_secret_errors(tmp_path, failed_phase):
    writer = IntegrationResults(tmp_path)
    nodeid = NODE + "[" + SECRET + "]"
    writer.select([nodeid, NODE + "_later"])
    writer.start(nodeid)
    for phase in ("setup", "call", "teardown"):
        _report(writer, nodeid, phase, "failed" if phase == failed_phase else "passed")
        if phase == failed_phase:
            receipt = _read(tmp_path)
            assert receipt["cases"][0]["status"] == "failed"
            assert not receipt["session_finished"]
            assert "failed phase(s): " + phase in (tmp_path / "failures.txt").read_text()
    receipt = _read(tmp_path)
    assert receipt["cases"][1]["status"] == "not_started"
    for path in tmp_path.iterdir():
        assert SECRET not in path.read_text()
        assert "Captured output" not in path.read_text()
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600


def test_parameter_cases_keep_distinct_ordinals_without_retaining_parameter_ids(tmp_path):
    writer = IntegrationResults(tmp_path)
    nodes = [NODE + "[first-secret]", NODE + "[second-secret]"]
    writer.select(nodes)
    for node in nodes:
        writer.start(node)
        for phase in ("setup", "call", "teardown"):
            _report(writer, node, phase)
    assert "incomplete" in (tmp_path / "failures.txt").read_text()
    writer.finish(0)
    receipt = _read(tmp_path)
    assert receipt["selected"] == 2 and receipt["session_finished"]
    assert [case["case"] for case in receipt["cases"]] == [1, 2]
    assert [case["nodeid"] for case in receipt["cases"]] == [NODE, NODE]
    assert all(case["status"] == "passed" and case["complete"] for case in receipt["cases"])
    assert (tmp_path / "failures.txt").read_text() == ""
    assert "secret" not in (tmp_path / "integration-outcomes.json").read_text()


@pytest.mark.parametrize("skip_phase", ["setup", "call"])
def test_setup_and_call_skips_are_distinguished_from_passed_coverage(tmp_path, skip_phase):
    writer = IntegrationResults(tmp_path)
    writer.select([NODE])
    writer.start(NODE)
    _report(writer, when="setup", outcome="skipped" if skip_phase == "setup" else "passed")
    if skip_phase == "call":
        _report(writer, when="call", outcome="skipped")
    _report(writer, when="teardown")
    writer.finish(0)
    case = _read(tmp_path)["cases"][0]
    assert case["complete"] and case["status"] == "skipped"
    assert (tmp_path / "failures.txt").read_text() == ""


@pytest.mark.parametrize("state", ["no-selection", "not-started", "setup-only", "call-only", "collection-error", "rerun"])
def test_premature_or_unsuccessful_exit_cannot_clear_failure_evidence(tmp_path, state):
    writer = IntegrationResults(tmp_path)
    if state != "no-selection":
        writer.select([NODE])
    if state in {"setup-only", "call-only", "rerun"}:
        writer.start(NODE)
        _report(writer, when="setup")
    if state in {"call-only", "rerun"}:
        _report(writer, outcome="rerun" if state == "rerun" else "passed")
    writer.finish(2 if state == "collection-error" else 0)
    assert (tmp_path / "failures.txt").read_text()
    assert not any(case["status"] == "passed" for case in _read(tmp_path)["cases"])


def test_relative_directory_survives_integration_fixture_chdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writer = IntegrationResults("results")
    writer.select([NODE])
    child = tmp_path / "fixture-cwd"
    child.mkdir()
    monkeypatch.chdir(child)
    writer.start(NODE)
    assert _read(tmp_path / "results")["cases"][0]["started"]
    assert not (child / "results").exists()


def test_receipt_replacement_does_not_clear_incomplete_marker_before_terminal_json(tmp_path, monkeypatch):
    writer = IntegrationResults(tmp_path)
    writer.select([NODE])
    for phase in ("setup", "call", "teardown"):
        _report(writer, when=phase)
    original = writer._write

    def fail(name, text):
        if name == "integration-outcomes.json":
            raise OSError("simulated interruption before atomic replace")
        original(name, text)

    monkeypatch.setattr(writer, "_write", fail)
    with pytest.raises(OSError):
        writer.finish(0)
    assert not _read(tmp_path)["session_finished"]
    assert "incomplete" in (tmp_path / "failures.txt").read_text()


def test_receipts_work_without_terminal_reporter_or_heartbeat(tmp_path, mocker):
    config = SimpleNamespace(pluginmanager=mocker.Mock())
    config.pluginmanager.getplugin.return_value = None
    plugin = IntegrationProgress(config, 0, results_dir=tmp_path)
    plugin.pytest_sessionstart()
    plugin.pytest_collection_finish(SimpleNamespace(items=[
        SimpleNamespace(nodeid=NODE), SimpleNamespace(nodeid="test_sample_unit.py::test_unit"),
    ]))
    plugin.pytest_runtest_logstart(NODE)
    plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=NODE, when="setup", outcome="passed", duration=0))
    plugin.pytest_runtest_logstart("test_sample_unit.py::test_unit")
    receipt = _read(tmp_path)
    assert receipt["selected"] == 1 and receipt["cases"][0]["status"] == "incomplete"
    plugin.pytest_unconfigure()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_terminal_receipt_waits_for_session_cleanup_hooks(tmp_path, mocker, cleanup_fails):
    plugin = IntegrationProgress(SimpleNamespace(pluginmanager=mocker.Mock()), 0, results_dir=tmp_path)
    plugin.pytest_sessionstart()
    plugin.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=NODE)]))
    plugin.pytest_runtest_logstart(NODE)
    for phase in ("setup", "call", "teardown"):
        plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=NODE, when=phase, outcome="passed", duration=0))

    class Cleanup:
        @pytest.hookimpl(trylast=True)
        def pytest_sessionfinish(self):
            assert not _read(tmp_path)["session_finished"]
            if cleanup_fails:
                raise RuntimeError(SECRET)

    manager = pytest.PytestPluginManager()
    manager.register(plugin)
    manager.register(Cleanup())
    if cleanup_fails:
        with pytest.raises(RuntimeError):
            manager.hook.pytest_sessionfinish(session=None, exitstatus=0)
    else:
        manager.hook.pytest_sessionfinish(session=None, exitstatus=0)
    assert _read(tmp_path)["session_finished"]
    assert _read(tmp_path)["exit_code"] == (3 if cleanup_fails else 0)
    failures = (tmp_path / "failures.txt").read_text()
    assert bool(failures) == cleanup_fails and SECRET not in failures


def test_incremental_option_rejects_parallel_writers_before_starting_pytest(mocker):
    from azext_iot.tests.conftest import pytest_configure

    options = {"integration_progress_interval": 0, "integration_results_dir": "results", "numprocesses": 2}
    config = SimpleNamespace(getoption=lambda name, **_: options[name], pluginmanager=mocker.Mock())
    with pytest.raises(pytest.UsageError, match="requires serial"):
        pytest_configure(config)
    config.pluginmanager.register.assert_not_called()


def _record_step():
    workflow = yaml.safe_load((ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    return next(step for step in workflow["jobs"]["int-test"]["steps"] if step["name"] == "Record test result")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "windows-crlf"])
def test_record_step_reads_utf8_workflow_under_windows_default_encoding(tmp_path, monkeypatch, newline):
    relative = ".github/workflows/int_test.yml"
    source = (ROOT / relative).read_text(encoding="utf-8")
    workflow = tmp_path / relative
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(source.replace("\n", newline).encode("utf-8"))

    def windows_read_text(path, encoding=None, errors=None, **kwargs):
        # Reproduce Windows' non-UTF-8 default on every test platform.
        with path.open(encoding=encoding or "cp1252", errors=errors, **kwargs) as stream:
            return stream.read()

    monkeypatch.setattr(Path, "read_text", windows_read_text)
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    # The actual workflow contains box-drawing text that CP1252 cannot decode.
    with pytest.raises(UnicodeDecodeError):
        workflow.read_text()
    step = _record_step()
    assert step["name"] == "Record test result"
    assert step["if"] == "${{ always() }}"
    assert "ADR incremental test evidence is missing" in step["run"]


@pytest.mark.skipif(sys.platform != "linux", reason="Executes the Ubuntu workflow record step.")
@pytest.mark.parametrize("receipt", ["failed", "cancelled", "missing", "passed", "not-started", "no-selection"])
def test_actual_workflow_record_step_preserves_incremental_adr_evidence(tmp_path, receipt):
    directory = tmp_path / "test-result"
    if receipt != "missing":
        writer = IntegrationResults(directory)
        if receipt != "no-selection":
            writer.select([NODE])
        if receipt not in ("not-started", "no-selection"):
            writer.start(NODE)
            for phase in ("setup", "call", "teardown"):
                _report(writer, when=phase, outcome="failed" if receipt == "failed" and phase == "call" else "passed")
        if receipt != "cancelled":
            writer.finish(1 if receipt == "failed" else 0)
    (tmp_path / "test-output.log").write_text("No final pytest summary was emitted.\n")
    status = {"failed": "failure", "cancelled": "cancelled"}.get(receipt, "success")
    result = subprocess.run(
        ["bash", "-c", _record_step()["run"]], cwd=tmp_path,
        env=dict(os.environ, TEST_SERVICE="ADR", TEST_STATUS=status, TEST_PYTHON="3.13", TEST_REGION="centraluseuap"),
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    failures = (directory / "failures.txt").read_text()
    assert bool(failures) == (receipt != "passed")
    if receipt == "failed":
        assert "failed phase(s): call" in failures
    elif receipt == "cancelled":
        assert "session incomplete" in failures
    elif receipt == "missing":
        assert "missing" in failures
    assert (directory / "status.txt").read_text().strip() == status
    evaluate = runpy.run_path(str(ROOT / "azext_iot/tests/_evaluate_test_results.py"))["evaluate_results"]
    summary, errors = evaluate(
        directory, [{"service": "ADR", "python": "3.13", "region": "centraluseuap"}],
        {"setup": "success", "unit-test": "success", "int-test": "success", "gate preparation": "success"},
    )
    assert bool(errors) == (receipt != "passed")
    assert ("### Passed" in summary) == (receipt == "passed")


def test_only_adr_tox_enables_incremental_serial_receipts():
    text = (ROOT / "tox.ini").read_text()
    enabled = [line.strip() for line in text.splitlines() if "--integration-results-dir" in line]
    assert enabled == ["ADR:    -n 0 -p no:rerunfailures --integration-results-dir={toxinidir}/test-result \\"]
    assert _record_step()["if"] == "${{ always() }}"


@pytest.mark.skipif(sys.platform != "linux", reason="Verifies abrupt Linux process cancellation without sessionfinish.")
def test_killed_serial_pytest_retains_failed_active_and_unstarted_cases(tmp_path):
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    test_file = tmp_path / "test_cancel_int.py"
    test_file.write_text(textwrap.dedent(f"""
        from pathlib import Path
        import time
        import pytest

        @pytest.mark.parametrize("token", ["{SECRET}"])
        def test_first(token):
            raise RuntimeError(token)

        def test_second():
            Path("entered").touch()
            time.sleep(60)

        def test_third():
            pass
    """))
    directory = tmp_path / "results"
    environment = dict(
        os.environ, AZURE_TEST_RUN_LIVE="False", azext_iot_testrg="unit-test-rg",
        PYTHONPATH=os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH")))),
    )
    command = [
        sys.executable, "-m", "pytest", "-c", str(config), "--rootdir", str(tmp_path),
        "-p", "azext_iot.tests.conftest", "-p", "no:rerunfailures",
        "--integration-results-dir", str(directory), str(test_file),
    ]
    with subprocess.Popen(
        command, cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ) as process:
        try:
            deadline = monotonic() + 25
            while not (tmp_path / "entered").exists() and process.poll() is None and monotonic() < deadline:
                sleep(0.05)
            assert (tmp_path / "entered").exists(), "Child did not reach the deliberately blocked call"
        finally:
            process.kill()
            process.communicate(timeout=10)
    receipt = _read(directory)
    assert receipt["selected"] == 3 and not receipt["session_finished"]
    assert [case["status"] for case in receipt["cases"]] == ["failed", "incomplete", "not_started"]
    assert receipt["cases"][0]["complete"] and not receipt["cases"][1]["complete"]
    failures = (directory / "failures.txt").read_text()
    assert "test_first" in failures and "failed phase(s): call" in failures
    assert "test_second" in failures and "test_third" in failures
    assert SECRET not in failures and SECRET not in (directory / "integration-outcomes.json").read_text()
