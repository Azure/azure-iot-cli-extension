# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

from pathlib import Path
import json
import runpy

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATE = runpy.run_path(str(REPOSITORY_ROOT / "scripts" / "evaluate_test_results.py"))["evaluate_results"]
MATRIX = [{"service": "ADR", "python": "3.13", "region": "centraluseuap"}]
SUCCESSFUL_JOBS = {
    "setup": "success",
    "unit-test": "success",
    "int-test": "success",
    "gate preparation": "success",
}


def _result(path, config=None, status="success", failures=""):
    path.mkdir(parents=True, exist_ok=True)
    for field, value in (config or MATRIX[0]).items():
        (path / f"{field}.txt").write_text(value, encoding="utf-8")
    (path / "status.txt").write_text(status, encoding="utf-8")
    (path / "failures.txt").write_text(failures, encoding="utf-8")


@pytest.mark.parametrize("layout", ["", "test-result-ADR-py3.13-centraluseuap"])
@pytest.mark.parametrize("status", ["success", "failure", "cancelled", "skipped", ""])
def test_workflow_gate_handles_single_and_multiple_artifact_layouts(tmp_path, layout, status):
    _result(tmp_path / layout, status=status)
    summary, errors = EVALUATE(tmp_path, MATRIX, SUCCESSFUL_JOBS)
    assert bool(errors) == (status != "success")
    assert ("### Passed" in summary) == (status == "success")


def test_workflow_gate_requires_every_combination_to_pass(tmp_path):
    other = dict(MATRIX[0], python="3.12")
    _result(tmp_path / "passing")
    _result(tmp_path / "failing", other, status="failure")
    _, errors = EVALUATE(tmp_path, MATRIX + [other], SUCCESSFUL_JOBS)
    assert any("3.12" in error and "did not succeed" in error for error in errors)


@pytest.mark.parametrize("present", [False, True])
def test_workflow_gate_rejects_missing_artifacts(tmp_path, present):
    other = dict(MATRIX[0], service="DPS")
    if present:
        _result(tmp_path / "adr")
    _, errors = EVALUATE(tmp_path, MATRIX + [other], SUCCESSFUL_JOBS)
    assert any("Missing result for DPS" in error for error in errors)


@pytest.mark.parametrize("job", list(SUCCESSFUL_JOBS))
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", ""])
def test_workflow_gate_does_not_mask_other_step_or_job_failures(tmp_path, job, status):
    _result(tmp_path)
    _, errors = EVALUATE(tmp_path, MATRIX, dict(SUCCESSFUL_JOBS, **{job: status}))
    assert any(f"Job '{job}' did not succeed" in error for error in errors)


def test_workflow_gate_rejects_duplicate_and_unexpected_results(tmp_path):
    _result(tmp_path / "first")
    _result(tmp_path / "duplicate")
    _result(tmp_path / "unexpected", dict(MATRIX[0], service="DPS"))
    _, errors = EVALUATE(tmp_path, MATRIX, SUCCESSFUL_JOBS)
    assert any("Duplicate result" in error for error in errors)
    assert any("Unexpected result" in error for error in errors)


def test_workflow_gate_rejects_incomplete_metadata(tmp_path):
    _result(tmp_path)
    (tmp_path / "service.txt").unlink()
    _, errors = EVALUATE(tmp_path, MATRIX, SUCCESSFUL_JOBS)
    assert any("Invalid result artifact" in error for error in errors)
    assert any("Missing result" in error for error in errors)


def test_workflow_gate_rejects_success_with_failed_tests(tmp_path):
    _result(tmp_path, failures="azext_iot/tests/adr/example.py::test_failed")
    summary, errors = EVALUATE(tmp_path, MATRIX, SUCCESSFUL_JOBS)
    assert any("contains failed tests" in error for error in errors)
    assert "example.py::test_failed" in summary


@pytest.mark.parametrize("matrix", [[], MATRIX + MATRIX])
def test_workflow_gate_rejects_empty_or_duplicate_matrix(tmp_path, matrix):
    _, errors = EVALUATE(tmp_path, matrix, SUCCESSFUL_JOBS)
    assert errors


@pytest.mark.parametrize("status,exit_code", [("success", 0), ("failure", 1), (None, 1)])
def test_workflow_gate_command_exit_status_and_summary(tmp_path, monkeypatch, status, exit_code):
    results = tmp_path / "results"
    if status is not None:
        _result(results, status=status)
    summary = tmp_path / "summary.txt"
    for key, value in {
        "INTEGRATION_MATRIX": json.dumps(MATRIX),
        "SETUP_RESULT": "success",
        "UNIT_TEST_RESULT": "success",
        "INTEGRATION_RESULT": "success",
        "GATE_JOB_RESULT": "success",
        "GITHUB_STEP_SUMMARY": str(summary),
    }.items():
        monkeypatch.setenv(key, value)
    script = str(REPOSITORY_ROOT / "scripts" / "evaluate_test_results.py")
    monkeypatch.setattr("sys.argv", [script, "--results-dir", str(results)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(script, run_name="__main__")
    assert error.value.code == exit_code
    assert ("### Passed" in summary.read_text(encoding="utf-8")) == (exit_code == 0)


def test_workflow_failure_propagation_is_wired():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert not jobs["int-test"].get("continue-on-error", False)
    assert jobs["int-test"]["strategy"]["fail-fast"] is False
    gate = jobs["int-test-gate"]
    assert set(gate["needs"]) == {"setup", "unit-test", "int-test"}
    assert not any(step.get("continue-on-error", False) for step in gate["steps"])
    evaluation = next(step for step in gate["steps"] if step["name"] == "Evaluate per-service results")
    assert "scripts/evaluate_test_results.py" in evaluation["run"]
    assert "needs.int-test.result" in evaluation["env"]["INTEGRATION_RESULT"]
    assert "needs.setup.outputs.matrix" in evaluation["env"]["INTEGRATION_MATRIX"]
    assert "job.status" in evaluation["env"]["GATE_JOB_RESULT"]
    summaries = [step for step in jobs["combine-coverage"]["steps"] if step["name"] == "Write job summary"]
    assert summaries[0] is jobs["combine-coverage"]["steps"][-1]
    assert "job.status" in summaries[0]["env"]["COVERAGE_RESULT"]
