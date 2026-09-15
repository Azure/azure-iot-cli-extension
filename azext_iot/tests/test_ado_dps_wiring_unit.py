# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".azure-devops/templates/run-tests-parallel.yml"
CONTROLLER_ENV = (
    "azext_iot_dps_test_phase", "azext_iot_dps_phase_receipts", "azext_iot_dps_run_uid",
    "azext_iot_dps_test_subscription", "azext_iot_dps_test_resource_group",
)


def _script():
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    integration = next(
        value for step in template["steps"] for key, value in step.items()
        if "if eq(parameters.runIntTests" in key
    )
    task = next(step for step in integration if step.get("task") == "AzureCLI@2")
    return next(
        value["inlineScript"] for key, value in task["inputs"].items()
        if "contains(parameters.path, 'azext_iot/tests/dps')" in key
    )


def test_ado_dps_template_has_one_honestly_scoped_legacy_invocation():
    script = _script()
    commands = [line.strip() for line in script.splitlines() if line.strip().startswith("pytest ")]
    assert len(commands) == 1
    command = commands[0]
    assert command.startswith('pytest -vv ${{ parameters.path }} -k "_int.py"')
    assert "--ignore=azext_iot/tests/dps/core/test_dps_disable_local_auth_int.py" in command
    assert "-n ${{ parameters.num_threads }}" in command
    assert "--reruns ${{ parameters.num_reruns }}" in command
    assert "--junitxml=junit/test-iotext-int.xml" in command
    assert "legacy regular only" in script
    assert "Service-SAS and owned local-auth-toggle coverage run through the GitHub DPS controller" in script
    assert "_dps_phase_runner.py" not in script
    assert "unset " not in script
    assert not re.search(r"(?:export\s+)?azext_iot_dps_test_phase=", script)


def test_ado_callers_do_not_supply_the_canary_owned_controller_contract():
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    parameters = {item["name"] for item in template["parameters"]}
    assert "serviceConnection" in parameters
    assert {"subscription", "resourceGroup", "region"}.isdisjoint(parameters)
    trigger = yaml.safe_load((ROOT / ".azure-devops/templates/trigger-tests.yml").read_text(encoding="utf-8"))
    dps = next(job for job in trigger["jobs"] if job["job"] == "testDPS")
    assert dps["timeoutInMinutes"] == 90
    call = dps["steps"][0]
    assert call["parameters"]["serviceConnection"] == "$(AzureServiceConnection)"
    assert call["parameters"]["path"] == "azext_iot/tests/dps"
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text(encoding="utf-8"))
    test_stage = next(stage for stage in entry["stages"] if stage["stage"] == "test")
    assert any("msi" in condition for condition in test_stage["pool"])
    assert test_stage["jobs"][0]["parameters"]["maxParallelDPS"] == 2


def _execute(tmp_path, overrides=None, exit_code=0):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("The AzureCLI bash-script execution proof requires bash.")
    parameters = {
        "path": "azext_iot/tests/dps", "name": "unit-dps",
        "num_threads": 6, "num_reruns": 2, "reruns_delay": 60,
    }
    script = re.sub(
        r"\$\{\{\s*parameters\.(\w+)\s*\}\}", lambda match: str(parameters[match.group(1)]), _script(),
    )
    record = tmp_path / "pytest-calls"
    environment = {key: value for key, value in os.environ.items() if key not in CONTROLLER_ENV}
    environment.update(
        PYTEST_RECORD=str(record), PYTEST_EXIT=str(exit_code), azext_iot_testdps="supplied-unit-pin",
        **(overrides or {}),
    )
    result = subprocess.run(
        [bash, "-c", 'pytest() { printf "%s\\n" "$*" "$azext_iot_testdps" >> "$PYTEST_RECORD"; '
         'return "$PYTEST_EXIT"; }\n' + script],
        env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=5, check=False,
    )
    return result, record.read_text(encoding="utf-8").splitlines() if record.exists() else []


