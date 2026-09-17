# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import json
import runpy
import re
import os
import shutil
import subprocess
import sys

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVALUATE = runpy.run_path(str(REPOSITORY_ROOT / "azext_iot/tests/_evaluate_test_results.py"))["evaluate_results"]
MATRIX = [{"service": "ADR", "python": "3.13", "region": "centraluseuap"}]
SUCCESSFUL_JOBS = {
    "setup": "success",
    "unit-test": "success",
    "int-test": "success",
    "gate preparation": "success",
}


@pytest.fixture(params=["github", "ado"])
def macos_openssl_step(request):
    if request.param == "github":
        workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/tox.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["tox"]["steps"]
        selected = next(step for step in steps if step.get("name") == "Select OpenSSL 3 for CSR signing")
        assert steps.index(selected) < next(i for i, step in enumerate(steps) if step.get("name") == "Setup test suite")
    else:
        template = yaml.safe_load(
            (REPOSITORY_ROOT / ".azure-devops/templates/setup-dev-test-env.yml").read_text(encoding="utf-8")
        )
        steps = template["steps"]
        selected = next(step for step in steps if step.get("displayName") == "Select OpenSSL 3 for CSR signing")
        assert steps.index(selected) < next(
            i for i, step in enumerate(steps) if step.get("template") == "download-install-local-azure-iot-cli-extension.yml"
        )
    return request.param, selected


def test_native_openssl_selection_is_scoped_to_macos(macos_openssl_step):
    provider, step = macos_openssl_step
    if provider == "github":
        assert step["if"] == "runner.os == 'macOS'"
        assert step["shell"] == "bash"
        script = step["run"]
    else:
        assert step["condition"] == "and(succeeded(), eq(variables['Agent.OS'], 'Darwin'))"
        script = step["bash"]
    assert "source scripts/select-openssl.sh" in script


@pytest.mark.skipif(os.name != "posix", reason="The macOS dependency-selection step requires a POSIX shell.")
@pytest.mark.parametrize("capability", ["ready", "missing", "unsupported"])
def test_native_openssl_selection_proves_capabilities_before_changing_path(macos_openssl_step, tmp_path, capability):
    provider, step = macos_openssl_step
    bash, openssl = shutil.which("bash"), shutil.which("openssl")
    assert bash and openssl
    prefix = Path(openssl).resolve().parents[1]
    if capability != "ready":
        prefix = tmp_path / "openssl"
        if capability == "unsupported":
            binary = prefix / "bin" / "openssl"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nprintf 'OpenSSL without required signing options\\n'\n", encoding="utf-8")
            binary.chmod(0o700)
    output = tmp_path / "github-path"
    brew = """
brew() {
  test "$#" -eq 2
  test "$1" = --prefix
  test "$2" = openssl@3
  printf '%s\\n' "$OPENSSL_PREFIX"
}
"""
    result = subprocess.run(
        [bash, "-c", brew + (step["run"] if provider == "github" else step["bash"])],
        cwd=REPOSITORY_ROOT,
        env=dict(os.environ, OPENSSL_PREFIX=str(prefix), GITHUB_PATH=str(output)),
        capture_output=True, text=True, timeout=20, check=False,
    )
    ado_path = f"##vso[task.prependpath]{prefix / 'bin'}"
    if capability == "ready":
        assert result.returncode == 0, result.stdout + result.stderr
        if provider == "github":
            assert output.read_text(encoding="utf-8") == str(prefix / "bin") + "\n"
            assert ado_path not in result.stdout
        else:
            assert ado_path in result.stdout.splitlines()
            assert not output.exists()
    else:
        assert result.returncode != 0
        assert not output.exists()
        assert "##vso[task.prependpath]" not in result.stdout


