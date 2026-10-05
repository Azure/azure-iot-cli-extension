# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for manual retry ancestry, exact selection and the real diagnostic subprocess."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
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


def receipt(results):
    return {
        "finished": True, "exitstatus": int("failed" in results.values()), "collected": list(results),
        "reports": {node: {"setup": ["passed"], "call": [outcome], "teardown": ["passed"]}
                    for node, outcome in results.items()},
        "retryableFailures": {node: True for node, outcome in results.items() if outcome == "failed"},
    }


def attempt(results, previous=None):
    return {
        "schema": 1, "context": CONTEXT.copy(), "sequence": previous["sequence"] + 1 if previous else 1,
        "nativeAttempt": previous["nativeAttempt"] + 1 if previous else 1,
        "parent": retry.digest(previous) if previous else None, "healthy": True,
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
        second["healthy"] = False
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
    with pytest.raises(ValueError):
        retry.evaluate([first, second], CONTEXT)


def test_failed_retry_stays_failed_and_unhealthy_first_attempt_cannot_be_erased():
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    second = attempt({"b": "failed"}, first)
    assert retry.pending([first, second], CONTEXT) == {"tests": ["b"]}
    first["healthy"] = False
    second = attempt({"b": "passed"}, first)
    with pytest.raises(ValueError):
        retry.evaluate([first, second], CONTEXT)


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


@pytest.mark.parametrize("hour,minutes", [(8, 360), (12, 90), (13, 10)])
def test_cleanup_window_rejected_before_network(hour, minutes, mocker):
    get = mocker.patch("requests.get", side_effect=AssertionError("No HTTP before time admission"))
    with pytest.raises(ValueError, match="cleanup"):
        pipeline.admission(minutes, datetime(2026, 10, 5, hour, tzinfo=timezone.utc))
    get.assert_not_called()


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


def test_yaml_exposes_manual_only_services_and_non_live_default():
    entry_text = (ROOT / ".azure-devops/integration_tests.yml").read_text()
    entry = yaml.safe_load(entry_text)
    parameters = {value["name"]: value for value in entry["parameters"]}
    assert parameters["mode"]["default"] == "Dry run"
    assert parameters["mode"]["values"] == ["Dry run", "Integration tests"]
    assert len(entry["stages"]) == 2
    assert entry["stages"][0]["stage"] == "Plan"
    assert [job["job"] for job in entry["stages"][0]["jobs"]] == ["Plan"]
    assert "${{ if eq(parameters.mode, 'Integration tests') }}" in entry["stages"][1]
    assert parameters["services"]["values"] == list(retry.SERVICES)
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


def test_build_lint_and_unit_stages_are_independent_and_keep_artifacts():
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())
    integration = entry["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    stages = {stage["stage"]: stage for stage in integration if "stage" in stage}
    assert list(stages) == ["Build", "Lint", "Unit", "Qualify"]
    for name in ("Build", "Lint", "Unit"):
        assert stages[name]["dependsOn"] == "Plan"
        assert [job["job"] for job in stages[name]["jobs"]] == [name]
    build_steps = stages["Build"]["jobs"][0]["steps"]
    assert any(step.get("artifact") == "integration-wheel-$(System.JobAttempt)" for step in build_steps)
    lint = next(step["bash"] for step in stages["Lint"]["jobs"][0]["steps"] if "bash" in step)
    unit_steps = stages["Unit"]["jobs"][0]["steps"]
    unit = next(step["bash"] for step in unit_steps if "bash" in step)
    assert "python -m tox r -e lint -vv" in lint
    assert "python-azcur-unit" not in lint
    assert "python -m tox r -e clean,python-azcur-unit,report -vv" in unit
    assert "lint" not in unit
    publish = next(step for step in unit_steps if step.get("task") == "PublishTestResults@2")
    assert publish["inputs"]["failTaskOnFailedTests"] is True
    assert publish["inputs"]["failTaskOnMissingResultsFile"] is True
    assert any(step.get("artifact") == "integration-unit-coverage-$(System.JobAttempt)" for step in unit_steps)
    assert stages["Qualify"]["dependsOn"] == [
        "Plan", "Build", "Lint", "Unit", {"${{ each service in parameters.services }}": ["${{ service }}"]},
    ]
    assert "condition" not in stages["Qualify"]


def test_service_stages_require_all_prechecks_but_remain_independent_retry_targets():
    template = yaml.safe_load((ROOT / ".azure-devops/templates/integration-service.yml").read_text())
    stage, = template["stages"]
    assert stage["stage"] == "${{ parameters.service }}"
    assert stage["dependsOn"][:3] == ["Build", "Lint", "Unit"]
    assert " ".join(stage["condition"].split()) == (
        "and(not(canceled()), eq(dependencies.Build.result, 'Succeeded'), "
        "eq(dependencies.Lint.result, 'Succeeded'), eq(dependencies.Unit.result, 'Succeeded'))"
    )
    assert stage["jobs"][0]["strategy"]["maxParallel"] == 1


@pytest.mark.skipif(sys.platform != "linux", reason="ADO controller uses Linux process groups")
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
    assert record["healthy"], first.stdout + first.stderr
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
    assert retry.read(history / "third/attempt.json")["reused"]
    assert not (history / "third/tests").exists()
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


def test_missing_intermediate_native_attempt_rejects_before_execution(tmp_path, monkeypatch, mocker):
    first = attempt({"a": "passed", "b": "failed", "c": "passed"})
    mocker.patch.object(pipeline, "context", return_value=CONTEXT)
    monkeypatch.setitem(pipeline.RETRY, "load_history", lambda *_: [first])
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "3")
    args = SimpleNamespace(
        service="ADR", python="3.13", region="australiaeast", endpoint=CONTEXT["endpoint"],
        wheel=tmp_path, diagnostic=False, history=tmp_path, output=tmp_path / "must-not-exist",
    )
    with pytest.raises(ValueError, match="native job attempt"):
        pipeline.run(args)
    assert not args.output.exists()


@pytest.mark.parametrize("primary_failure", [False, True])
def test_actual_cleanup_ledger_never_promotes_failed_cleanup(primary_failure):
    from azext_iot.tests.adr._helpers import CleanupLedger

    def failed_cleanup():
        raise TimeoutError("Original cleanup confirmation failed.")

    with pytest.raises(AssertionError) as captured:
        with CleanupLedger() as ledger:
            ledger.register("offline-owned", failed_cleanup)
            assert not primary_failure, "Original test assertion."
    assert not retry.assertion_failure(captured.value)
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
    assert not retry.assertion_failure(captured.value)


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("expression", [
    "raise UnauthorizedError('private-auth-details')",
    "raise TimeoutError('private-timeout-details')",
    "raise RuntimeError('private-infrastructure-details')",
    "try:\n        raise RuntimeError('private-cause')\n    except RuntimeError:\n        assert False",
])
def test_real_failure_classification_never_promotes_auth_infrastructure_or_wrapped_errors(tmp_path, expression, owned):
    source = tmp_path / "test_unsafe.py"
    source.write_text(
        "from azure.cli.core.azclierror import UnauthorizedError\n"
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
    with pytest.raises(ValueError, match="infrastructure"):
        retry.outcomes(retry.read(path))


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
