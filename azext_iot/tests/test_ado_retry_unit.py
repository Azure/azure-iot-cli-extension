# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for manual retry ancestry, exact selection and the real diagnostic subprocess."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from string import Template
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from azext_iot.tests import _ado_retry as retry
from azext_iot.tests import _ado_pipeline as pipeline
from azext_iot.tests import _focused_live as focused
from azext_iot.tests import _refresh_ci_auth as auth

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = {
    "build": "offline-123", "definition": "147", "commit": "a" * 40, "wheel": "b" * 64,
    "dependencies": "c" * 64, "service": "ADR", "python": "3.13", "region": "australiaeast",
    "endpoint": "https://management.azure.com", "subscription": pipeline.TARGET["SUBSCRIPTION"],
    "resource_group": "cli-int-test-rg", "diagnostic": "false",
}


@pytest.fixture
def isolated_phase_environment(monkeypatch):
    for name in pipeline.GENERIC_PHASE_OVERRIDES:
        monkeypatch.delenv(name, raising=False)


def receipt(results):
    return {
        "finished": True, "exitstatus": int("failed" in results.values()), "collected": list(results),
        "reports": {node: {"setup": ["passed"], "call": [outcome], "teardown": ["passed"]}
                    for node, outcome in results.items()},
        "retryableFailures": {node: True for node, outcome in results.items() if outcome == "failed"},
    }


def attempt(results, previous=None):
    return {
        "schema": 3, "context": CONTEXT.copy(), "sequence": previous["sequence"] + 1 if previous else 1,
        "mode": "full" if previous is None or set(results) == {"a", "b", "c"} else "cases",
        "nativeAttempt": previous["nativeAttempt"] + 1 if previous else 1,
        "parent": retry.digest(previous) if previous else None, "executionErrors": [],
        "phases": {"tests": {"expected": ["a", "b", "c"], "safe": True, "receipt": receipt(results)}},
    }


def test_exact_retry_preserves_passes_and_records_recovery(tmp_path):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    assert retry.pending([first], CONTEXT) == {"tests": ["b"]}
    second = attempt({"b": "passed"}, first)
    expected, effective, recovered = retry.evaluate([first, second], CONTEXT)
    assert expected == {"tests": ("a", "b", "c")}
    assert effective == {"tests": {"a": "passed", "b": "passed", "c": "passed"}}
    assert recovered == {("tests", "b")}
    assert retry.junit([first, second], CONTEXT, tmp_path / "final.xml") == 0
    assert "Passed on manual retry" in (tmp_path / "final.xml").read_text()


@pytest.mark.parametrize("defect", [
    "parent", "commit", "wheel", "dependencies", "region", "endpoint", "build", "definition",
    "sequence", "missing", "extra", "rerun-pass", "skip", "setup", "teardown", "incomplete",
    "cleanup", "auth", "collection", "duplicate-stage", "exit-code", "phase", "native-attempt", "unsafe-call", "exclusions",
])
def test_bad_evidence_never_recovers_a_run(defect):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    second = attempt({"b": "passed"}, first)
    phase = second["phases"]["tests"]
    reports = phase["receipt"]["reports"]
    if defect in CONTEXT:
        second["context"][defect] = "foreign"
    elif defect == "parent":
        second["parent"] = "foreign"
    elif defect == "sequence":
        second["sequence"] = 3
    elif defect == "missing":
        phase["receipt"] = receipt({})
    elif defect in ("extra", "rerun-pass"):
        phase["receipt"] = receipt({"b": "passed", "a": "passed"})
    elif defect == "skip":
        reports["b"]["call"] = ["skipped"]
    elif defect in ("setup", "teardown"):
        reports["b"][defect] = ["failed"]
    elif defect == "incomplete":
        phase["receipt"]["finished"] = False
    elif defect == "cleanup":
        phase["safe"] = False
    elif defect == "auth":
        second["executionErrors"] = ["Credential refresher stopped unexpectedly."]
    elif defect == "collection":
        phase["expected"] = ["b"]
    elif defect == "duplicate-stage":
        reports["b"]["call"].append("passed")
    elif defect == "exit-code":
        phase["receipt"]["exitstatus"] = 1
    elif defect == "phase":
        second["phases"]["other"] = second["phases"].pop("tests")
    elif defect == "native-attempt":
        second["nativeAttempt"] = 3
    elif defect == "unsafe-call":
        first["phases"]["tests"]["receipt"]["retryableFailures"]["b"] = False
        second["parent"] = retry.digest(first)
    elif defect == "exclusions":
        phase["excluded"] = ["new"]
    if defect in ("missing", "skip", "setup", "teardown", "incomplete", "auth", "duplicate-stage", "exit-code"):
        assert retry.recovery_plan([first, second], CONTEXT)["mode"] == "full"
    else:
        with pytest.raises(ValueError):
            retry.evaluate([first, second], CONTEXT)


def test_failed_retry_stays_failed_and_incomplete_first_attempt_cannot_be_erased():
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    second = attempt({"b": "failed"}, first)
    assert retry.pending([first, second], CONTEXT) == {"tests": ["b"]}
    first["executionErrors"] = ["Credential refresher stopped unexpectedly."]
    second = attempt({"b": "passed"}, first)
    with pytest.raises(ValueError):
        retry.evaluate([first, second], CONTEXT)


@pytest.mark.parametrize("service", retry.SERVICES)
@pytest.mark.parametrize("failure", ["call", "setup", "teardown", "call-cleanup"])
@pytest.mark.parametrize("cleanup_verified", [False, True])
def test_cross_service_retry_scope_is_independent_of_cleanup_completion(service, failure, cleanup_verified):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    first["context"]["service"] = service
    ctx = first["context"]
    phase = first["phases"]["tests"]
    phase["cleanupVerified"] = cleanup_verified
    report = phase["receipt"]["reports"]["b"]
    if failure == "setup":
        report["setup"] = ["failed"]
        del report["call"]
    elif failure == "teardown":
        report.update(call=["passed"], teardown=["failed"])
    elif failure == "call-cleanup":
        phase["receipt"]["retryableFailures"]["b"] = False
    selected = ["b"] if failure == "call" else ["a", "b", "c"]
    assert retry.recovery_plan([first], ctx)["mode"] == ("cases" if failure == "call" else "full")
    assert retry.pending([first], ctx) == {"tests": selected}
    second = attempt(dict.fromkeys(selected, "passed"), first)
    second["context"] = ctx.copy()
    assert not retry.pending([first, second], ctx)
    assert retry.evaluate([first, second], ctx)[2] == {("tests", "b")}
    if failure != "call":
        second["phases"]["tests"]["receipt"] = receipt({"b": "passed"})
        with pytest.raises(ValueError, match="exactly"):
            retry.evaluate([first, second], ctx)


