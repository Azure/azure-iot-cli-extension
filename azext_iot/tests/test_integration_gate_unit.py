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
import shlex

import pytest
import yaml


VALID_MATRIX_ENTRY = {"service": "DPS", "python": "3.13", "region": "westus"}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def gate_steps():
    workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "int_test.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert set(workflow["jobs"]["int-test-gate"]["needs"]) == {"setup", "unit-test", "int-test"}
    steps = workflow["jobs"]["int-test-gate"]["steps"]
    return {
        "download": next(step for step in steps if step.get("name") == "Download all test results"),
        "evaluate": next(step for step in steps if step.get("name") == "Evaluate per-service results"),
        "matrix": next(step for step in workflow["jobs"]["setup"]["steps"] if step.get("id") == "matrix"),
    }


def test_download_failure_cannot_be_ignored_by_gate(gate_steps):
    download = gate_steps["download"]
    evaluate = gate_steps["evaluate"]
    assert not download.get("continue-on-error", False)
    assert evaluate["if"] == "${{ always() }}"
    assert "_evaluate_test_results.py" in evaluate["run"]
    for key, value in {
        "INTEGRATION_RESULT": "${{ needs.int-test.result }}",
        "SETUP_RESULT": "${{ needs.setup.result }}",
        "UNIT_TEST_RESULT": "${{ needs.unit-test.result }}",
        "GATE_JOB_RESULT": "${{ job.status }}",
        "INTEGRATION_MATRIX": "${{ needs.setup.outputs.matrix || '[]' }}",
    }.items():
        assert evaluate["env"][key] == value


@pytest.fixture()
def run_workflow_step(gate_steps, tmp_path):
    if sys.platform != "linux":
        pytest.skip("The integration gate runs on Ubuntu")
    if not which("bash") or not which("jq"):
        pytest.skip("The integration gate requires bash and jq")

    def run_step(name, env):
        if name == "evaluate":
            command = shlex.split(gate_steps[name]["run"])
            command[:2] = [sys.executable, str(REPOSITORY_ROOT / command[1])]
            cwd = tmp_path
        else:
            command = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", gate_steps[name]["run"]]
            cwd = REPOSITORY_ROOT
        return subprocess.run(
            command,
            cwd=cwd,
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
        ("success", "success", "success", ["ADR"], [("ADR", "success")], 0),
        ("success", "failure", "success", ["ADR"], [("ADR", "failure")], 1),
        ("success", "failure", "success", ["ADR", "ADR"], [("ADR", "success"), ("ADR", "failure")], 1),
        ("success", "skipped", "skipped", ["ADR"], [], 1),
        ("failure", "skipped", "skipped", [], [], 1),
        ("skipped", "skipped", "skipped", [], [], 1),
        ("success", "skipped", "skipped", [], [], 1),
        ("success", "success", "success", ["ADR"], [], 1),
        ("success", "failure", "success", ["ADR"], [], 1),
        ("success", "success", "failure", ["ADR"], [("ADR", "success")], 1),
        ("success", "failure", "failure", ["ADR"], [], 1),
        ("success", "success", "success", ["ADR", "ADU"], [("ADR", "success")], 1),
        ("success", "success", "success", ["ADR", "ADU"], [("ADR", "success"), ("ADR", "success")], 1),
        ("success", "success", "success", ["ADR", "ADU"], [("ADR", "success"), ("Other", "success")], 1),
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
        "INTEGRATION_RESULT": job_result,
        "SETUP_RESULT": setup_result,
        "UNIT_TEST_RESULT": "success",
        "GATE_JOB_RESULT": download_result,
        "INTEGRATION_MATRIX": json.dumps([
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
        "UNIT_TEST_RESULT": "success",
        "INTEGRATION_RESULT": "success",
        "GATE_JOB_RESULT": "success",
        "INTEGRATION_MATRIX": matrix,
    })

    assert result.returncode == 1, result.stdout + result.stderr
    assert any(message in result.stdout + result.stderr for message in (
        "JSONDecodeError",
        "INTEGRATION_MATRIX must be a JSON array",
        "Each test combination requires a service, Python version, and region",
        "No integration test combinations were scheduled",
    ))
    assert "### Passed" not in result.stdout


@pytest.mark.parametrize(
    "services, python_versions, regions, expected_jobs",
    [
        ("DPS", "3.13", "westus", 1),
        ("DPS,ADR", "3.10,3.13", "westus,eastus", 8),
        ("Unknown,DPS", "3.13", "westus", 0),
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
        "INPUT_TEST_HUB_CONTROL": "false",
        "INPUT_TEST_HUB_DATA": "false",
        "INPUT_TEST_ADU": "false",
        "INPUT_TEST_ADR": "false",
        "INPUT_ARM_ENDPOINT": "public",
        "TEST_SUBSCRIPTION_ID": "a386d5ea-ea90-441a-8263-d816368c84a1",
        "RESOURCE_GROUP": "cli-int-test-rg",
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
        "UNIT_TEST_RESULT": "success",
        "INTEGRATION_RESULT": "skipped",
        "GATE_JOB_RESULT": "success",
        "INTEGRATION_MATRIX": matrix,
    })
    assert gate_result.returncode == 1, gate_result.stdout + gate_result.stderr
    assert "Job 'int-test' did not succeed: skipped" in gate_result.stdout
