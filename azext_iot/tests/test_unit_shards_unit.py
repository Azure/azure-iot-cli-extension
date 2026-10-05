# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Unit shard collection, artifact isolation, aggregation and pipeline wiring contracts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from azext_iot.tests import _unit_shards as shards

ROOT = Path(__file__).resolve().parents[2]
PROFILE = {"seconds": {}, "default_seconds": 1}
CONTEXT = {"build": "offline-unit-shards", "commit": "a" * 40}


def records():
    inventory = [f"azext_iot/tests/test_{i}_unit.py::test_case::0" for i in range(4)]
    return [{
        "schema": 1, "context": CONTEXT, "python": "3.13.0", "shard": i + 1, "attempt": 1,
        "profile": shards.digest(PROFILE), "inventory": inventory, "selected": [node],
        "finished": True, "exitstatus": 0, "seconds": 1,
        "reports": {node: {"setup": ["passed"], "call": ["passed"], "teardown": ["passed"]}},
        "durations": {node.split("::")[0]: 1},
    } for i, node in enumerate(inventory)]


def test_balancing_is_deterministic_and_includes_unknown_new_files():
    files = [f"file-{i}" for i in range(8)]
    profile = {"seconds": dict(zip(files, [90, 80, 70, 60, 40, 30, 20, 10])), "default_seconds": 1}
    plan = shards.partition(files, profile)
    assert plan == shards.partition(reversed(files), profile)
    assert [sum(profile["seconds"][name] for name in part) for part in plan] == [100] * 4
    updated = shards.partition(files + ["new-file"], profile)
    assert sorted(name for part in updated for name in part) == sorted(files + ["new-file"])


@pytest.mark.parametrize("weight", [0, -1, float("nan"), float("inf"), "1"])
def test_bad_weights_cannot_silently_change_selection(weight):
    with pytest.raises(ValueError):
        shards.partition(["a", "b", "c", "d"], {"seconds": {"a": weight}, "default_seconds": 1})


@pytest.mark.parametrize("defect", [
    "missing-shard", "duplicate-shard", "context", "python", "profile", "inventory", "selection",
    "unfinished", "exitstatus", "missing-report", "failed-call", "missing-teardown", "duplicate-stage",
])
def test_aggregate_rejects_incomplete_or_inconsistent_unit_execution(defect):
    values = deepcopy(records())
    record = values[0]
    node = record["selected"][0]
    if defect == "missing-shard":
        values.pop()
    elif defect == "duplicate-shard":
        values[-1]["shard"] = 1
    elif defect in ("context", "python", "profile"):
        record[defect] = "changed"
    elif defect == "inventory":
        record["inventory"] = record["inventory"][:-1]
    elif defect == "selection":
        record["selected"] = values[1]["selected"]
    elif defect == "unfinished":
        record["finished"] = False
    elif defect == "exitstatus":
        record["exitstatus"] = 1
    elif defect == "missing-report":
        record["reports"] = {}
    elif defect == "failed-call":
        record["reports"][node]["call"] = ["failed"]
    elif defect == "missing-teardown":
        del record["reports"][node]["teardown"]
    else:
        record["reports"][node]["setup"].append("passed")
    with pytest.raises(ValueError):
        shards.validate(values, CONTEXT, PROFILE)


def test_unit_gate_preserves_standard_pytest_skip_semantics():
    values = records()
    node = values[0]["selected"][0]
    values[0]["reports"][node] = {"setup": ["skipped"], "teardown": ["passed"]}
    assert shards.validate(values, CONTEXT, PROFILE) == 4


def make_artifacts(root):
    for record in records():
        folder = root / f"unit-shard-{record['shard']}-1"
        folder.mkdir()
        for name in shards.ARTIFACTS:
            (folder / name).write_bytes(b"offline artifact")
        record["artifacts"] = {name: shards.file_digest(folder / name) for name in shards.ARTIFACTS}
        shards.write(folder / "receipt.json", record)


@pytest.mark.parametrize("defect", ["missing", "changed", "empty-newer-attempt", "wrong-attempt", "extra-shard"])
def test_artifact_gate_never_falls_back_to_older_or_unverified_results(tmp_path, defect):
    make_artifacts(tmp_path)
    folder = tmp_path / "unit-shard-1-1"
    if defect == "missing":
        (folder / "coverage.dat").unlink()
    elif defect == "changed":
        (folder / "junit.xml").write_text("changed")
    elif defect == "empty-newer-attempt":
        (tmp_path / "unit-shard-1-2").mkdir()
    elif defect == "wrong-attempt":
        folder.rename(tmp_path / "unit-shard-1-2")
    else:
        (tmp_path / "unit-shard-5-1").mkdir()
    with pytest.raises((ValueError, FileNotFoundError)):
        shards.aggregate(tmp_path, tmp_path / "combined")
    assert not (tmp_path / "combined").exists()