def test_phase_retry_new_failure_is_not_hidden_by_retained_passing_results():
    first = attempt({"a": "passed", "b": "passed", "c": "passed"})
    first["context"]["service"] = "HubControl"
    phase = first["phases"]["tests"]
    phase["cleanupVerified"] = True
    phase["receipt"]["reports"]["b"]["teardown"] = ["failed"]
    phase["receipt"]["exitstatus"] = 1
    second = attempt({"a": "failed", "b": "passed", "c": "passed"}, first)
    second["context"] = first["context"].copy()
    assert retry.pending([first, second], first["context"]) == {"tests": ["a"]}
    third = attempt({"a": "passed"}, second)
    third["context"] = first["context"].copy()
    assert not retry.pending([first, second, third], first["context"])


@pytest.mark.parametrize("service", retry.SERVICES)
@pytest.mark.parametrize("failure", ["setup", "worker-crash", "timeout", "empty-collection", "before-collection"])
def test_incomplete_execution_requires_full_service_including_passing_phases(service, failure):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    first["context"]["service"] = service
    ctx = first["context"]
    first["phases"]["passing-phase"] = deepcopy(attempt(dict.fromkeys(("a", "b", "c"), "passed"))["phases"]["tests"])
    value = first["phases"]["tests"]["receipt"]
    if failure == "setup":
        value["reports"]["b"] = {"setup": ["failed"], "teardown": ["passed"]}
    elif failure == "worker-crash":
        value["workerErrors"] = ["worker terminated"]
    elif failure == "timeout":
        first["executionErrors"] = ["test process timed out and was terminated"]
    elif failure == "empty-collection":
        value.update(collected=[], reports={})
    else:
        first.update(phases={}, executionErrors=["login failed"])
    assert retry.recovery_plan([first], ctx)["mode"] == "full"
    second = attempt(dict.fromkeys(("a", "b", "c"), "passed"), first)
    second["context"] = ctx.copy()
    second["phases"]["passing-phase"] = deepcopy(second["phases"]["tests"])
    assert not retry.pending([first, second], ctx)
    second["phases"]["passing-phase"]["receipt"] = receipt({"a": "passed", "b": "failed", "c": "passed"})
    assert retry.pending([first, second], ctx) == {"passing-phase": ["b"]}


def test_reuse_cannot_hide_new_execution_errors():
    first = attempt(dict.fromkeys(("a", "b", "c"), "passed"))
    second = attempt({}, first)
    second.update(mode="reuse", phases={}, executionErrors=["authentication failed"])
    with pytest.raises(ValueError, match="fully passing"):
        retry.evaluate([first, second], CONTEXT)


def test_identity_rejection_identifies_changed_field_without_values():
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    first["context"]["dependencies"] = "private-dependency-data"
    with pytest.raises(ValueError, match="identity changed: dependencies") as error:
        retry.pending([first], CONTEXT)
    assert "private-dependency-data" not in str(error.value)


def test_rejected_attempt_cannot_be_ignored_by_final_gate(tmp_path):
    pipeline.reject(tmp_path / "attempt", "Prior teardown is unproven.")
    with pytest.raises(ValueError, match="immutable identity"):
        pipeline.gate(tmp_path)


@pytest.mark.parametrize("reported", [False, True])
def test_real_incomplete_execution_report_is_failing_and_never_overwrites_results(tmp_path, reported):
    if reported:
        (tmp_path / "final.xml").write_text("original terminal report", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", str(ROOT / "azext_iot/tests/_ado_pipeline.py"),
         "report-incomplete", "--output", str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == int(not reported), completed.stdout + completed.stderr
    if reported:
        assert (tmp_path / "final.xml").read_text() == "original terminal report"
        assert not (tmp_path / "rejection.json").exists()
    else:
        assert 'errors="1"' in (tmp_path / "final.xml").read_text()
        assert retry.read(tmp_path / "rejection.json")["qualifies"] is False
        assert "installation, login or execution" in (tmp_path / "summary.md").read_text()


def test_parameter_case_hashes_preserve_identity_without_persisting_secrets():
    assert retry.case_id("test[secret-one]") != retry.case_id("test[secret-two]")
    assert "secret" not in retry.case_id("test[secret-one]")


@pytest.mark.parametrize("services,versions,regions,endpoint", [
    (["Central"], ["3.13"], ["westus"], pipeline.TARGET["PUBLIC_ARM"]),
    (["DPS", "DPS"], ["3.13"], ["westus"], pipeline.TARGET["PUBLIC_ARM"]),
    (["DPS"], ["3.9"], ["westus"], pipeline.TARGET["PUBLIC_ARM"]),
    (["DPS"], ["3.13"], ["westus"], pipeline.TARGET["CANARY_ARM"]),
    (["DPS"], ["3.13"], ["westus", "westus"], pipeline.TARGET["PUBLIC_ARM"]),
])
def test_plan_rejects_unsupported_or_duplicate_configuration(services, versions, regions, endpoint):
    with pytest.raises(ValueError):
        pipeline.plan(services, versions, regions, endpoint)


def test_plan_has_all_github_services_and_no_legacy_services():
    jobs = pipeline.plan(list(retry.SERVICES), ["3.10", "3.13"], ["australiaeast"], pipeline.TARGET["PUBLIC_ARM"])
    assert len(jobs) == 10
    assert {job["service"] for job in jobs} == set(retry.SERVICES)
    assert next(job["minutes"] for job in jobs if job["service"] == "ADR") == 360


@pytest.mark.parametrize("status,count,error,message", [
    (200, 0, None, ""),
    (200, 1, ValueError, "A GitHub integration run is active"),
    (403, 0, RuntimeError, "GitHub live-run admission could not be checked"),
    (302, 0, RuntimeError, "GitHub live-run admission could not be checked"),
])
def test_admission_only_checks_github_without_ado_build_credentials(status, count, error, message, mocker, monkeypatch):
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)
    monkeypatch.delenv("BUILD_BUILDID", raising=False)
    response = mocker.MagicMock(status_code=status)
    response.__enter__.return_value = response
    response.json.return_value = {"total_count": count}
    get = mocker.patch("requests.get", return_value=response)
    if error:
        with pytest.raises(error, match=message):
            pipeline.admission()
    else:
        pipeline.admission()
    get.assert_called_once_with(
        "https://api.github.com/repos/Azure/azure-iot-cli-extension/actions/workflows/int_test.yml/runs",
        params={"status": "in_progress", "per_page": 1}, timeout=(10, 30), allow_redirects=False,
    )


