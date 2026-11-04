# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import json
import runpy
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


def _ci_budgets():
    return json.loads((REPOSITORY_ROOT / "azext_iot/tests/ci_budgets.json").read_text(encoding="utf-8"))


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
def test_native_openssl_selection_explains_missing_homebrew(tmp_path):
    bash = shutil.which("bash")
    assert bash
    result = subprocess.run(
        [bash, str(REPOSITORY_ROOT / "scripts/select-openssl.sh")],
        env=dict(os.environ, PATH=str(tmp_path)), capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 1
    assert "requires Homebrew on macOS with openssl@3 installed" in result.stderr
    assert not result.stdout


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


@pytest.mark.parametrize("endpoint", [None, "https://centraluseuap.management.azure.com", "https://management.azure.com"])
def test_matrix_endpoint_receipt_must_match_scheduled_target(tmp_path, endpoint):
    combination = dict(MATRIX[0], region="australiaeast", arm_endpoint="https://management.azure.com")
    _result(tmp_path, combination)
    if endpoint:
        (tmp_path / "arm-endpoint.txt").write_text(endpoint, encoding="utf-8")
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    assert bool(errors) == (endpoint != combination["arm_endpoint"])


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


def test_ado_style_check_installs_cli_in_selected_python():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".azure-devops/merge.yml").read_text(encoding="utf-8"))
    steps = next(job for job in workflow["jobs"] if job["job"] == "run_style_check")["steps"]
    templates = [step.get("template") for step in steps]
    setup = templates.index("templates/setup-python.yml")
    cli = templates.index("templates/install-azure-cli-released.yml")
    extension = templates.index("templates/download-install-local-azure-iot-cli-extension-with-pip.yml")
    pylint = next(index for index, step in enumerate(steps) if step.get("script", "").startswith("pylint "))
    assert setup < cli < extension < pylint
    install = yaml.safe_load(
        (REPOSITORY_ROOT / ".azure-devops/templates/install-azure-cli-released.yml").read_text(encoding="utf-8")
    )
    assert install["steps"][0]["script"] == "python -m pip install azure-cli"


def test_heavy_job_budgets_accommodate_known_resource_lifecycles():
    from azext_iot.tests._hub_phase_runner import BUDGETS, runner_seconds

    budgets = _ci_budgets()
    ado = yaml.safe_load((REPOSITORY_ROOT / ".azure-devops/templates/trigger-tests.yml").read_text(encoding="utf-8"))
    ado_budgets = {job["job"]: job["timeoutInMinutes"] for job in ado["jobs"] if job.get("job") in BUDGETS}
    assert ado_budgets == {suite: budgets[suite]["job_timeout_minutes"] for suite in BUDGETS}
    for suite, phases in BUDGETS.items():
        assert budgets[suite].get("concurrent_phases") is True
        # Concurrent phases are bounded by the slowest phase, plus controller reserve.
        assert runner_seconds(suite, phases) == 60 * (max(
            phase["runtime_minutes"] + phase["cleanup_minutes"] for phase in budgets[suite]["phases"]
        ) + budgets[suite]["reserve_minutes"])
        assert runner_seconds(suite, phases) / 60 + budgets[suite]["setup_minutes"] <= (
            budgets[suite]["job_timeout_minutes"]
        )


def test_adr_budget_accommodates_owned_lifecycles():
    from azext_iot.tests.adr._helpers import SU_LIFECYCLE_TIMEOUT
    from azext_iot.tests.adr.test_adr_link_int import _SU_LINK_LIFECYCLE_TIMEOUT

    budget = _ci_budgets()["ADR"]["job_timeout_minutes"]
    assert budget == 180
    assert SU_LIFECYCLE_TIMEOUT == 75 * 60
    assert _SU_LINK_LIFECYCLE_TIMEOUT == 115 * 60
    # Scenario ceilings are not serial runtime estimates for the loadgroup workers.
    assert budget * 60 > max(_SU_LINK_LIFECYCLE_TIMEOUT, SU_LIFECYCLE_TIMEOUT)