def test_latest_successful_native_unit_attempt_is_aggregated(tmp_path, monkeypatch, mocker):
    make_artifacts(tmp_path)
    folder = tmp_path / "unit-shard-1-1"
    folder.rename(tmp_path / "unit-shard-1-2")
    folder = tmp_path / "unit-shard-1-2"
    record = shards.read(folder / "receipt.json")
    record["attempt"] = 2
    shards.write(folder / "receipt.json", record)
    profile = tmp_path / "profile.json"
    shards.write(profile, PROFILE)
    monkeypatch.setattr(shards, "PROFILE", profile)
    monkeypatch.setenv("BUILD_BUILDID", CONTEXT["build"])
    monkeypatch.setenv("BUILD_SOURCEVERSION", CONTEXT["commit"])
    run = mocker.patch.object(shards.subprocess, "run")
    shards.aggregate(tmp_path, tmp_path / "combined")
    assert shards.read(tmp_path / "combined/summary.json")["tests"] == 4
    assert len([arg for arg in run.call_args.args[0] if arg.endswith("coverage.dat")]) == 4
    assert "unit-shard-1-2" in run.call_args.args[0][5]


def test_real_four_process_collection_and_coverage_with_random_parameters(tmp_path, monkeypatch):
    directory = tmp_path / "azext_iot/tests"
    directory.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\njunit_family=xunit1\n", encoding="utf-8")
    (tmp_path / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    for index in range(4):
        (directory / f"test_{index}_unit.py").write_text(
            "import uuid, pytest, sample\n"
            "@pytest.mark.parametrize('value', [str(uuid.uuid4()), str(uuid.uuid4())])\n"
            "def test_example(value):\n"
            "    assert value and sample.value() == 1\n",
            encoding="utf-8",
        )

    def execute(index):
        output = tmp_path / f"unit-shard-{index}-1"
        env = dict(os.environ, BUILD_BUILDID=CONTEXT["build"], BUILD_SOURCEVERSION=CONTEXT["commit"],
                   SYSTEM_JOBATTEMPT="1", COVERAGE_FILE=str(output / "coverage.dat"), PYTEST_ADDOPTS="",
                   PYTHONPATH=os.pathsep.join(dict.fromkeys([str(tmp_path), str(ROOT), *map(os.path.abspath, sys.path)])))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(directory), "-c", str(tmp_path / "pytest.ini"), "-k", "_unit.py",
             "-p", "azext_iot.tests._unit_shard_plugin", "--unit-shard", str(index), "--unit-shard-output", str(output),
             "--cov=sample", "--cov-report=", "--junitxml", str(output / "junit.xml"), "-q"],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return shards.read(output / "receipt.json")

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(execute, range(1, 5)))
    assert shards.validate(values, CONTEXT, shards.read(shards.PROFILE)) == 8
    assert all(len(record["selected"]) == 2 for record in values)
    monkeypatch.setenv("BUILD_BUILDID", CONTEXT["build"])
    monkeypatch.setenv("BUILD_SOURCEVERSION", CONTEXT["commit"])
    shards.aggregate(tmp_path, tmp_path / "combined")
    assert (tmp_path / "combined/.coverage").is_file()
    assert len(shards.read(tmp_path / "combined/timings.json")["seconds"]) == 4


def test_pipeline_keeps_four_shards_and_unit_gate_without_cross_job_cache():
    pipeline = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())
    stages = pipeline["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    unit = next(stage for stage in stages if stage.get("stage") == "Unit")
    job, gate = unit["jobs"]
    assert job["strategy"]["maxParallel"] == 4
    assert {value["shard"] for value in job["strategy"]["matrix"].values()} == {1, 2, 3, 4}
    assert gate["dependsOn"] == "Unit" and "condition" not in gate
    assert any(step.get("artifact") == "unit-shard-$(shard)-$(System.JobAttempt)" for step in job["steps"])
    run = next(step for step in job["steps"] if "bash" in step)
    assert "--unit-shard" in run["bash"] and "--unit-shard-output" in run["bash"]
    assert run["env"]["COVERAGE_FILE"].endswith("/coverage.dat")
    assert not (ROOT / ".azure-devops/templates/pip-cache.yml").exists()
    assert "PIP_CACHE_DIR" not in run["env"]
    assert "pip-cache" not in str(stages) and "Cache@2" not in str(stages)
    assert "condition" not in run
