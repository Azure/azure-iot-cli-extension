# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import zipfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("index_compatibility", ROOT / "scripts/check_index_compatibility.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def lint_output(severity=None, pylint="PASSED"):
    lines = ["Modules: azure-iot", f"Linter: {pylint}"]
    for rule in sorted(CHECK.REQUIRED_RULES):
        if severity and rule == "require_wait_command_if_no_wait":
            lines.extend([
                f"- \x1b[31m FAIL\x1b[39m - {severity} severity: {rule}",
                "    Command-Group: `iot hub` - No wait command",
            ])
        else:
            lines.append(f"- \x1b[32m pass\x1b[39m: {rule} ")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("severity", [None, "MEDIUM", "HIGH"])
def test_parser_handles_real_ansi_spacing_and_medium_fail_with_pylint_pass(severity):
    findings = CHECK.parse_lint(lint_output(severity))
    assert findings == ([] if severity is None else [{
        "severity": severity, "rule": "require_wait_command_if_no_wait",
        "command": "iot hub", "parameter": "", "message": "No wait command",
    }])


def test_parser_extracts_parameter_and_multiple_findings():
    text = lint_output() + (
        "- FAIL - HIGH severity: no_parameter_defaults_for_update_commands\n"
        "    Parameter: iot hub digital-twin update, `auth_type_dataplane` - Default is key\n"
        "    Parameter: iot dps enrollment update, `auth_type_dataplane` - Default is key\n"
    )
    findings = CHECK.parse_lint(text)
    assert len(findings) == 2
    assert findings[0]["command"] == "iot hub digital-twin update"
    assert findings[0]["parameter"] == "auth_type_dataplane"


@pytest.mark.parametrize("text", [
    "", "Linter: PASSED\n", "No violations found.\n",
    lint_output().replace("Modules: azure-iot", "Modules: other"),
    lint_output() + "WARNING: No commands selected to check.\n",
    lint_output().replace("Linter: PASSED", ""),
    lint_output().replace("- \x1b[32m pass\x1b[39m: missing_group_help ", ""),
    lint_output() + "- FAIL - HIGH severity: new_rule\n",
    lint_output() + "- FAIL - UNKNOWN severity: new_rule\n",
])
def test_empty_partial_or_unrecognized_results_never_pass(text):
    with pytest.raises(ValueError):
        CHECK.parse_lint(text)


def test_exclusions_use_exact_parameter_keys_and_all_effective_sources():
    local = {
        "iot hub": {"rule_exclusions": ["wait"]},
        "iot hub update": {"parameters": {"auth": {"rule_exclusions": ["default"]}}},
        "iot hub state migrate": {"parameters": {"orig": {"rule_exclusions": ["resource_group"]}}},
    }
    core = {"iot hub": local["iot hub"]}
    index = {
        "iot hub state migrate": {"parameters": {"orig": {"rule exclusions": ["resource_group"]}}},
        "iot hub update": {"parameters": {"other": {"rule_exclusions": ["default"]}}},
    }
    wheel = {"iot hub update": local["iot hub update"]}
    assert CHECK.compare_exclusions(local, [core, index, wheel]) == [{
        "command": "iot hub state migrate", "parameter": "orig", "rule": "resource_group",
    }]
    index["iot hub state migrate"] = local["iot hub state migrate"]
    assert CHECK.compare_exclusions(local, [core, index, wheel]) == []


