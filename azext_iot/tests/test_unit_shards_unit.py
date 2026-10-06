# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Unit shard collection, artifact isolation, aggregation and pipeline wiring contracts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from fnmatch import fnmatchcase
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


def test_unit_gate_accepts_different_patch_releases_within_the_requested_python_series():
    values = records()
    for record, version in zip(values, ["3.13.15", "3.13.15", "3.13.16", "3.13.15"]):
        record["python"] = version
    assert shards.validate(values, CONTEXT, PROFILE) == 4


@pytest.mark.parametrize("version", ["3.12.16", "3.14.0", "4.13.0", "3.13", "3.13.bad", "3.13.16rc1", "", None])
def test_unit_gate_rejects_other_python_series_and_malformed_versions(version):
    values = records()
    values[2]["python"] = version
    with pytest.raises(ValueError, match="Python"):
        shards.validate(values, CONTEXT, PROFILE)


def test_unit_gate_preserves_standard_pytest_skip_semantics():
    values = records()
    node = values[0]["selected"][0]
    values[0]["reports"][node] = {"setup": ["skipped"], "teardown": ["passed"]}
    assert shards.validate(values, CONTEXT, PROFILE) == 4


def make_artifacts(root, prefix="unit-shard"):
    for record in records():
        folder = root / f"{prefix}-{record['shard']}-1"
        folder.mkdir()
        for name in shards.ARTIFACTS:
            (folder / name).write_bytes(b"offline artifact")
        record["artifacts"] = {name: shards.file_digest(folder / name) for name in shards.ARTIFACTS}
        shards.write(folder / "receipt.json", record)


@pytest.mark.parametrize("prefix", ["unit-shard", "tox-unit-windows-2025-py3.13"])
@pytest.mark.parametrize("defect", ["missing", "changed", "empty-newer-attempt", "wrong-attempt", "extra-shard"])
def test_artifact_gate_never_falls_back_to_older_or_unverified_results(tmp_path, defect, prefix):
    make_artifacts(tmp_path, prefix)
    folder = tmp_path / f"{prefix}-1-1"
    if defect == "missing":
        (folder / "coverage.dat").unlink()
    elif defect == "changed":
        (folder / "junit.xml").write_text("changed")
    elif defect == "empty-newer-attempt":
        (tmp_path / f"{prefix}-1-2").mkdir()
    elif defect == "wrong-attempt":
        folder.rename(tmp_path / f"{prefix}-1-2")
    else:
        (tmp_path / f"{prefix}-5-1").mkdir()
    with pytest.raises((ValueError, FileNotFoundError)):
        shards.aggregate(tmp_path, tmp_path / "combined", prefix)
    assert not (tmp_path / "combined").exists()


@pytest.mark.parametrize("prefix", ["unit-shard", "tox-unit-windows-2025-py3.13"])
def test_latest_successful_native_unit_attempt_is_aggregated(tmp_path, monkeypatch, mocker, prefix):
    make_artifacts(tmp_path, prefix)
    make_artifacts(tmp_path, "tox-unit-macos-15-intel-py3.12")
    folder = tmp_path / f"{prefix}-1-1"
    folder.rename(tmp_path / f"{prefix}-1-2")
    folder = tmp_path / f"{prefix}-1-2"
    record = shards.read(folder / "receipt.json")
    record["attempt"] = 2
    record["python"] = "3.13.16"
    shards.write(folder / "receipt.json", record)
    profile = tmp_path / "profile.json"
    shards.write(profile, PROFILE)
    monkeypatch.setattr(shards, "PROFILE", profile)
    monkeypatch.setenv("UNIT_RUN_ID", CONTEXT["build"])
    monkeypatch.setenv("UNIT_COMMIT", CONTEXT["commit"])
    run = mocker.patch.object(shards.subprocess, "run")
    shards.aggregate(tmp_path, tmp_path / "combined", prefix)
    summary = shards.read(tmp_path / "combined/summary.json")
    assert summary["tests"] == 4
    assert [record["python"] for record in summary["shards"]] == ["3.13.16", "3.13.0", "3.13.0", "3.13.0"]
    assert len([arg for arg in run.call_args.args[0] if arg.endswith("coverage.dat")]) == 4
    assert f"{prefix}-1-2" in run.call_args.args[0][5]