def test_attempt_selection_is_separate_from_nonqualifying_debug():
    node = pipeline.owned_nodes("DPS")["regular"][0]
    selection = focused.attempt("DPS", "regular", [node], "a" * 64)
    evidence = focused.provenance(selection)
    assert evidence["mode"] == "attempt"
    assert not focused.matches(evidence, None)
    assert not focused.matches(evidence, focused.select("DPS", "regular", [node]))
    assert focused.from_environment({focused.ENV: json.dumps(selection)}, "DPS", "regular") == selection


def test_ado_federation_uses_job_and_service_connection_without_github_token(mocker, monkeypatch):
    names = ("SYSTEM_TEAMPROJECTID", "SYSTEM_PLANID", "SYSTEM_JOBID", "AZURESUBSCRIPTION_SERVICE_CONNECTION_ID")
    for index, name in enumerate(names, 1):
        monkeypatch.setenv(name, f"00000000-0000-0000-0000-{index:012d}")
    monkeypatch.setenv("AZEXT_IOT_CI_AUTH", "ado")
    monkeypatch.setenv("SYSTEM_ACCESSTOKEN", "offline-secret")
    response = Mock(status_code=200)
    response.json.return_value = {"oidcToken": "offline-assertion"}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    post = mocker.patch.object(auth.requests, "post", return_value=response)
    get = mocker.patch.object(auth.requests, "get", side_effect=AssertionError("GitHub must not be used"))
    assert auth.assertion() == "offline-assertion"
    assert post.call_args.kwargs["params"]["serviceConnectionId"] == os.environ[names[-1]]
    assert post.call_args.kwargs["allow_redirects"] is False
    assert "/jobs/" + os.environ["SYSTEM_JOBID"] + "/oidctoken" in post.call_args.args[0]
    get.assert_not_called()


def test_yaml_exposes_manual_only_integration_default_and_all_services_preset():
    entry_text = (ROOT / ".azure-devops/integration_tests.yml").read_text()
    entry = yaml.safe_load(entry_text)
    parameters = {value["name"]: value for value in entry["parameters"]}
    assert entry["trigger"] == entry["pr"] == "none"
    assert parameters["mode"]["default"] == "Integration tests"
    assert parameters["mode"]["values"] == ["Dry run", "Integration tests"]
    assert len(entry["stages"]) == 2
    assert entry["stages"][0]["stage"] == "Plan"
    assert [job["job"] for job in entry["stages"][0]["jobs"]] == ["Plan"]
    assert "${{ if eq(parameters.mode, 'Integration tests') }}" in entry["stages"][1]
    assert parameters["services"]["default"] == ["DPS/Hub/ADR/ADU"]
    assert parameters["services"]["values"] == ["DPS/Hub/ADR/ADU", *retry.SERVICES]
    assert parameters["pythonVersions"]["type"] == "stringList"
    text = (ROOT / ".azure-devops/templates/integration-service.yml").read_text()
    assert "RetrySelfTest" not in entry_text + text
    assert "--diagnostic" not in entry_text + text
    assert "continueOnError" not in text and "retryCountOnTaskFailure" not in text
    assert "System.JobAttempt" in text and "failTaskOnMissingResultsFile: true" in text
    assert "indexOf(" not in (ROOT / ".azure-devops/integration_tests.yml").read_text()
    assert "smoke-tests.yml" not in (ROOT / ".azure-devops/integration_tests.yml").read_text()
    template = yaml.safe_load(text)
    steps = template["stages"][0]["jobs"][0]["steps"]
    assert "diagnostic" not in {value["name"] for value in template["parameters"]}
    live = next(step for step in steps if step.get("task") == "AzureCLI@2")
    assert live["env"]["PYTHONPATH"] == "$(Build.SourcesDirectory)"