def make_wheel(path, name="azure-iot"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("azure_iot-1.0.dist-info/METADATA", f"Name: {name}\nVersion: 1.0\n")
        archive.writestr("azext_iot/__init__.py", "# candidate\n")
        archive.writestr("azext_iot/azext_metadata.json", "{}")


def test_candidate_provenance_requires_installed_wheel_bytes(tmp_path):
    wheel, extension = tmp_path / "azure_iot-1.0-py3-none-any.whl", tmp_path / "extension"
    make_wheel(wheel)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(extension)
    provenance = CHECK.verify_wheel(wheel, extension)
    assert provenance["version"] == "1.0"
    assert len(provenance["sha256"]) == 64
    (extension / "azext_iot/__init__.py").write_text("# source checkout\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from candidate"):
        CHECK.verify_wheel(wheel, extension)


def test_foreign_wheel_is_rejected(tmp_path):
    wheel = tmp_path / "foreign.whl"
    make_wheel(wheel, name="other-extension")
    with pytest.raises(ValueError, match="not azure-iot"):
        CHECK.verify_wheel(wheel, tmp_path)


@pytest.mark.parametrize("case", ["valid", "no-module", "source-module", "no-commands", "shadowed-import"])
def test_loaded_commands_and_imports_belong_to_candidate(tmp_path, mocker, case):
    extension = tmp_path / "extensions/azure-iot"
    selected = {"mod": {}, "core": {}, "ext": {"azure-iot": str(extension)}}
    if case == "no-module":
        selected["ext"] = {}
    elif case == "source-module":
        selected["ext"]["azure-iot"] = str(tmp_path / "source")
    paths, rules = ModuleType("azdev.utilities.path"), ModuleType("azdev.operations.linter.util")
    paths.get_path_table = mocker.Mock(return_value=selected)
    loader = mocker.Mock(command_table={} if case == "no-commands" else {"iot hub show": object()})
    rules.filter_modules = mocker.Mock(return_value=(loader, {}))
    mocker.patch.dict(sys.modules, {"azdev.utilities.path": paths, "azdev.operations.linter.util": rules})
    mocker.patch("azure.cli.core.get_default_cli")
    mocker.patch("azure.cli.core.file_util.create_invoker_and_load_cmds_and_args")
    imported = ModuleType("azext_iot")
    imported.__file__ = str((tmp_path / "source" if case == "shadowed-import" else extension) / "azext_iot/__init__.py")
    mocker.patch.object(CHECK.importlib, "import_module", return_value=imported)
    if case == "valid":
        assert CHECK.verify_loaded_extension(extension)["command_count"] == 1
    else:
        with pytest.raises(ValueError):
            CHECK.verify_loaded_extension(extension)


@pytest.fixture
def candidate(tmp_path, mocker):
    work, source = tmp_path / "work", tmp_path / "source"
    source.mkdir()
    for directory in ("run", "wheels", "azure-cli", "azure-cli-extensions", "extensions/azure-iot"):
        (work / directory).mkdir(parents=True)
    wheel = work / "wheels/azure_iot-1.0-py3-none-any.whl"
    make_wheel(wheel)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(work / "extensions/azure-iot")
    (source / "linter_exclusions.yml").write_text(
        "iot hub:\n  rule_exclusions:\n  - require_wait_command_if_no_wait\n", encoding="utf-8",
    )
    for directory in ("azure-cli", "azure-cli-extensions"):
        (work / directory / "linter_exclusions.yml").write_text("{}\n", encoding="utf-8")
    mocker.patch.object(CHECK, "run", return_value="upstream-sha\n")
    mocker.patch.object(CHECK, "check_toolchain", return_value={"python": "3.14", "azdev": "0.2.13"})
    mocker.patch.object(CHECK, "verify_environment")
    mocker.patch.object(CHECK, "verify_loaded_extension", return_value={"command_count": 100})
    return work, source


@pytest.mark.parametrize("severity,returncode,expected", [
    (None, 0, 0), ("MEDIUM", 0, 0), ("HIGH", 1, 1), ("HIGH", 0, 1), (None, 7, 7),
])
def test_checker_preserves_status_and_always_reports(candidate, mocker, capsys, severity, returncode, expected):
    work, source = candidate
    runner = mocker.patch.object(
        CHECK.subprocess, "run",
        return_value=subprocess.CompletedProcess(CHECK.LINT_COMMAND, returncode, lint_output(severity)),
    )
    assert CHECK.check(work, source) == expected
    runner.assert_called_once_with(
        CHECK.LINT_COMMAND, cwd=work / "azure-cli-extensions", check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    report = json.loads((work / "reports/report.json").read_text(encoding="utf-8"))
    assert report["lint_exit_code"] == returncode
    assert report["missing_exclusions"]
    assert report["result"] == ("Failed" if expected else "Passed with MEDIUM warnings" if severity else "Passed")
    assert (work / "reports/linter.log").exists()
    assert (work / "reports/summary.md").exists()
    assert not (work / "extensions/azure-iot/linter_exclusions.yml").exists()
    output = capsys.readouterr().out
    if severity:
        assert report["findings"][0]["local_exclusion"] == "yes"
        assert ("::error::" if severity == "HIGH" else "::warning::") in output
    if not expected:
        assert "::error::" not in output


@pytest.mark.parametrize("failure", ["install", "empty", "shadowed", "toolchain", "no-wheel", "two-wheels"])
def test_tool_and_provenance_failures_are_red_with_artifacts(candidate, mocker, failure):
    work, source = candidate
    mocker.patch.object(CHECK.subprocess, "run",
                        return_value=subprocess.CompletedProcess(CHECK.LINT_COMMAND, 0, "Linter: PASSED\n"))
    if failure == "install":
        CHECK.run.side_effect = ["source", "cli", "index", subprocess.CalledProcessError(9, ["az"], output="install failed")]
    elif failure == "shadowed":
        CHECK.verify_loaded_extension.side_effect = ValueError("IoT imports are shadowed")
    elif failure == "toolchain":
        CHECK.check_toolchain.side_effect = ValueError("Toolchain drift")
    elif failure == "no-wheel":
        next((work / "wheels").glob("*.whl")).unlink()
    elif failure == "two-wheels":
        make_wheel(work / "wheels/second.whl")
    assert CHECK.check(work, source) != 0
    report = json.loads((work / "reports/report.json").read_text(encoding="utf-8"))
    assert report["result"] == "Failed" and report["error"]
    assert "**Error:**" in (work / "reports/summary.md").read_text(encoding="utf-8")


def test_annotations_escape_workflow_command_characters(capsys):
    CHECK.annotate("warning", "first%\n::error::injected\r")
    assert capsys.readouterr().out == "::warning::first%25%0A::error::injected%0D\n"


@pytest.mark.parametrize("bad", ["pythonpath", "user-site", "system-site", "source-cwd", "config", "dev-sources"])
def test_environment_isolation_rejects_source_and_config_leaks(tmp_path, monkeypatch, bad):
    work, source = tmp_path / "work", tmp_path / "source"
    (work / "venv").mkdir(parents=True)
    source.mkdir()
    (work / "venv/pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(work / "venv"))
    monkeypatch.setattr(CHECK.site, "ENABLE_USER_SITE", False)
    monkeypatch.setenv("PYTHONPATH", "")
    for key, directory in [
        ("AZURE_CONFIG_DIR", "azure-config"), ("AZDEV_CONFIG_DIR", "azdev-config"),
        ("AZURE_EXTENSION_DIR", "extensions"), ("AZURE_EXTENSION_DEV_SOURCES", "azure-cli-extensions"),
    ]:
        monkeypatch.setenv(key, str(work / directory))
    monkeypatch.chdir(work)
    if bad == "pythonpath":
        monkeypatch.setenv("PYTHONPATH", str(source))
    elif bad == "user-site":
        monkeypatch.setattr(CHECK.site, "ENABLE_USER_SITE", True)
    elif bad == "system-site":
        (work / "venv/pyvenv.cfg").write_text("include-system-site-packages = true\n", encoding="utf-8")
    elif bad == "source-cwd":
        monkeypatch.chdir(source)
    elif bad == "config":
        monkeypatch.setenv("AZDEV_CONFIG_DIR", str(source))
    else:
        monkeypatch.setenv("AZURE_EXTENSION_DEV_SOURCES", str(source))
    with pytest.raises(ValueError):
        CHECK.verify_environment(work, source)


def test_toolchain_drift_is_explicit(tmp_path, mocker):
    (tmp_path / ".azure-pipelines/templates").mkdir(parents=True)
    (tmp_path / "azure-pipelines.yml").write_text(yaml.safe_dump({"jobs": [{
        "job": "AzdevLinterModifiedExtensions",
        "steps": [{"task": "UsePythonVersion@0", "inputs": {"versionSpec": "99.0"}}],
    }]}), encoding="utf-8")
    (tmp_path / ".azure-pipelines/templates/azdev_setup.yml").write_text(
        "pip install azdev==0.2.13\ngit clone -b dev https://github.com/Azure/azure-cli.git\n", encoding="utf-8",
    )
    mocker.patch.object(CHECK.importlib.metadata, "version", return_value="0.2.13")
    with pytest.raises(ValueError, match="Toolchain drift.*99.0"):
        CHECK.check_toolchain(tmp_path)


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def test_both_callers_reuse_wheel_without_gating_existing_checks_or_release():
    ci, release = workflow("ci_workflow.yml")["jobs"], workflow("release_workflow.yml")["jobs"]
    for jobs in (ci, release):
        job = jobs["index-compatibility"]
        assert job["needs"] == ["build"]
        assert job["uses"] == "./.github/workflows/index_compatibility.yml"
        assert "secrets" not in job and "continue-on-error" not in job
        assert all("index-compatibility" not in other.get("needs", []) for other in jobs.values())
    assert ci["linter"] == {"needs": ["build"], "uses": "./.github/workflows/azdev_linter.yml"}
    assert release["approval"]["needs"] == ["security", "build", "unit-test", "azdev_linter", "int_test"]
    assert release["approval"]["environment"] == "production"
    assert release["draft_github_release"]["needs"] == ["approval"]


def test_reusable_workflow_is_isolated_read_only_and_does_not_mask_failures():
    config = workflow("index_compatibility.yml")
    assert set(config.get("on", config.get(True))) == {"workflow_call"}
    job = config["jobs"]["index-compatibility"]
    assert job["permissions"] == {"contents": "read"}
    assert "continue-on-error" not in job
    assert job["env"]["PYTHONPATH"] == ""
    assert job["env"]["PYTHONNOUSERSITE"] == "1"
    assert all("continue-on-error" not in step for step in job["steps"])
    assert all("azure/login" not in step.get("uses", "") for step in job["steps"])
    download = next(step for step in job["steps"] if "actions/download-artifact@" in step.get("uses", ""))
    assert download["with"]["name"] == "azure-iot-cli-ext"
    upload = next(step for step in job["steps"] if "actions/upload-artifact@" in step.get("uses", ""))
    assert upload["if"] == "always()" and upload["with"]["if-no-files-found"] == "error"
    setup = next(step for step in job["steps"] if step.get("name") == "Check candidate against index CI")
    assert "set -euo pipefail" in setup["run"]
    assert 'cd "$COMPAT_ROOT/run"' in setup["run"]
    assert '-r "$COMPAT_ROOT/azure-cli-extensions"' in setup["run"]
    assert "azdev==0.2.13" in setup["run"]
    assert not any(text in setup["run"] for text in ("|| true", "--system-site-packages", "cp ./linter_exclusions"))


@pytest.mark.skipif(sys.platform != "linux", reason="Runs the Linux workflow shell.")
def test_isolated_paths_are_set_before_checkout_and_download(tmp_path):
    steps = workflow("index_compatibility.yml")["jobs"]["index-compatibility"]["steps"]
    assert steps[0]["name"] == "Initialize isolated paths"
    env_file = tmp_path / "github-env"
    subprocess.run(
        ["bash", "-c", steps[0]["run"]],
        env=dict(os.environ, RUNNER_TEMP=str(tmp_path), GITHUB_ENV=str(env_file)), check=True,
    )
    values = dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines())
    root = tmp_path / "index-compatibility"
    assert values == {
        "COMPAT_ROOT": str(root),
        "AZURE_CONFIG_DIR": str(root / "azure-config"),
        "AZDEV_CONFIG_DIR": str(root / "azdev-config"),
        "AZURE_EXTENSION_DIR": str(root / "extensions"),
        "AZURE_EXTENSION_DEV_SOURCES": str(root / "azure-cli-extensions"),
    }


@pytest.mark.skipif(sys.platform != "linux", reason="Runs the Linux workflow shell.")
def test_setup_failure_survives_tee(tmp_path):
    script = next(step["run"] for step in workflow("index_compatibility.yml")["jobs"]["index-compatibility"]["steps"]
                  if step.get("name") == "Check candidate against index CI")
    result = subprocess.run(
        ["bash", "-c", "python() { echo 'setup failed'; return 17; }\n" + script],
        env=dict(os.environ, COMPAT_ROOT=str(tmp_path)), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 17
    assert "setup failed" in (tmp_path / "reports/setup.log").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "linux", reason="Runs the Linux workflow shell.")
def test_summary_step_reports_setup_failure_without_success_fallback(tmp_path):
    script = next(step["run"] for step in workflow("index_compatibility.yml")["jobs"]["index-compatibility"]["steps"]
                  if step.get("name") == "Publish compatibility summary")
    result = subprocess.run(
        ["bash", "-c", script],
        env=dict(os.environ, COMPAT_ROOT=str(tmp_path), GITHUB_STEP_SUMMARY=str(tmp_path / "github-summary")),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "::error::Index compatibility did not complete" in result.stdout
    assert "**Incomplete:**" in (tmp_path / "github-summary").read_text(encoding="utf-8")