@pytest.mark.parametrize("helper,option", [
    ("_dps_phase_runner.py", "--subscription"),
    ("_evaluate_test_results.py", "--results-dir"),
])
def test_ci_helpers_resolve_checkout_and_execute_without_installed_dependencies(tmp_path, monkeypatch, helper, option):
    script = REPOSITORY_ROOT / "azext_iot/tests" / helper
    monkeypatch.chdir(tmp_path)
    namespace = runpy.run_path(str(script))
    assert Path(namespace["MANIFEST"]["__file__"]) == REPOSITORY_ROOT / "azext_iot/tests/dps/_phase_manifest.py"
    if helper == "_dps_phase_runner.py":
        assert namespace["ROOT"] == REPOSITORY_ROOT
    # Help exits before credentials/ARM/children; isolated stdlib-only execution cannot import Azure CLI.
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(script), "--help"], cwd=tmp_path,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert option in result.stdout
    assert not list(tmp_path.iterdir())


def test_ci_helpers_remain_excluded_from_extension_packages(monkeypatch, mocker):
    setup = mocker.patch("setuptools.setup")
    monkeypatch.chdir(REPOSITORY_ROOT)
    runpy.run_path(str(REPOSITORY_ROOT / "setup.py"))
    packages = setup.call_args.kwargs["packages"]
    assert "azext_iot" in packages
    assert not any(package == "azext_iot.tests" or package.startswith("azext_iot.tests.") for package in packages)
    assert set(setup.call_args.kwargs["package_data"]) == {"azext_iot"}
    assert not any("tests" in pattern for pattern in setup.call_args.kwargs["package_data"]["azext_iot"])


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
    script = str(REPOSITORY_ROOT / "azext_iot/tests/_evaluate_test_results.py")
    monkeypatch.setattr("sys.argv", [script, "--results-dir", str(results)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(script, run_name="__main__")
    assert error.value.code == exit_code
    assert ("### Passed" in summary.read_text(encoding="utf-8")) == (exit_code == 0)


def test_workflow_failure_propagation_is_wired():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert not jobs["int-test"].get("continue-on-error", False)
    bundle = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test_bundle.yml").read_text(encoding="utf-8"))
    assert bundle["jobs"]["cohort"]["strategy"]["fail-fast"] is False
    assert _integration_service_job()["strategy"]["fail-fast"] is False
    assert not _integration_service_job().get("continue-on-error", False)
    gate = jobs["int-test-gate"]
    assert set(gate["needs"]) == {"setup", "unit-test", "int-test"}
    assert not any(step.get("continue-on-error", False) for step in gate["steps"])
    evaluation = next(step for step in gate["steps"] if step["name"] == "Evaluate per-service results")
    assert "azext_iot/tests/_evaluate_test_results.py" in evaluation["run"]
    assert "needs.int-test.result" in evaluation["env"]["INTEGRATION_RESULT"]
    assert "needs.setup.outputs.matrix" in evaluation["env"]["INTEGRATION_MATRIX"]
    assert "job.status" in evaluation["env"]["GATE_JOB_RESULT"]
    summaries = [step for step in jobs["combine-coverage"]["steps"] if step["name"] == "Write job summary"]
    assert summaries[0] is jobs["combine-coverage"]["steps"][-1]
    assert "job.status" in summaries[0]["env"]["COVERAGE_RESULT"]


def test_heavy_job_budgets_accommodate_known_resource_lifecycles():
    from azext_iot.tests._hub_phase_runner import BUDGETS, CLEANUP, RESERVE
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    matrix = next(step for step in jobs["setup"]["steps"] if step.get("id") == "matrix")
    budgets = dict(re.findall(r'"(HubControl|HubData|ADR)\|[^"]+\|(\d+)"', matrix["run"]))
    assert budgets == {"HubControl": "225", "HubData": "360", "ADR": "120"}
    ado = yaml.safe_load((REPOSITORY_ROOT / ".azure-devops/templates/trigger-tests.yml").read_text(encoding="utf-8"))
    ado_budgets = {job["job"]: job["timeoutInMinutes"] for job in ado["jobs"] if job.get("job") in BUDGETS}
    assert ado_budgets == {"HubControl": 225, "HubData": 360}
    for suite, phases in BUDGETS.items():
        assert int(budgets[suite]) == (sum(runtime + CLEANUP for _, runtime in phases) + RESERVE) / 60 + 15
    assert _integration_service_job()["timeout-minutes"] == "${{ matrix.config.timeout }}"


def test_dps_workflow_runs_three_serial_complete_phases_with_existing_redaction_and_gate():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    matrix = next(step for step in jobs["setup"]["steps"] if step.get("id") == "matrix")
    assert '"DPS|azext_iot/tests/dps|DPS-int|120"' in matrix["run"]
    steps = _integration_service_job()["steps"]
    setup = next(step for step in steps if step["name"] == "Setup tox test environment")
    assert "tox r -vv -e DPS-phases,DPS-int --notest" in setup["run"]
    step = next(step for step in steps if step.get("id") == "run_tests")
    assert ".tox/DPS-phases/bin/python azext_iot/tests/_dps_phase_runner.py" in step["run"]
    assert ".tox/DPS-int/bin/python azext_iot/tests/_dps_phase_runner.py" not in step["run"]
    assert "certificate coverage is not configured in this workflow" in step["run"]
    assert "serial local-auth-toggle" in step["run"]
    assert '--subscription "$TEST_SUBSCRIPTION_ID"' in step["run"]
    assert "set -o pipefail" in step["run"] and "run_service 2>&1 |" in step["run"]
    assert "SharedAccessKey=" in step["run"] and "tee test-output.log" in step["run"]
    assert 'tox r -e "$TEST_TOX_ENV" --skip-pkg-install' in step["run"]
    upload = next(step for step in steps if step["name"] == "Upload test result")
    assert upload["with"]["path"] == "test-result/"


def _integration_service_job():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test_cohort.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["service"]


def _integration_run_step():
    return next(step for step in _integration_service_job()["steps"] if step.get("id") == "run_tests")


def test_adr_revocation_workflow_opt_in_is_typed_default_off_and_adr_only():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    for trigger in ("workflow_call", "workflow_dispatch"):
        setting = triggers[trigger]["inputs"]["adr-revoke-certificates"]
        assert setting["type"] == "boolean"
        assert setting["required"] is False and setting["default"] is False
        assert "newly created, test-owned ADR CAs" in setting["description"]
    assert len(triggers["workflow_dispatch"]["inputs"]) <= 25
    assert _integration_run_step()["env"]["azext_iot_adr_revoke_certificates"] == (
        "${{ matrix.config.service == 'ADR' && inputs['adr-revoke-certificates'] == true && 'true' || 'false' }}"
    )
    assert "azext_iot_adr_revoke_certificates" not in workflow.get("env", {})
    assert "adr-revoke-certificates" not in _integration_run_step()["run"]


def test_adr_workflow_filter_is_optional_and_bound_only_through_environment():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    for trigger in ("workflow_call", "workflow_dispatch"):
        setting = triggers[trigger]["inputs"]["adr-test-filter"]
        assert setting["type"] == "string"
        assert setting["required"] is False
        assert setting["default"] == ""
        assert "ADR-only" in setting["description"]
    # Existing service defaults must not change when the filter is introduced.
    assert triggers["workflow_call"]["inputs"]["test-services"]["default"] == "auto"
    for service in ("DPS", "HubControl", "HubData", "ADU", "ADR"):
        assert triggers["workflow_dispatch"]["inputs"][f"test{service}"]["default"] is True
    assert "testHubSAS" not in triggers["workflow_dispatch"]["inputs"]
    step = _integration_run_step()
    assert step["env"]["ADR_TEST_FILTER"] == "${{ inputs['adr-test-filter'] }}"
    assert "adr-test-filter" not in step["run"]
    assert '-k "(_int.py) and (${ADR_TEST_FILTER})"' in step["run"]
    assert 'Expression.compile(os.environ["ADR_TEST_FILTER"])' in step["run"]
    assert not step.get("continue-on-error", False)
    assert "|| true" not in step["run"]


def _run_integration_shell(tmp_path, service, expression, exit_code=0):
    script = _integration_run_step()["run"]
    # Execute the actual shell/pipeline, but never tox, the DPS controller, or file-output tee.
    script = script.replace(".tox/DPS-phases/bin/python", "dps_controller")
    script = script.replace(".tox/ADR-int/bin/python", '"$OFFLINE_PYTHON"')
    stubs = """
tox() { printf '%s\\n' tox "$@"; return "$OFFLINE_EXIT_CODE"; }
dps_controller() { printf '%s\\n' dps_controller "$@"; return "$OFFLINE_EXIT_CODE"; }
tee() { cat; }
"""
    return subprocess.run(
        ["bash", "-c", stubs + script], cwd=tmp_path,
        env=dict(os.environ, ADR_TEST_FILTER=expression, OFFLINE_PYTHON=sys.executable,
                 TEST_SERVICE=service, TEST_TOX_ENV=f"{service}-int", TEST_REGION="centraluseuap",
                 TEST_SUBSCRIPTION_ID="offline-subscription", RESOURCE_GROUP="offline-rg",
                 OFFLINE_EXIT_CODE=str(exit_code)),
        capture_output=True, text=True, timeout=20, check=False,
    )


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"), reason="Executes the Ubuntu workflow's Bash.")
@pytest.mark.parametrize("service", ["ADR", "DPS", "HubControl", "HubData", "ADU"])
@pytest.mark.parametrize("expression", ["", "test_adr_job_lifecycle or test_adr_job_validation_negatives"])
def test_adr_workflow_filter_changes_only_nonempty_adr_posargs(tmp_path, service, expression):
    result = _run_integration_shell(tmp_path, service, expression)
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = result.stdout.splitlines()
    if service == "DPS":
        assert arguments[1:] == [
            "dps_controller", "azext_iot/tests/_dps_phase_runner.py",
            "--subscription", "offline-subscription", "--resource-group", "offline-rg",
            "--region", "centraluseuap",
        ]
    else:
        expected = ["tox", "r", "-e", f"{service}-int", "--skip-pkg-install"]
        if service == "ADR" and expression:
            expected += ["--", "-k", f"(_int.py) and ({expression})"]
        assert arguments == expected


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"), reason="Executes the Ubuntu workflow's Bash.")
@pytest.mark.parametrize("expression", ["and", "test_job) or _unit.py or (test_job", '$(printf UNEXPECTED); "quoted"'])
def test_adr_workflow_rejects_invalid_or_shell_input_without_running_tox(tmp_path, expression):
    result = _run_integration_shell(tmp_path, "ADR", expression)
    assert result.returncode != 0
    assert "tox\n" not in result.stdout
    assert "\nUNEXPECTED\n" not in result.stdout


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"), reason="Executes the Ubuntu workflow's Bash.")
@pytest.mark.parametrize("exit_code", [1, 4, 5])
def test_adr_workflow_preserves_failure_usage_and_no_selection_exit_codes(tmp_path, exit_code):
    result = _run_integration_shell(tmp_path, "ADR", "test_job", exit_code)
    assert result.returncode == exit_code


@pytest.mark.parametrize("expression,exit_code", [
    ("test_job", 0),
    ("test_job or _unit.py", 0),
    ("does_not_match_any_test", 5),
    ("and", 4),
])
def test_adr_filter_overrides_tox_keyword_without_selecting_unit_tests(tmp_path, expression, exit_code):
    # Isolated, portable pytest collection: no repository conftest, credentials or live fixtures.
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    for suffix in ("int", "unit"):
        (tmp_path / f"test_example_{suffix}.py").write_text("def test_job(): pass\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(config), "--collect-only", "-q",
         "-p", "no:cacheprovider", "-k", "_int.py", str(tmp_path),
         "-k", f"(_int.py) and ({expression})"],
        cwd=tmp_path, env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS=""),
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    if exit_code == 0:
        assert [line for line in result.stdout.splitlines() if "::" in line] == ["test_example_int.py::test_job"]


@pytest.mark.parametrize("filtered", [False, True], ids=["full-adr", "five-ca-job-cases"])
def test_adr_workflow_filter_collects_existing_cases_offline(tmp_path, monkeypatch, filtered):
    expected = {
        "test_adr_certificate_authority_int.py::TestADRCertificateAuthorityLifecycle"
        "::test_adr_certificate_authority_lifecycle",
        "test_adr_job_int.py::TestADRJobLifecycle::test_adr_job_lifecycle",
        "test_adr_job_int.py::TestADRJobLifecycle::test_adr_onboarding_update_job_lifecycle",
        "test_adr_job_int.py::TestADRJobValidation::test_adr_job_validation_negatives",
        "test_adr_job_run_int.py::TestADRJobRunSurface::test_adr_job_run_surface_smoke",
    }
    expression = " or ".join(sorted(node.rsplit("::", 1)[1] for node in expected))
    dependency_path = tmp_path / "parent-only-imports"
    dependency_path.mkdir()
    (dependency_path / "workflow_parent_dependency.py").write_text("AVAILABLE = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(dependency_path))
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    script = """
import socket
import sys
from pathlib import Path
import workflow_parent_dependency
assert workflow_parent_dependency.AVAILABLE
def deny_network(*args, **kwargs):
    raise AssertionError("Workflow collection must not connect to any service")
socket.socket.connect = deny_network
import pytest
repository = Path.cwd().resolve()
class RepositoryOnlyCollection:
    @pytest.hookimpl(tryfirst=True)
    def pytest_collect_directory(self, path, parent):
        assert path.resolve().is_relative_to(repository), f"Collection escaped repository: {path}"
sys.exit(pytest.main(sys.argv[1:], plugins=[RepositoryOnlyCollection()]))
"""
    command = [
        sys.executable, "-B", "-c", script, "-c", str(config), "--rootdir", str(REPOSITORY_ROOT),
        "--confcutdir", str(REPOSITORY_ROOT),
        "--collect-only", "-q", "-p", "no:cacheprovider", "-k", "_int.py",
        str(REPOSITORY_ROOT / "azext_iot/tests/adr"),
    ]
    if filtered:
        command += ["-k", f"(_int.py) and ({expression})"]
    # Azure CLI also adds extension dependency paths at runtime.
    import_paths = dict.fromkeys([str(REPOSITORY_ROOT), *(os.path.abspath(path) for path in sys.path)])
    result = subprocess.run(
        command, cwd=REPOSITORY_ROOT,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(import_paths),
                 AZURE_TEST_RUN_LIVE="False", AZURE_CONFIG_DIR=str(tmp_path / "cli"),
                 AZURE_CORE_COLLECT_TELEMETRY="0", AZURE_CORE_CHECK_VERSION="no",
                 AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no", azext_iot_testrg="offline-workflow-rg",
                 PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS=""),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nodes = {
        line.removeprefix("azext_iot/tests/adr/") for line in result.stdout.splitlines()
        if line.startswith("azext_iot/tests/adr/") and "::" in line
    }
    if filtered:
        assert nodes == expected
    else:
        assert len(nodes) == 30
        assert expected <= nodes
        assert {
            "test_adr_certificate_authority_int.py::TestADRCAActions::" + name
            for name in ("test_external_activation_recipe", "test_external_activation_no_wait",
                         "test_microsoft_revocation", "test_microsoft_revocation_no_wait")
        } <= nodes
        assert all(node.partition("::")[0].endswith("_int.py") for node in nodes)


def test_hub_workflow_uses_two_public_suites_and_one_scoped_bundle():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["testHubControl"]["default"] is True
    assert inputs["testHubData"]["default"] is True
    assert not {"testHubMgmt", "testHubSAS"}.intersection(inputs)
    step = next(value for value in workflow["jobs"]["setup"]["steps"] if value.get("id") == "matrix")
    assert step["env"]["INPUT_TEST_HUB_CONTROL"] == "${{ inputs.testHubControl }}"
    job = workflow["jobs"]["int-test"]
    assert "strategy" not in job
    assert job["uses"] == "./.github/workflows/int_test_bundle.yml"
    assert job["concurrency"]["cancel-in-progress"] is False
    assert job["concurrency"]["group"] == "integration-live-${{ needs.setup.outputs.live-scope }}"
    service = _integration_service_job()
    assert "concurrency" not in service
    assert "max-parallel" not in service["strategy"]
    assert '"${TEST_SUBSCRIPTION_ID,,}" "${RESOURCE_GROUP,,}" | sha256sum' in step["run"]
    env = _integration_run_step()["env"]
    assert env["azext_iot_testhub_location"] == "${{ matrix.config.region }}"
    assert env["azext_iot_hub_subscription"] == "${{ env.TEST_SUBSCRIPTION_ID }}"
    assert not any(key.startswith("azext_iot_hubsas_") for key in env)


@pytest.mark.skipif(sys.platform != "linux", reason="Executes the Ubuntu workflow's Bash matrix script.")
@pytest.mark.parametrize("services,toggle,expected", [
    ("auto", "false", {"DPS", "HubControl", "HubData", "ADU", "ADR"}),
    ("auto", "true", {"DPS", "HubControl", "HubData", "ADU", "ADR"}),
    ("HubData", "false", {"HubData"}), ("", "true", {"HubData"}),
    ("HubControl", "false", {"HubControl"}),
])
def test_hub_public_matrix_auto_includes_complete_data_suite(services, toggle, expected, tmp_path):
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    step = next(value for value in workflow["jobs"]["setup"]["steps"] if value.get("id") == "matrix")
    output = tmp_path / "output"
    env = dict(os.environ, INPUT_SERVICES=services, INPUT_TEST_HUB_DATA=toggle,
               INPUT_TEST_DPS="false", INPUT_TEST_HUB_CONTROL="false",
               INPUT_TEST_ADU="false", INPUT_TEST_ADR="false", INPUT_PYTHON_VERSIONS="3.13",
               TEST_SUBSCRIPTION_ID="a386d5ea-ea90-441a-8263-d816368c84a1", RESOURCE_GROUP="cli-int-test-rg",
               INPUT_REGIONS="centraluseuap", GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=REPOSITORY_ROOT, env=env,
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    matrix = json.loads(output.read_text(encoding="utf-8").split("matrix=", 1)[1].splitlines()[0])
    assert {value["service"] for value in matrix} == expected
    for value in matrix:
        assert value["tox_env"] == value["service"] + "-int"
        assert value["region"] == "centraluseuap"


@pytest.mark.parametrize("service", ["HubControl", "HubData"])
@pytest.mark.parametrize("status", ["success", "failure", "cancelled"])
def test_hub_requires_phase_evidence_even_when_job_is_green(tmp_path, service, status):
    combination = dict(MATRIX[0], service=service)
    _result(tmp_path, combination, status=status)
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    assert errors
    assert any("Hub phase evidence" in error for error in errors)


def test_hub_data_manifest_preserves_exact_six_sas_nodes_and_normal_auth_default():
    from azext_iot.tests.iothub._sas_phase import NODES
    from azext_iot.tests._hub_suite_manifest import nodes, phases
    content = (REPOSITORY_ROOT / "tox.ini").read_text(encoding="utf-8")
    assert tuple(nodes("HubData", "sas")) == NODES
    assert phases("HubData") == ("entra", "sas")
    assert len(nodes("HubData", "entra")) == 42
    assert len(nodes("HubControl", "regular")) == 28
    assert "AZURE_DEFAULTS_IOTHUB-DATA-AUTH-TYPE=login" in content


@pytest.mark.parametrize("service", ["HubControl", "HubData"])
@pytest.mark.parametrize("passed", [False, True])
def test_hub_gate_delegates_to_checkout_controller(tmp_path, mocker, service, passed):
    combination = dict(MATRIX[0], service=service)
    _result(tmp_path, combination)
    folder = tmp_path / "hub-phases"
    folder.mkdir()
    (folder / "hub-phases.json").write_text(json.dumps({"suite": service}), encoding="utf-8")
    evaluate = mocker.Mock(return_value={"passed": passed, "errors": [] if passed else ["incomplete cleanup"]})
    load = mocker.patch("runpy.run_path", return_value={"evaluate_hub_phases": evaluate})
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    load.assert_called_once_with(str(REPOSITORY_ROOT / "azext_iot/tests/_hub_phase_runner.py"))
    evaluate.assert_called_once_with(folder)
    assert bool(errors) is not passed


def test_hub_control_evidence_cannot_qualify_hub_data(tmp_path):
    combination = dict(MATRIX[0], service="HubData")
    _result(tmp_path, combination)
    folder = tmp_path / "hub-phases"
    folder.mkdir()
    (folder / "hub-phases.json").write_text('{"suite":"HubControl"}', encoding="utf-8")
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    assert any("suite does not match" in error for error in errors)


@pytest.mark.skipif(sys.platform != "linux", reason="Executes the Ubuntu workflow's Bash matrix script.")
@pytest.mark.parametrize("override", [
    {"INPUT_SERVICES": "HubSAS"}, {"INPUT_SERVICES": "HubMgmt"},
    {"INPUT_REGIONS": "westus"}, {"INPUT_REGIONS": "centraluseuap,westus"},
    {"TEST_SUBSCRIPTION_ID": "foreign"}, {"RESOURCE_GROUP": "foreign"},
])
def test_hub_matrix_rejects_retired_suites_and_scope_mismatch_before_login(tmp_path, override):
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    step = next(value for value in workflow["jobs"]["setup"]["steps"] if value.get("id") == "matrix")
    output = tmp_path / "output"
    env = dict(os.environ, INPUT_SERVICES="HubData", INPUT_PYTHON_VERSIONS="3.13",
               INPUT_REGIONS="centraluseuap", RESOURCE_GROUP="cli-int-test-rg",
               TEST_SUBSCRIPTION_ID="a386d5ea-ea90-441a-8263-d816368c84a1",
               GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(tmp_path / "summary"))
    env.update(override)
    result = subprocess.run(["bash", "-c", step["run"]], cwd=REPOSITORY_ROOT, env=env,
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert not output.exists()


def test_hub_release_and_schedule_callers_use_owned_canary_scope():
    release = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/release_workflow.yml").read_text(encoding="utf-8"))
    inputs = release["jobs"]["int_test"]["with"]
    assert inputs["test-services"] == "auto"
    assert inputs["regions"] == "centraluseuap"
    assert inputs["resource-group"] == "cli-int-test-rg"
    assert inputs["subscription-id"] == "a386d5ea-ea90-441a-8263-d816368c84a1"
    scheduler = (REPOSITORY_ROOT / ".github/workflows/int_test_schedule.yml").read_text(encoding="utf-8")
    assert 'region="centraluseuap"' in scheduler
    assert "-f subscription-id=a386d5ea-ea90-441a-8263-d816368c84a1" in scheduler
    assert "-f resource-group=cli-int-test-rg" in scheduler
    assert "region_list=" not in scheduler


def test_hub_workflow_gate_loads_real_phase_evaluator_without_installed_dependencies(tmp_path):
    combination = dict(MATRIX[0], service="HubData")
    _result(tmp_path, combination)
    folder = tmp_path / "hub-phases"
    folder.mkdir()
    (folder / "hub-phases.json").write_text('{"suite":"HubData"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(REPOSITORY_ROOT / "azext_iot/tests/_evaluate_test_results.py"),
         "--results-dir", str(tmp_path)], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
        env=dict(os.environ, INTEGRATION_MATRIX=json.dumps([combination]), SETUP_RESULT="success",
                 UNIT_TEST_RESULT="success", INTEGRATION_RESULT="success", GATE_JOB_RESULT="success"),
    )
    assert result.returncode == 1
    assert "Hub phase evidence is incomplete or unsuccessful" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