def test_service_preset_uses_one_expansion_for_plan_stages_and_gate():
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())
    services = next(value for value in entry["variables"] if value.get("name") == "servicesCsv")
    assert services == {
        "name": "servicesCsv",
        "${{ if containsValue(parameters.services, 'DPS/Hub/ADR/ADU') }}": {"value": ",".join(retry.SERVICES)},
        "${{ else }}": {"value": "${{ join(',', parameters.services) }}"},
    }
    plan = next(step for step in entry["stages"][0]["jobs"][0]["steps"] if "bash" in step)
    assert plan["env"]["SERVICES"] == "${{ replace(variables.servicesCsv, ',', ' ') }}"
    integration = entry["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    nonempty = "${{ if ne(variables.servicesCsv, '') }}"
    each = "${{ each service in split(variables.servicesCsv, ',') }}"
    stages = next(value[nonempty] for value in integration if nonempty in value)
    assert stages == [{each: [{
        "template": "templates/integration-service.yml",
        "parameters": {
            "service": "${{ service }}", "pythonVersions": "${{ parameters.pythonVersions }}",
            "regions": "${{ split(parameters.regions, ',') }}",
        },
    }]}]
    gate = next(value for value in integration if value.get("stage") == "Qualify")
    assert gate["dependsOn"] == ["Plan", "Build", "Lint", "Unit", {nonempty: [{each: ["${{ service }}"]}]}]


@pytest.mark.parametrize("step_name", ["install", "live"])
def test_standalone_runners_and_children_inherit_candidate_dependencies(tmp_path, step_name):
    template = yaml.safe_load((ROOT / ".azure-devops/templates/integration-service.yml").read_text())
    steps = template["stages"][0]["jobs"][0]["steps"]
    install = next(step["bash"] for step in steps if "bash" in step)
    live = next(step["inputs"]["inlineScript"] for step in steps if step.get("task") == "AzureCLI@2")
    export = 'export PYTHONPATH="$PYTHONPATH:$AZURE_EXTENSION_DIR/azure-iot"'
    assert export in install and export in live
    probe = '"from azext_iot import _factory; from azext_iot.tests import _ado_retry_plugin"'
    assert install.index(export) < install.index("python -c " + probe)
    assert 'PYTHONPATH="$PYTHONPATH:$extension" .tox/DPS-int/bin/python -c' in install
    assert live.index(export) < live.index("python azext_iot/tests/_ado_pipeline.py run")

    checkout = tmp_path / "checkout"
    extension_root = tmp_path / "extensions"
    dependency_dir = extension_root / "azure-iot"
    checkout.mkdir()
    dependency_dir.mkdir(parents=True)
    (checkout / "ado_runtime_probe.py").write_text("ORIGIN = 'checkout'\n", encoding="utf-8")
    (dependency_dir / "ado_runtime_probe.py").write_text("ORIGIN = 'candidate'\n", encoding="utf-8")
    (dependency_dir / "ado_runtime_dependency.py").write_text("AVAILABLE = True\n", encoding="utf-8")
    script = install if step_name == "install" else live
    assignment = next(line.strip() for line in script.splitlines() if line.strip().startswith("export PYTHONPATH="))
    parts = assignment.split("=", 1)[1].strip('"').split(":")
    pythonpath = os.pathsep.join(Template(part).substitute(
        PYTHONPATH=str(checkout), AZURE_EXTENSION_DIR=str(extension_root),
    ) for part in parts)
    environment = dict(os.environ, PYTHONPATH=pythonpath, PYTHONNOUSERSITE="1")
    check = (
        "import ado_runtime_probe, ado_runtime_dependency;"
        "assert ado_runtime_probe.ORIGIN == 'checkout';"
        "assert ado_runtime_dependency.AVAILABLE"
    )
    command = [
        sys.executable, "-S", "-c", check + ";import subprocess,sys;"
        f"subprocess.run([sys.executable,'-S','-c',{check!r}],check=True)",
    ]
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    environment["PYTHONPATH"] = str(checkout)
    missing = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert missing.returncode != 0 and "ModuleNotFoundError" in missing.stderr


def test_build_lint_and_unit_stages_are_independent_and_keep_artifacts():
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())
    integration = entry["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    stages = {stage["stage"]: stage for stage in integration if "stage" in stage}
    assert list(stages) == ["Build", "Lint", "Unit", "Qualify"]
    for name in ("Build", "Lint", "Unit"):
        assert stages[name]["dependsOn"] == "Plan"
        assert [job["job"] for job in stages[name]["jobs"]] == ([name, "UnitGate"] if name == "Unit" else [name])
    build_steps = stages["Build"]["jobs"][0]["steps"]
    assert any(step.get("artifact") == "integration-wheel-$(System.JobAttempt)" for step in build_steps)
    lint = next(step["bash"] for step in stages["Lint"]["jobs"][0]["steps"] if "bash" in step)
    unit_steps = stages["Unit"]["jobs"][0]["steps"]
    unit = next(step["bash"] for step in unit_steps if "bash" in step)
    assert "python -m tox r -e lint -vv" in lint
    assert "python-azcur-unit" not in lint
    assert "python -m tox r -e python-azcur-unit -vv" in unit
    assert "lint" not in unit
    publish = next(step for step in unit_steps if step.get("task") == "PublishTestResults@2")
    assert publish["inputs"]["failTaskOnFailedTests"] is True
    assert publish["inputs"]["failTaskOnMissingResultsFile"] is True
    assert any(step.get("artifact") == "integration-unit-coverage-$(System.JobAttempt)"
               for step in stages["Unit"]["jobs"][1]["steps"])
    assert stages["Qualify"]["dependsOn"][:4] == ["Plan", "Build", "Lint", "Unit"]
    assert "condition" not in stages["Qualify"]


def test_pipeline_adapts_shared_four_shards_and_unit_gate_without_cross_job_cache():
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())
    stages = entry["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    unit = next(stage for stage in stages if stage.get("stage") == "Unit")
    job, gate = unit["jobs"]
    assert job["strategy"]["maxParallel"] == 4
    assert {value["shard"] for value in job["strategy"]["matrix"].values()} == {1, 2, 3, 4}
    assert gate["dependsOn"] == "Unit" and "condition" not in gate
    assert any(step.get("artifact") == "unit-shard-$(shard)-$(System.JobAttempt)" for step in job["steps"])
    run = next(step for step in job["steps"] if "bash" in step)
    assert "--unit-shard" in run["bash"] and "--unit-shard-output" in run["bash"]
    assert run["env"]["COVERAGE_FILE"].endswith("/coverage.dat")
    assert run["env"]["UNIT_RUN_ID"] == "$(Build.BuildId)"
    assert run["env"]["UNIT_COMMIT"] == "$(Build.SourceVersion)"
    assert run["env"]["UNIT_ATTEMPT"] == "$(System.JobAttempt)"
    combine = next(step for step in gate["steps"] if "bash" in step)
    assert "_unit_shards.py" in combine["bash"]
    assert combine["env"] == {name: run["env"][name] for name in ("UNIT_RUN_ID", "UNIT_COMMIT")}
    assert not (ROOT / ".azure-devops/templates/pip-cache.yml").exists()
    assert "PIP_CACHE_DIR" not in run["env"]
    assert "pip-cache" not in str(stages) and "Cache@2" not in str(stages)
    assert "condition" not in run


def test_service_stages_require_all_prechecks_but_remain_independent_retry_targets():
    template = yaml.safe_load((ROOT / ".azure-devops/templates/integration-service.yml").read_text())
    stage, = template["stages"]
    assert stage["stage"] == "${{ parameters.service }}"
    assert stage["dependsOn"] == ["Build", "Lint", "Unit"]
    assert " ".join(stage["condition"].split()) == (
        "and(not(canceled()), eq(dependencies.Build.result, 'Succeeded'), "
        "eq(dependencies.Lint.result, 'Succeeded'), eq(dependencies.Unit.result, 'Succeeded'))"
    )
    assert stage["jobs"][0]["strategy"]["maxParallel"] == 1
    steps = stage["jobs"][0]["steps"]
    fallback = next(step for step in steps if "report-incomplete" in step.get("bash", ""))
    publish = next(step for step in steps if step.get("publish") == "attempt")
    assert steps.index(fallback) < steps.index(publish)
    assert fallback["condition"] == publish["condition"] == "succeededOrFailed()"


@pytest.mark.parametrize("service", ["ADR", "ADU"])
@pytest.mark.parametrize("teardown_failed", [False, True])
@pytest.mark.usefixtures("isolated_phase_environment")
def test_generic_phase_uses_fixture_teardown_without_inventory_gate(tmp_path, mocker, monkeypatch, service, teardown_failed):
    monkeypatch.delenv("azext_iot_ado_resource_scope", raising=False)
    output = tmp_path / "phase"
    selection = tmp_path / "selection.json"
    retry.write(selection, {
        "context": dict(CONTEXT, service=service), "phase": "tests", "nodes": [],
        "expected": [], "sequence": 1,
    })
    inventory = mocker.patch.object(
        pipeline.subprocess, "run", side_effect=AssertionError("Generic phases must not scan ARM inventory."),
    )

    def execute(command, env, _log, runtime, cleanup):
        assert [arg for arg in command if arg.startswith("--timeout")] == (["--timeout=900"] if service == "ADR" else [])
        assert runtime == (pipeline.BUDGETS[service]["job_timeout_minutes"] - 20) * 60
        assert cleanup == 600
        assert "azext_iot_ado_resource_scope" not in env
        value = receipt({"case": "passed"})
        value["expected"] = ["case"]
        if teardown_failed:
            value["reports"]["case"]["teardown"] = ["failed"]
            value["exitstatus"] = 1
        retry.write(env["azext_iot_ado_receipt"], value)
        return {"exit_code": value["exitstatus"], "timed_out": False, "interrupted": False}

    mocker.patch("azext_iot.tests._dps_phase_runner.child", side_effect=execute)
    pipeline.phase(selection, output)
    assert retry.read(output / "phase.json")["safe"]
    assert retry.read(output / "phase.json")["cleanupMode"] == "handoff"
    inventory.assert_not_called()
    assert not (output / "cleanup.json").exists()


@pytest.mark.parametrize("name", pipeline.GENERIC_PHASE_OVERRIDES)
@pytest.mark.usefixtures("isolated_phase_environment")
def test_generic_phase_still_rejects_external_fixture_and_selection_overrides(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "sentinel")
    selection = tmp_path / "selection.json"
    retry.write(selection, {
        "context": CONTEXT, "phase": "tests", "nodes": [], "expected": [], "sequence": 1,
    })
    with pytest.raises(ValueError, match="Fresh service attempts reject"):
        pipeline.phase(selection, tmp_path / "phase")


@pytest.mark.parametrize("workers", ["0", "2"])
def test_real_plugin_records_outcomes_without_intercepting_http(tmp_path, workers):
    scope = {key: CONTEXT[key] for key in ("subscription", "resource_group")}
    for name, provider in (("hub", "Microsoft.Devices"), ("adu", "Microsoft.DeviceUpdate")):
        url = (f"https://management.azure.com/subscriptions/{scope['subscription']}"
               f"/providers/{provider}/checkNameAvailability?api-version=1&sig=private-secret")
        (tmp_path / f"test_{name}.py").write_text(
            "import requests\n"
            "def test_resource(monkeypatch):\n"
            "    sent = []\n"
            "    def send(adapter, request, **kwargs):\n"
            "        sent.append(request.method)\n"
            "        response = requests.Response()\n"
            "        response.status_code = 200\n"
            "        return response\n"
            "    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)\n"
            f"    requests.post({url!r})\n"
            "    for method in ('PUT', 'PATCH', 'DELETE'):\n"
            "        requests.request(method, 'https://management.azure.com/subscriptions/other/'\n"
            "                          'resourceGroups/other/providers/Microsoft.Resources/deployments/test')\n"
            "    assert sent == ['POST', 'PUT', 'PATCH', 'DELETE']\n",
            encoding="utf-8",
        )
    path = tmp_path / "receipt.json"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-n", workers, "--dist=loadfile",
         "-p", "azext_iot.tests._ado_retry_plugin"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
        env=dict(os.environ, azext_iot_ado_receipt=str(path), azext_iot_ado_resource_scope=json.dumps(scope),
                 PYTEST_ADDOPTS="", PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)]))),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = retry.read(path)
    assert "resourceScope" not in value and "resourceRoots" not in value
    assert "private-secret" not in path.read_text()
    assert len(retry.outcomes(value)) == 2


