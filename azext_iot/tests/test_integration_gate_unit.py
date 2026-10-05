# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from pathlib import Path
import subprocess
import sys
from shutil import which

import pytest
import yaml


VALID_MATRIX_ENTRY = {"service": "DPS", "python": "3.13", "region": "westus"}


@pytest.fixture(scope="module")
def gate_steps():
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "int_test.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert set(workflow["jobs"]["int-test-gate"]["needs"]) == {"setup", "int-test"}
    steps = workflow["jobs"]["int-test-gate"]["steps"]
    return {
        "download": next(step for step in steps if step.get("id") == "download_results"),
        "evaluate": next(step for step in steps if step.get("name") == "Evaluate per-service results"),
        "matrix": next(step for step in workflow["jobs"]["setup"]["steps"] if step.get("id") == "matrix"),
    }


def test_download_outcome_is_exposed_to_gate(gate_steps):
    download = gate_steps["download"]
    evaluate = gate_steps["evaluate"]
    assert evaluate["shell"] == "bash"
    assert download["id"] == "download_results"
    assert download["if"] == "${{ needs.int-test.result != 'skipped' }}"
    assert download["continue-on-error"] is True
    for key, value in {
        "TEST_JOB_RESULT": "${{ needs.int-test.result }}",
        "SETUP_RESULT": "${{ needs.setup.result }}",
        "DOWNLOAD_RESULT": "${{ steps.download_results.outcome }}",
        "EXPECTED_MATRIX": "${{ needs.setup.outputs.matrix }}",
    }.items():
        assert evaluate["env"][key] == value


@pytest.fixture()
def run_workflow_step(gate_steps, tmp_path):
    if sys.platform != "linux":
        pytest.skip("The integration gate runs on Ubuntu")
    if not which("bash") or not which("jq"):
        pytest.skip("The integration gate requires bash and jq")

    def run_step(name, env):
        script = tmp_path / f"{name}.sh"
        script.write_text(gate_steps[name]["run"], encoding="utf-8")
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
            cwd=tmp_path,
            env={
                **os.environ,
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"),
                "GITHUB_OUTPUT": str(tmp_path / "outputs.txt"),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    return run_step


@pytest.mark.parametrize(
    "setup_result, job_result, download_result, expected_services, results, expected_code",
    [
        ("success", "success", "success", ["Hub"], [("Hub", "success")], 0),
        ("success", "failure", "success", ["Hub"], [("Hub", "failure")], 1),
        ("success", "failure", "success", ["Hub", "Hub"], [("Hub", "success"), ("Hub", "failure")], 0),
        ("success", "skipped", "skipped", ["Hub"], [], 0),
        ("failure", "skipped", "skipped", [], [], 1),
        ("skipped", "skipped", "skipped", [], [], 1),
        ("success", "skipped", "skipped", [], [], 1),
        ("success", "success", "success", ["Hub"], [], 1),
        ("success", "failure", "success", ["Hub"], [], 1),
        ("success", "success", "failure", ["Hub"], [("Hub", "success")], 1),
        ("success", "failure", "failure", ["Hub"], [], 1),
        ("success", "success", "success", ["Hub", "DPS"], [("Hub", "success")], 1),
        ("success", "success", "success", ["Hub", "DPS"], [("Hub", "success"), ("Hub", "success")], 1),
        ("success", "success", "success", ["Hub", "DPS"], [("Hub", "success"), ("Other", "success")], 1),
    ],
)
def test_integration_gate_outcomes(
    run_workflow_step, tmp_path, setup_result, job_result, download_result, expected_services, results, expected_code
):
    for index, (service, status) in enumerate(results):
        result_dir = tmp_path / "test-results" / f"test-result-{index}"
        result_dir.mkdir(parents=True)
        for name, value in {
            "service": service,
            "status": status,
            "python": "3.10",
            "region": f"region-{index}",
            "failures": "",
        }.items():
            (result_dir / f"{name}.txt").write_text(value, encoding="utf-8")
    env = {
        "TEST_JOB_RESULT": job_result,
        "SETUP_RESULT": setup_result,
        "DOWNLOAD_RESULT": download_result,
        "EXPECTED_MATRIX": json.dumps([
            {"service": service, "python": "3.10", "region": f"region-{index}"}
            for index, service in enumerate(expected_services)
        ]),
    }

    result = run_workflow_step("evaluate", env)

    assert result.returncode == expected_code, result.stdout + result.stderr


@pytest.mark.parametrize(
    "matrix",
    ["", " ", "not-json", "null", "{}", "[]", "[null]", "[1]", "[true]", '["DPS"]', "[[]]"]
    + [json.dumps([VALID_MATRIX_ENTRY]) + "\n" + json.dumps([VALID_MATRIX_ENTRY])]
    + [json.dumps([VALID_MATRIX_ENTRY, {}]), json.dumps([{}, VALID_MATRIX_ENTRY])]
    + [
        json.dumps([{key: value for key, value in VALID_MATRIX_ENTRY.items() if key != missing}])
        for missing in VALID_MATRIX_ENTRY
    ]
    + [
        json.dumps([{**VALID_MATRIX_ENTRY, field: value}])
        for field in VALID_MATRIX_ENTRY
        for value in (None, "", " ", "\t", 0, False, [], {})
    ],
)
def test_integration_gate_rejects_invalid_matrix(run_workflow_step, tmp_path, matrix):
    result = run_workflow_step("evaluate", {
        "SETUP_RESULT": "success",
        "TEST_JOB_RESULT": "skipped",
        "DOWNLOAD_RESULT": "skipped",
        "EXPECTED_MATRIX": matrix,
    })

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Expected a valid, nonempty integration test matrix" in result.stdout
    assert "### Invalid integration test matrix" in (tmp_path / "summary.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "services, python_versions, regions, expected_jobs",
    [
        ("DPS", "3.13", "westus", 1),
        ("DPS,ADR", "3.10,3.13", "westus,eastus", 8),
        ("Unknown,DPS", "3.13", "westus", 1),
        ("Unknown", "3.13", "westus", 0),
        ("DPS", " ", "westus", 0),
        ("DPS", "3.13", " ", 0),
        ("DPS", "", "westus", 0),
    ],
)
def test_matrix_setup_rejects_empty_selections(
    run_workflow_step, tmp_path, services, python_versions, regions, expected_jobs
):
    result = run_workflow_step("matrix", {
        "INPUT_SERVICES": services,
        "INPUT_PYTHON_VERSIONS": python_versions,
        "INPUT_REGIONS": regions,
        "INPUT_TEST_DPS": "false",
        "INPUT_TEST_HUB_MGMT": "false",
        "INPUT_TEST_HUB_DATA": "false",
        "INPUT_TEST_ADU": "false",
        "INPUT_TEST_ADR": "false",
    })

    if not expected_jobs:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "::error::" in result.stdout
        assert not (tmp_path / "outputs.txt").exists()
        return

    assert result.returncode == 0, result.stdout + result.stderr
    output = (tmp_path / "outputs.txt").read_text(encoding="utf-8")
    assert output.startswith("matrix=")
    matrix = output.removeprefix("matrix=").strip()
    assert len(json.loads(matrix)) == expected_jobs
    gate_result = run_workflow_step("evaluate", {
        "SETUP_RESULT": "success",
        "TEST_JOB_RESULT": "skipped",
        "DOWNLOAD_RESULT": "skipped",
        "EXPECTED_MATRIX": matrix,
    })
    assert gate_result.returncode == 0, gate_result.stdout + gate_result.stderr