@pytest.mark.parametrize("expression,exit_code", [
    ("test_job", 0),
    ("test_job or _unit.py", 0),
    ("does_not_match_any_test", 5),
    ("and", 4),
])
def test_local_adr_filter_overrides_tox_keyword_without_selecting_unit_tests(tmp_path, expression, exit_code):
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
def test_full_adr_and_local_debug_collect_existing_cases_offline(tmp_path, monkeypatch, filtered):
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
        assert len(nodes) == 32
        assert {
            "test_adr_registry_device_int.py::TestADRRegistryDeviceLifecycle::test_registry_device_lifecycle",
            "test_adr_link_delete_int.py::TestADRLinkDelete::test_adr_link_hub_dps_delete",
            "test_adr_link_int.py::TestADRLinkBrownfieldRecovery::test_adr_link_brownfield_recovery",
            "test_adr_link_delete_int.py::TestADRLinkDelete::test_adr_link_su_delete",
            "test_adr_link_delete_int.py::TestADRLinkDelete::test_adr_unlink_missing_rg_advisory",
            "test_adr_schema_int.py::TestADRSemanticModelLifecycle::"
            "test_schema_registry_models_and_device_reference_lifecycle",
        } <= nodes
        assert expected <= nodes
        assert {
            "test_adr_certificate_authority_int.py::TestADRCAActions::" + name
            for name in ("test_external_activation_recipe", "test_external_activation_no_wait",
                         "test_microsoft_revocation", "test_microsoft_revocation_no_wait")
        } <= nodes
        assert all(node.partition("::")[0].endswith("_int.py") for node in nodes)


@pytest.mark.parametrize("service", ["HubControl", "HubData"])
@pytest.mark.parametrize("status", ["success", "failure", "cancelled"])
def test_hub_requires_phase_evidence_even_when_job_is_green(tmp_path, service, status):
    combination = dict(MATRIX[0], service=service)
    _result(tmp_path, combination, status=status)
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    assert errors
    assert any("Hub phase evidence" in error for error in errors)


def test_hub_data_manifest_preserves_exact_sas_nodes_and_normal_auth_default():
    from azext_iot.tests.iothub._sas_phase import NODES
    from azext_iot.tests._hub_suite_manifest import nodes, phases
    content = (REPOSITORY_ROOT / "tox.ini").read_text(encoding="utf-8")
    assert tuple(nodes("HubData", "sas")) == NODES
    assert phases("HubData") == ("entra-state-config", "entra-devices-protocol", "entra-identities", "sas")
    assert sum(len(nodes("HubData", phase)) for phase in phases("HubData") if phase.startswith("entra-")) == 44
    assert sum(len(nodes("HubControl", phase)) for phase in phases("HubControl")) == 36
    assert "AZURE_DEFAULTS_IOTHUB-DATA-AUTH-TYPE=login" in content


@pytest.mark.parametrize("service", ["HubControl", "HubData"])
@pytest.mark.parametrize("passed", [False, True])
@pytest.mark.parametrize("endpoint", [None, "https://management.azure.com"])
def test_hub_gate_delegates_to_checkout_controller(tmp_path, mocker, service, passed, endpoint):
    combination = dict(MATRIX[0], service=service)
    if endpoint:
        combination["arm_endpoint"] = endpoint
        (tmp_path / "arm-endpoint.txt").write_text(endpoint, encoding="utf-8")
    _result(tmp_path, combination)
    folder = tmp_path / "hub-phases"
    folder.mkdir()
    (folder / "hub-phases.json").write_text(json.dumps({"suite": service}), encoding="utf-8")
    evaluate = mocker.Mock(return_value={"passed": passed, "errors": [] if passed else ["incomplete cleanup"]})
    load = mocker.patch("runpy.run_path", return_value={"evaluate_hub_phases": evaluate})
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    load.assert_called_once_with(str(REPOSITORY_ROOT / "azext_iot/tests/_hub_phase_runner.py"))
    evaluate.assert_called_once_with(folder, region=combination["region"], endpoint=endpoint)
    assert bool(errors) is not passed


def test_hub_control_evidence_cannot_qualify_hub_data(tmp_path):
    combination = dict(MATRIX[0], service="HubData")
    _result(tmp_path, combination)
    folder = tmp_path / "hub-phases"
    folder.mkdir()
    (folder / "hub-phases.json").write_text('{"suite":"HubControl"}', encoding="utf-8")
    _, errors = EVALUATE(tmp_path, [combination], SUCCESSFUL_JOBS)
    assert any("suite does not match" in error for error in errors)


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
