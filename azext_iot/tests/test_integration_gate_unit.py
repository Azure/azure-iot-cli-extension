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

import pytest
import yaml


@pytest.fixture(scope="module")
def gate_steps():
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "int_test.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert workflow["jobs"]["int-test-gate"]["needs"] == ["setup", "int-test"]
    return workflow["jobs"]["int-test-gate"]["steps"]


def test_download_outcome_is_exposed_to_gate(gate_steps):
    download, evaluate = gate_steps
    assert download["id"] == "download_results"
    assert download["if"] == "${{ needs.int-test.result != 'skipped' }}"
    assert download["continue-on-error"] is True
    assert evaluate["env"] == {
        "TEST_JOB_RESULT": "${{ needs.int-test.result }}",
        "DOWNLOAD_RESULT": "${{ steps.download_results.outcome }}",
        "EXPECTED_MATRIX": "${{ needs.setup.outputs.matrix }}",
    }


@pytest.mark.skipif(sys.platform != "linux", reason="The integration gate runs on Ubuntu")
@pytest.mark.parametrize(
    "job_result, download_result, expected_services, results, expected_code",
    [
        ("success", "success", ["Hub"], [("Hub", "success")], 0),
        ("failure", "success", ["Hub"], [("Hub", "failure")], 1),
        ("failure", "success", ["Hub", "Hub"], [("Hub", "success"), ("Hub", "failure")], 0),
        ("skipped", "skipped", [], [], 0),
        ("success", "success", ["Hub"], [], 1),
        ("failure", "success", ["Hub"], [], 1),
        ("success", "failure", ["Hub"], [("Hub", "success")], 1),
        ("failure", "failure", ["Hub"], [], 1),
        ("success", "success", ["Hub", "DPS"], [("Hub", "success")], 1),
        ("success", "success", ["Hub", "DPS"], [("Hub", "success"), ("Hub", "success")], 1),
        ("success", "success", ["Hub", "DPS"], [("Hub", "success"), ("Other", "success")], 1),
    ],
)
def test_integration_gate_outcomes(
    gate_steps, tmp_path, job_result, download_result, expected_services, results, expected_code
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
        **os.environ,
        "TEST_JOB_RESULT": job_result,
        "DOWNLOAD_RESULT": download_result,
        "EXPECTED_MATRIX": json.dumps([
            {"service": service, "python": "3.10", "region": f"region-{index}"}
            for index, service in enumerate(expected_services)
        ]),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.txt"),
    }

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", gate_steps[1]["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == expected_code, result.stdout + result.stderr