@pytest.mark.skipif(sys.platform != "linux", reason="ADO controller uses Linux process groups")
@pytest.mark.usefixtures("isolated_phase_environment")
def test_real_offline_first_failure_then_manual_exact_case_recovery(tmp_path, monkeypatch, capsys):
    wheel = tmp_path / "wheel"
    wheel.mkdir()
    (wheel / "offline.whl").write_bytes(b"offline candidate hash only")
    history = tmp_path / "history"
    history.mkdir()
    retry.write(history / "integration-plan-1/plan.json", [{
        "service": "RetrySelfTest", "python": "3.13", "region": "australiaeast",
        "endpoint": pipeline.TARGET["PUBLIC_ARM"],
    }])
    original = history / "integration-wheel-1"
    original.mkdir()
    (original / "offline.whl").write_bytes((wheel / "offline.whl").read_bytes())
    monkeypatch.setenv("BUILD_BUILDID", "offline-123")
    monkeypatch.setenv("BUILD_SOURCEVERSION", "a" * 40)
    environment = dict(
        os.environ, BUILD_BUILDID="offline-123", SYSTEM_DEFINITIONID="147", BUILD_SOURCEVERSION="a" * 40,
        SYSTEM_JOBATTEMPT="1", AZURE_TEST_RUN_LIVE="False",
        PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)])),
    )
    command = [
        sys.executable, str(ROOT / "azext_iot/tests/_ado_pipeline.py"), "run",
        "--service", "RetrySelfTest", "--python", "3.13", "--region", "australiaeast",
        "--endpoint", pipeline.TARGET["PUBLIC_ARM"], "--wheel", str(wheel), "--history", str(history), "--diagnostic",
    ]
    first = subprocess.run(command + ["--output", str(history / "first")], env=environment,
                           cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert first.returncode == 1, first.stdout + first.stderr
    record = retry.read(history / "first/attempt.json")
    assert record["executionErrors"] == [], first.stdout + first.stderr
    assert len(record["phases"]["tests"]["receipt"]["collected"]) == 3
    assert len(retry.pending([record], record["context"])["tests"]) == 1
    with pytest.raises(ValueError, match="Unresolved"):
        pipeline.gate(history)
    environment["SYSTEM_JOBATTEMPT"] = "2"
    second = subprocess.run(command + ["--output", str(history / "second")], env=environment,
                            cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert second.returncode == 0, second.stdout + second.stderr
    recovered = retry.read(history / "second/attempt.json")
    assert len(recovered["phases"]["tests"]["receipt"]["collected"]) == 1
    assert not retry.pending([record, recovered], record["context"])
    assert record == retry.read(history / "first/attempt.json")
    pipeline.gate(history)
    assert "NOT release qualification" in capsys.readouterr().out
    environment["SYSTEM_JOBATTEMPT"] = "3"
    third = subprocess.run(command + ["--output", str(history / "third")], env=environment,
                           cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert third.returncode == 0, third.stdout + third.stderr
    assert retry.read(history / "third/attempt.json")["mode"] == "reuse"
    assert not (history / "third/tests").exists()
    pipeline.gate(history)
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "4")
    pipeline.reject(history / "fourth", "login did not complete", recoverable=True,
                    service="RetrySelfTest", python="3.13", region="australiaeast")
    with pytest.raises(ValueError, match="full-service recovery"):
        pipeline.gate(history)
    environment["SYSTEM_JOBATTEMPT"] = "5"
    fifth = subprocess.run(command + ["--output", str(history / "fifth")], env=environment,
                           cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert fifth.returncode == 0, fifth.stdout + fifth.stderr
    full = retry.read(history / "fifth/attempt.json")
    assert full["mode"] == "full" and full["missingAttempts"] == [4]
    assert len(full["phases"]["tests"]["receipt"]["collected"]) == 3
    pipeline.gate(history)


def test_final_gate_requires_every_scheduled_combination(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_BUILDID", CONTEXT["build"])
    monkeypatch.setenv("BUILD_SOURCEVERSION", CONTEXT["commit"])
    retry.write(tmp_path / "integration-plan-1/plan.json", [
        {"service": service, "python": "3.13", "region": "australiaeast", "endpoint": CONTEXT["endpoint"]}
        for service in ("ADR", "ADU")
    ])
    retry.write(tmp_path / "attempt-ADR/attempt.json", attempt(dict.fromkeys(("a", "b", "c"), "passed")))
    with pytest.raises(ValueError, match="combinations"):
        pipeline.gate(tmp_path)


def test_duplicate_attempt_artifacts_rejected(tmp_path):
    record = attempt({"a": "passed", "b": "failed", "c": "passed"})
    retry.write(tmp_path / "one/attempt.json", record)
    retry.write(tmp_path / "two/attempt.json", deepcopy(record))
    with pytest.raises(ValueError):
        retry.load_history(tmp_path, CONTEXT)


@pytest.mark.parametrize("changed", ["deleted", "modified", "ledger"])
def test_raw_artifacts_are_required_and_immutable(tmp_path, changed):
    record = attempt({"a": "passed", "b": "passed", "c": "passed"})
    path = tmp_path / "tests/phase.json"
    retry.write(path, record["phases"]["tests"])
    record["evidence"] = retry.evidence(tmp_path)
    retry.verify_artifacts(tmp_path / "attempt.json", record)
    if changed == "deleted":
        path.unlink()
    elif changed == "modified":
        path.write_text("{}")
    else:
        record["phases"]["tests"]["safe"] = False
    with pytest.raises(ValueError):
        retry.verify_artifacts(tmp_path / "attempt.json", record)


def test_missing_intermediate_native_attempt_forces_full_service(tmp_path, monkeypatch, mocker):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    ctx = dict(CONTEXT, service="RetrySelfTest", diagnostic="true")
    first["context"] = ctx
    mocker.patch.object(pipeline, "context", return_value=ctx)
    monkeypatch.setitem(pipeline.RETRY, "load_history", lambda *_: [first])
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "3")
    args = SimpleNamespace(
        service="RetrySelfTest", python="3.13", region="australiaeast", endpoint=CONTEXT["endpoint"],
        wheel=tmp_path, diagnostic=True, history=tmp_path / "history", output=tmp_path / "attempt",
    )
    (tmp_path / "candidate.whl").write_bytes(b"offline")

    def execute(command, _env, _log, *_args):
        selection = retry.read(command[command.index("--selection") + 1])
        assert selection["nodes"] == []
        assert selection["expected"] == ["a", "b", "c"]
        folder = Path(command[command.index("--output") + 1])
        retry.write(folder / "phase.json", {
            "expected": ["a", "b", "c"], "safe": True, "receipt": receipt(dict.fromkeys(("a", "b", "c"), "passed")),
        })
        return {"exit_code": 0, "timed_out": False, "interrupted": False}

    mocker.patch("azext_iot.tests._dps_phase_runner.child", side_effect=execute)
    assert pipeline.run(args) == 0
    record = retry.read(args.output / "attempt.json")
    assert record["mode"] == "full" and record["missingAttempts"] == [2]
    assert not retry.pending([first, record], ctx)


def test_controller_keeps_all_completed_sibling_phases_when_one_fails(tmp_path, monkeypatch, mocker):
    ctx = dict(CONTEXT, service="RetrySelfTest", diagnostic="true")
    mocker.patch.object(pipeline, "context", return_value=ctx)
    mocker.patch.object(pipeline, "owned_nodes", return_value={name: ["case"] for name in ("bad", "one", "two")})
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "1")
    args = SimpleNamespace(
        service="RetrySelfTest", python="3.13", region="australiaeast", endpoint=ctx["endpoint"],
        wheel=tmp_path, diagnostic=True, history=tmp_path / "history", output=tmp_path / "attempt",
    )
    (tmp_path / "candidate.whl").write_bytes(b"offline")

    def execute(command, _env, _log, *_args):
        folder = Path(command[command.index("--output") + 1])
        code = int(folder.name == "bad")
        if not code:
            retry.write(folder / "phase.json", {"expected": ["case"], "safe": True, "receipt": receipt({"case": "passed"})})
        else:
            pipeline.reject(folder, "Independent cleanup proof is missing.")
        return {"exit_code": code, "timed_out": False, "interrupted": False}

    mocker.patch("azext_iot.tests._dps_phase_runner.child", side_effect=execute)
    with pytest.raises(ValueError, match="bad:"):
        pipeline.run(args)
    record = retry.read(args.output / "attempt.json")
    assert set(record["phases"]) == {"one", "two"}
    assert len(record["executionErrors"]) == 1
    assert record["executionErrors"] == ["bad: Independent cleanup proof is missing."]
    retry.verify_artifacts(args.output / "attempt.json", record)
    assert (args.output / "rejection.json").is_file()
    assert (args.output / "final.xml").is_file()


def test_full_fallback_dispatches_every_service_phase(tmp_path, monkeypatch, mocker):
    ctx = dict(CONTEXT, service="RetrySelfTest", diagnostic="true")
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    first["context"] = ctx
    first["phases"]["tests"]["receipt"]["reports"]["b"] = {"setup": ["failed"], "teardown": ["passed"]}
    first["phases"]["passing-phase"] = deepcopy(attempt(dict.fromkeys(("a", "b", "c"), "passed"))["phases"]["tests"])
    manifests = dict.fromkeys(first["phases"], ["a", "b", "c"])
    mocker.patch.object(pipeline, "context", return_value=ctx)
    mocker.patch.object(pipeline, "owned_nodes", return_value=manifests)
    monkeypatch.setitem(pipeline.RETRY, "load_history", lambda *_: [first])
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "2")
    (tmp_path / "candidate.whl").write_bytes(b"offline")
    args = SimpleNamespace(
        service="RetrySelfTest", python="3.13", region="australiaeast", endpoint=ctx["endpoint"],
        wheel=tmp_path, diagnostic=True, history=tmp_path / "history", output=tmp_path / "attempt",
    )

    def execute(command, _env, _log, *_args):
        selection = retry.read(command[command.index("--selection") + 1])
        assert selection["nodes"] == ["a", "b", "c"]
        folder = Path(command[command.index("--output") + 1])
        retry.write(folder / "phase.json", {
            "expected": ["a", "b", "c"], "safe": True, "receipt": receipt(dict.fromkeys(("a", "b", "c"), "passed")),
        })
        return {"exit_code": 0, "timed_out": False, "interrupted": False}

    child = mocker.patch("azext_iot.tests._dps_phase_runner.child", side_effect=execute)
    assert pipeline.run(args) == 0
    assert child.call_count == 2
    record = retry.read(args.output / "attempt.json")
    assert record["mode"] == "full" and set(record["phases"]) == set(manifests)


@pytest.mark.parametrize("primary_failure", [False, True])
def test_actual_cleanup_ledger_never_promotes_failed_cleanup(primary_failure):
    from azext_iot.tests.adr._helpers import CleanupLedger

    def failed_cleanup():
        raise TimeoutError("Original cleanup confirmation failed.")

    with pytest.raises(AssertionError) as captured:
        with CleanupLedger() as ledger:
            ledger.register("offline-owned", failed_cleanup)
            assert not primary_failure, "Original test assertion."
    assert not retry.retryable_failure(captured.value)
    if primary_failure:
        assert str(captured.value).startswith("Original test assertion.")
        assert type(captured.value) is AssertionError
    else:
        assert isinstance(captured.value, retry.InfrastructureFailure)


def test_actual_full_infra_finally_cleanup_marks_the_original_assertion(mocker):
    from azext_iot.tests.adr._helpers import ADRFullInfraHelper
    helper = ADRFullInfraHelper()
    helper._owned_resources = {("namespace", "offline-owned", "offline-rg"): None}
    mocker.patch.object(helper, "_cleanup_owned_resource", side_effect=TimeoutError("Cleanup confirmation failed"))
    with pytest.raises(AssertionError) as captured:
        try:
            assert False, "Primary test failure"
        finally:
            helper.cleanup_full_infra()
    assert type(captured.value) is AssertionError
    assert "Primary test failure" in str(captured.value)
    assert not retry.retryable_failure(captured.value)


def test_wrapped_cleanup_failure_cannot_be_misclassified_as_a_test_failure():
    with pytest.raises(RuntimeError) as captured:
        try:
            raise retry.CleanupFailure("private cleanup detail")
        except retry.CleanupFailure:
            raise RuntimeError("wrapped") from None
    assert not retry.retryable_failure(captured.value)
    captured.value.__context__.__context__ = captured.value
    assert not retry.retryable_failure(captured.value)


@pytest.mark.parametrize("classification", [None, "true", 1, []])
@pytest.mark.parametrize("cleanup_verified", [False, True])
def test_missing_or_malformed_failure_classification_never_becomes_cleanup_recovery(classification, cleanup_verified):
    value = receipt({"failed": "failed"})
    value["retryableFailures"]["failed"] = classification
    with pytest.raises(ValueError, match="classification is missing"):
        retry.outcomes(value, allow_fixture_failures=cleanup_verified)


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("expression", [
    "raise UnauthorizedError('private-auth-details')",
    "raise TimeoutError('private-timeout-details')",
    "raise RuntimeError('private-infrastructure-details')",
    "raise InfrastructureFailure('private-link-readiness-details')",
    "pytest.fail('private-explicit-test-failure')",
    "try:\n        raise RuntimeError('private-cause')\n    except RuntimeError:\n        assert False",
])
def test_real_completed_call_failures_can_be_retried_without_erasing_failure(tmp_path, expression, owned):
    source = tmp_path / "test_unsafe.py"
    source.write_text(
        "import pytest\nfrom azure.cli.core.azclierror import UnauthorizedError\n"
        "from azext_iot.tests._ado_retry import InfrastructureFailure\n"
        "def test_unsafe():\n    " + expression + "\n", encoding="utf-8",
    )
    path = tmp_path / "receipt.json"
    command = [sys.executable, "-m", "pytest", str(source), "-q", "-p", "azext_iot.tests._ado_retry_plugin"]
    if owned:
        script = (
            "import pytest\nfrom pathlib import Path\n"
            "from azext_iot.tests._hub_suite_plugin import PhaseReceipt\n"
            f"plugin=PhaseReceipt('DPS','regular',['test_unsafe.py::test_unsafe'],Path({str(path)!r}),'offline',"
            "debug={'attempt':'a'*64})\n"
            "raise SystemExit(pytest.main(['test_unsafe.py::test_unsafe','-q'],plugins=[plugin]))\n"
        )
        command = [sys.executable, "-c", script]
    result = subprocess.run(
        command,
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
        env=dict(os.environ, azext_iot_ado_receipt=str(path), PYTEST_ADDOPTS="",
                 PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)]))),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "private-" not in path.read_text()
    value = retry.read(path)
    assert list(retry.outcomes(value).values()) == ["failed"]
    assert list(value["retryableFailures"].values()) == [True]