@pytest.mark.parametrize("exit_code", [0, 1, 5])
def test_ado_legacy_script_runs_once_preserves_pins_and_propagates_pytest_exit(tmp_path, exit_code):
    result, calls = _execute(tmp_path, exit_code=exit_code)
    assert result.returncode == exit_code
    assert len(calls) == 2
    arguments = shlex.split(calls[0])
    assert arguments[1] == "azext_iot/tests/dps"
    assert arguments[arguments.index("-n") + 1] == "6"
    assert "--ignore=azext_iot/tests/dps/core/test_dps_disable_local_auth_int.py" in arguments
    assert calls[1] == "supplied-unit-pin"
    assert "legacy regular only" in result.stdout


@pytest.mark.parametrize("override", [
    {"azext_iot_dps_test_phase": "regular"},
    {"azext_iot_dps_test_phase": "service-sas"},
    {"azext_iot_dps_test_phase": "local-auth-toggle"},
    *({name: "supplied-controller-value"} for name in CONTROLLER_ENV[1:]),
])
def test_ado_rejects_controller_overrides_before_any_test_execution(tmp_path, override):
    result, calls = _execute(tmp_path, override)
    assert result.returncode == 2
    assert not calls
    assert "rejects isolated phase overrides" in result.stderr
    assert "supplied-controller-value" not in result.stderr


def _hub_wiring():
    template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    integration = next(
        value for step in template["steps"] for key, value in step.items()
        if "if eq(parameters.runIntTests" in key
    )
    task = next(step for step in integration if step.get("task") == "AzureCLI@2")
    script = next(value["inlineScript"] for key, value in task["inputs"].items()
                  if "ne(parameters.hubSuite, '')" in key)
    admission = next(
        child for step in template["steps"] for key, children in step.items()
        if "ne(parameters.hubSuite, '')" in key for child in children
        if child.get("task") == "PythonScript@0"
    )
    return template, task, script, admission


def test_ado_hub_uses_shared_controller_without_legacy_pins_or_hidden_failures():
    template, task, script, admission = _hub_wiring()
    assert "pytest " not in script
    assert 'python -m azext_iot.tests._hub_phase_runner --suite "${{ parameters.hubSuite }}"' in script
    assert '--subscription "$azext_iot_hub_subscription"' in script
    assert '--resource-group "$azext_iot_testrg"' in script
    assert '--region "$azext_iot_testhub_location" --output test-result/hub-phases' in script
    assert "set -euo pipefail" in script
    assert task["${{ if ne(parameters.hubSuite, '') }}"]["continueOnError"] is False
    assert task["${{ else }}"]["continueOnError"] is True  # Preserve unrelated DPS behavior.
    assert admission["displayName"].endswith("before Azure login")
    sentinel = next(step for step in template["steps"] if "${{ if eq(parameters.hubSuite, '') }}" in step)
    assert sentinel["${{ if eq(parameters.hubSuite, '') }}"][0]["template"] == "set-testenv-sentinel.yml"
    hub_publish = [child for step in template["steps"] for key, children in step.items()
                   if "ne(parameters.hubSuite, '')" in key for child in children
                   if child.get("task") == "PublishBuildArtifacts@1"]
    assert {step["inputs"]["pathToPublish"] for step in hub_publish} == {
        "test-result/", ".coverage.${{ parameters.name }}",
    }
    junit = [child for step in template["steps"] for key, children in step.items()
             if "ne(parameters.hubSuite, '')" in key for child in children
             if child.get("task") == "PublishTestResults@2"]
    assert len(junit) == 1
    assert junit[0]["inputs"]["testResultsFiles"] == "test-result/hub-phases/**/junit.xml"
    assert junit[0]["inputs"]["failTaskOnFailedTests"] is True
    assert junit[0]["inputs"]["failTaskOnMissingResultsFile"] is True
    assert not any(step.get("task") == "PublishTestResults@2" for step in template["steps"])