@pytest.mark.parametrize("prefix", ["unit-shard", "tox-unit-windows-2025-py3.13"])
def test_real_four_process_collection_and_coverage_with_random_parameters(tmp_path, monkeypatch, prefix):
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
        output = tmp_path / f"{prefix}-{index}-1"
        env = dict(os.environ, UNIT_RUN_ID=CONTEXT["build"], UNIT_COMMIT=CONTEXT["commit"],
                   UNIT_ATTEMPT="1", COVERAGE_FILE=str(output / "coverage.dat"), PYTEST_ADDOPTS="",
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
    monkeypatch.setenv("UNIT_RUN_ID", CONTEXT["build"])
    monkeypatch.setenv("UNIT_COMMIT", CONTEXT["commit"])
    shards.aggregate(tmp_path, tmp_path / "combined", prefix)
    assert (tmp_path / "combined/.coverage").is_file()
    assert len(shards.read(tmp_path / "combined/timings.json")["seconds"]) == 4


def test_github_prechecks_keep_lint_independent_and_gate_every_shard():
    jobs = yaml.safe_load((ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))["jobs"]
    lint, job, gate = (jobs[name] for name in ("lint", "unit-shards", "unit-test"))
    assert "needs" not in lint and "needs" not in job
    assert job["strategy"] == {"fail-fast": False, "max-parallel": 4, "matrix": {"shard": [1, 2, 3, 4]}}
    assert gate["needs"] == ["lint", "unit-shards"]
    for precheck in (lint, job, gate):
        assert "if" not in precheck and "continue-on-error" not in precheck
        assert precheck["permissions"] == {"contents": "read"}
        assert not any(step.get("continue-on-error") for step in precheck["steps"])
    run = next(step for step in job["steps"] if "run" in step)
    assert "-e python-azcur-unit" in run["run"]
    assert "--unit-shard" in run["run"] and "--unit-shard-output" in run["run"]
    assert run["env"]["COVERAGE_FILE"].endswith("/coverage.dat")
    assert run["env"]["UNIT_ATTEMPT"] == "${{ github.run_attempt }}"
    assert "if" not in run
    upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["name"] == "unit-shard-${{ matrix.shard }}-${{ github.run_attempt }}"
    assert upload["with"]["if-no-files-found"] == "error" and not upload["with"].get("overwrite")
    download = next(step for step in gate["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"pattern": "unit-shard-*", "path": "unit-history"}
    combine = next(step for step in gate["steps"] if "run" in step)
    assert "_unit_shards.py --history unit-history --output unit-coverage" in combine["run"]
    assert combine["env"] == {name: run["env"][name] for name in ("UNIT_RUN_ID", "UNIT_COMMIT")}
    coverage = next(step for step in gate["steps"] if step.get("with", {}).get("name") == "coverage-unit")
    assert coverage["with"]["path"] == "unit-coverage/.coverage"
    assert coverage["with"]["include-hidden-files"] is True
    assert coverage["with"]["if-no-files-found"] == "error" and "if" not in coverage
    assert jobs["int-test"]["needs"] == ["setup", "unit-test"]
    assert "needs.unit-test.result == 'success'" in jobs["int-test"]["if"]


@pytest.mark.parametrize("branch,push_enabled", [
    ("dev", True),
    ("preview", True),
    ("1.1.0-preview", True),
    ("release/1.0.0-preview", True),
    ("release/1.1.0-preview", True),
    ("release/future-preview", True),
    ("users/hangyiwang/unit-test-parallelism", False),
    ("users/hangyiwang/ado147-integration-parity-retries", False),
    ("dependabot/github_actions/update", False),
    ("fix/example", False),
])
def test_pr_ci_does_not_duplicate_feature_branch_pushes(branch, push_enabled):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci_workflow.yml").read_text(encoding="utf-8"))
    # PyYAML's YAML 1.1 parser also recognizes unquoted "on" as True.
    events = workflow.get("on", workflow.get(True))
    assert events == {
        "pull_request": None,
        "push": {"branches": ["dev", "preview", "1.1.0-preview", "release/**"], "tags": ["**"]},
        "workflow_dispatch": None,
    }
    assert any(fnmatchcase(branch, pattern) for pattern in events["push"]["branches"]) == push_enabled


def test_pr_ci_shards_every_os_python_combination_without_mixing_artifacts():
    caller = yaml.safe_load((ROOT / ".github/workflows/ci_workflow.yml").read_text(encoding="utf-8"))["jobs"]["test"]
    assert caller["uses"] == "./.github/workflows/tox.yml"
    assert caller.get("name", "test") == "test"
    assert caller.get("with", {}).get("continue-on-error", False) is False
    jobs = yaml.safe_load((ROOT / ".github/workflows/tox.yml").read_text(encoding="utf-8"))["jobs"]
    unit, gate = jobs["tox"], jobs["unit-gate"]
    assert gate["name"] == "Unit test ${{ matrix.py }} - ${{ matrix.os }}"
    assert unit["name"] == gate["name"] + " (shard ${{ matrix.shard }}/4)"
    matrix = {
        "os": ["ubuntu-24.04", "windows-2025", "macos-15-intel"],
        "py": ["3.13", "3.12", "3.11", "3.10"],
    }
    assert unit["strategy"] == {"fail-fast": False, "matrix": dict(matrix, shard=[1, 2, 3, 4])}
    assert gate["strategy"] == {"fail-fast": False, "matrix": matrix}
    assert gate["needs"] == "tox" and gate["if"] == "${{ always() }}"
    guard = gate["steps"][0]
    assert guard["name"] == "Require successful unit shards and lint"
    assert guard["if"] == "${{ needs.tox.result != 'success' }}"
    assert guard["run"].strip().endswith("exit 1") and "::error::" in guard["run"]
    assert "continue-on-error" not in guard
    for job in (unit, gate):
        assert job["runs-on"] == "${{ matrix.os }}"
        assert job["continue-on-error"] == "${{ inputs.continue-on-error }}"
    run = next(step for step in unit["steps"] if step.get("name") == "Run test suite")
    assert "-e python-azcur-unit --skip-pkg-install --" in run["run"]
    assert "--unit-shard ${{ matrix.shard }}" in run["run"]
    assert run["env"]["UNIT_ATTEMPT"] == "${{ github.run_attempt }}"
    assert ":tox:${{ matrix.os }}:py${{ matrix.py }}" in run["env"]["UNIT_RUN_ID"]
    lint = next(step for step in unit["steps"] if step.get("name") == "Run lint once per OS and Python")
    assert lint["if"] == "${{ matrix.shard == 1 }}" and "-e lint" in lint["run"]
    upload = next(step for step in unit["steps"] if step.get("name") == "Upload unit shard evidence")
    prefix = "tox-unit-${{ matrix.os }}-py${{ matrix.py }}"
    assert upload["with"]["name"] == prefix + "-${{ matrix.shard }}-${{ github.run_attempt }}"
    assert upload["if"] == "${{ always() }}" and upload["with"]["if-no-files-found"] == "error"
    assert not upload["with"].get("overwrite")
    download = next(step for step in gate["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"pattern": prefix + "-*", "path": "unit-history"}
    combine = next(step for step in gate["steps"] if "_unit_shards.py" in step.get("run", ""))
    assert "--prefix " + prefix in combine["run"]
    assert combine["env"] == {name: run["env"][name] for name in ("UNIT_RUN_ID", "UNIT_COMMIT")}
    report = next(step for step in gate["steps"] if step.get("name") == "Generate coverage reports")
    assert report["env"]["COVERAGE_FILE"].endswith("/unit-coverage/.coverage")
    assert all(f"coverage {kind}" in report["run"] for kind in ("report", "html", "json"))
    coverage = next(step for step in gate["steps"] if step.get("with", {}).get("name") == "code-coverage")
    assert coverage["if"] == "${{ matrix.os == 'ubuntu-24.04' && matrix.py == '3.13' }}"
    assert coverage["with"]["path"] == "htmlcov/"


def test_tox_passes_ci_neutral_shard_identity_without_changing_default_unit_selection():
    from configparser import ConfigParser
    config = ConfigParser(interpolation=None)
    config.read(ROOT / "tox.ini")
    unit = config["testenv:py{thon,38,39,310,311,312,313}-az{min,cur,dev}-unit"]
    assert {"UNIT_RUN_ID", "UNIT_COMMIT", "UNIT_ATTEMPT", "COVERAGE_FILE"} <= set(unit["passenv"].split())
    assert 'python -m pytest -k "_unit.py" ./azext_iot/tests' in unit["commands"]
    assert "{posargs}" in unit["commands"]