@pytest.mark.parametrize("workers,distribution", [("0", "load"), ("2", "loadgroup"), ("2", "loadfile")])
def test_real_plugin_selects_exact_parameterized_failures_with_xdist(tmp_path, workers, distribution):
    source = tmp_path / "test_cases.py"
    source.write_text(
        "import os\nimport pytest\n"
        "@pytest.mark.xdist_group('shared')\n"
        "@pytest.mark.parametrize('value', ['secret-one', 'secret-two', "
        "pytest.param('disabled', marks=pytest.mark.skip(reason='checked-in exclusion'))])\n"
        "def test_case(value):\n"
        "    assert value != 'secret-two' or os.environ.get('OFFLINE_RECOVER') == 'yes'\n",
        encoding="utf-8",
    )
    path = tmp_path / "receipt.json"
    environment = dict(
        os.environ, azext_iot_ado_receipt=str(path),
        PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)])),
        PYTEST_ADDOPTS="",
    )
    command = [
        sys.executable, "-m", "pytest", str(source), "-q", "-p", "azext_iot.tests._ado_retry_plugin",
        "-n", workers, "--dist=" + distribution,
    ]
    first = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert first.returncode == 1, first.stdout + first.stderr
    value = retry.read(path)
    assert len(retry.outcomes(value)) == 2
    assert len(value["excluded"]) == 1
    assert "secret-" not in path.read_text()
    selected = [node for node, outcome in retry.outcomes(value).items() if outcome == "failed"]
    environment.update(
        OFFLINE_RECOVER="yes", azext_iot_ado_selected=json.dumps(selected),
        azext_iot_ado_expected=json.dumps(value["expected"]), azext_iot_ado_receipt=str(tmp_path / "retry.json"),
    )
    second = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60, check=False)
    assert second.returncode == 0, second.stdout + second.stderr
    assert retry.outcomes(retry.read(tmp_path / "retry.json")) == {selected[0]: "passed"}