def test_ado_hub_public_jobs_are_serial_with_full_budgets_and_no_folder_selection():
    trigger = yaml.safe_load((ROOT / ".azure-devops/templates/trigger-tests.yml").read_text(encoding="utf-8"))
    hub_jobs = [job for job in trigger["jobs"] if job["job"].startswith("Hub")]
    assert [job["job"] for job in hub_jobs] == ["HubControl", "HubData"]
    assert [job["timeoutInMinutes"] for job in hub_jobs] == [190, 360]
    assert hub_jobs[1]["dependsOn"] == "HubControl"
    assert {"testDPS", "testADU", "testADR"}.issubset(hub_jobs[0]["dependsOn"])
    for job in hub_jobs:
        assert job["strategy"]["maxParallel"] == 1
        parameters = job["steps"][0]["parameters"]
        assert parameters["hubSuite"] == job["job"]
        assert "path" not in parameters
        assert parameters["hubSubscription"] == "${{ parameters.hubSubscription }}"
    assert "azext_iot/tests/iothub/" not in TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("platform,override,expected", [
    ("linux", {}, 0), ("win32", {}, 1),
    ("linux", {"azext_iot_hub_subscription": "foreign"}, 1),
    ("linux", {"azext_iot_testrg": "foreign"}, 1),
    ("linux", {"azext_iot_testhub_location": "westus"}, 1),
    ("linux", {"azext_iot_hubsas_subscription": "ambient"}, 1),
    ("linux", {"azext_iot_testhub": "pinned"}, 1),
])
def test_ado_hub_admission_rejects_unsupported_scope_platform_and_ambient_pins(platform, override, expected):
    script = _hub_wiring()[3]["inputs"]["script"].replace("${{ parameters.hubSuite }}", "HubData")
    env = {
        "PATH": os.environ.get("PATH", ""), "azext_iot_hub_subscription": "a386d5ea-ea90-441a-8263-d816368c84a1",
        "azext_iot_testrg": "cli-int-test-rg", "azext_iot_testhub_location": "centraluseuap",
    }
    env.update(override)
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", f"import sys; sys.platform = {platform!r}\n" + script],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if platform == "win32":
        assert "unsupported on Windows" in result.stderr


@pytest.mark.parametrize("exit_code,subscription,expected", [
    (0, "authorized", 0), (1, "authorized", 1), (5, "authorized", 5), (0, "foreign", 2),
])
def test_ado_hub_controller_failure_and_service_connection_mismatch_fail_job(exit_code, subscription, expected):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("AzureCLI script proof requires bash.")
    script = _hub_wiring()[2].replace("${{ parameters.name }}", "HubData").replace(
        "${{ parameters.hubSuite }}", "HubData",
    )
    stubs = (
        'az() { printf "%s\\n" "$OFFLINE_SUBSCRIPTION"; }\n'
        'python() { printf "%s\\n" "$@"; return "$OFFLINE_EXIT"; }\n'
    )
    result = subprocess.run(
        [bash, "-c", stubs + script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
        env=dict(os.environ, azext_iot_hub_subscription="authorized", azext_iot_testrg="cli-int-test-rg",
                 azext_iot_testhub_location="centraluseuap", OFFLINE_SUBSCRIPTION=subscription,
                 OFFLINE_EXIT=str(exit_code)),
    )
    assert result.returncode == expected
    if subscription == "foreign":
        assert "does not match" in result.stderr
        assert "_hub_phase_runner" not in result.stdout
    else:
        assert result.stdout.splitlines() == [
            "-m", "azext_iot.tests._hub_phase_runner", "--suite", "HubData",
            "--subscription", "authorized", "--resource-group", "cli-int-test-rg",
            "--region", "centraluseuap", "--output", "test-result/hub-phases",
        ]