@pytest.mark.parametrize("defect", ["worker-exit", "worker-finish", "controller-finish", "exclusions"])
def test_generic_parallel_receipt_rejects_worker_and_finish_failures(tmp_path, defect):
    (tmp_path / "test_cases.py").write_text(
        "import os\nimport pytest\n"
        "def test_case():\n"
        "    if os.environ['PROOF_DEFECT'] == 'worker-exit':\n"
        "        os._exit(3)\n"
        "def test_other():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        "import os\nimport pytest\n"
        "def pytest_sessionfinish(session):\n"
        "    defect = os.environ['PROOF_DEFECT']\n"
        "    worker = hasattr(session.config, 'workerinput')\n"
        "    if (defect == 'worker-finish' and worker) or (defect == 'controller-finish' and not worker):\n"
        "        raise RuntimeError('private worker detail')\n"
        "def pytest_collection_modifyitems(items):\n"
        "    if os.environ['PROOF_DEFECT'] == 'exclusions' and os.environ.get('PYTEST_XDIST_WORKER') == 'gw1':\n"
        "        items[-1].add_marker(pytest.mark.skip(reason='inconsistent exclusion'))\n",
        encoding="utf-8",
    )
    path = tmp_path / "receipt.json"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-n", "2", "--max-worker-restart=0",
         "-p", "azext_iot.tests._ado_retry_plugin"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
        env=dict(os.environ, azext_iot_ado_receipt=str(path), PROOF_DEFECT=defect, PYTEST_ADDOPTS="",
                 PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)]))),
    )
    assert result.returncode != 0, result.stdout + result.stderr
    value = retry.read(path)
    with pytest.raises(ValueError):
        retry.outcomes(value)
    assert "private worker detail" not in path.read_text()
