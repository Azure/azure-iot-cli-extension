# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Lint an installed candidate wheel using index CI's configuration, never source exclusions."""

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import site
import subprocess
import sys
import zipfile
from email.parser import Parser

import yaml


LINT_COMMAND = ["azdev", "linter", "--include-whl-extensions", "azure-iot", "--min-severity", "medium"]
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
RULE = re.compile(r"^-\s+(pass|FAIL)(?: - (HIGH|MEDIUM) severity)?: (\w+)\s*$")
REQUIRED_RULES = {
    "missing_group_help", "missing_command_help", "no_parameter_defaults_for_update_commands",
    "broken_site_link_from_command_group", "require_wait_command_if_no_wait",
    "parameter_should_not_end_in_resource_group",
}


def run(command, cwd):
    return subprocess.run(command, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT).stdout


def read_yaml(path):
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def flatten_exclusions(data):
    result = set()
    for command, entry in data.items():
        result.update((command, "", rule) for rule in entry.get("rule_exclusions", []))
        for parameter, settings in entry.get("parameters", {}).items():
            result.update((command, parameter, rule) for rule in settings.get("rule_exclusions", []))
    return result


def compare_exclusions(local, upstream):
    """Compare the exact command/parameter/rule keys consumed by azdev."""
    effective = set().union(*(flatten_exclusions(data) for data in upstream))
    return [
        {"command": command, "parameter": parameter, "rule": rule}
        for command, parameter, rule in sorted(flatten_exclusions(local) - effective)
    ]


def parse_lint(output):
    text = ANSI.sub("", output)
    if "No commands selected to check." in text or not re.search(r"^Modules: azure-iot\s*$", text, re.M):
        raise ValueError("The linter did not select azure-iot commands.")
    seen, findings = set(), []
    current = ("", "")
    for line in text.splitlines():
        match = RULE.fullmatch(line.strip())
        if match:
            result, severity, name = match.groups()
            seen.add(name)
            current = (severity, name) if result == "FAIL" else ("", "")
        elif line.lstrip().startswith("- FAIL"):
            raise ValueError(f"Unrecognized linter result: {line}")
        elif current[0] and line.startswith("    ") and " - " in line:
            entity, message = line.strip().split(" - ", 1)
            parameter = ""
            if entity.startswith("Parameter: "):
                command, parameter = entity[len("Parameter: "):].rsplit(", ", 1)
            else:
                command = entity.split(": ", 1)[-1]
            findings.append({
                "severity": current[0], "rule": current[1],
                "command": command.strip("`"), "parameter": parameter.strip("`"), "message": message,
            })
    if not REQUIRED_RULES.issubset(seen) or "Linter: PASSED" not in text and "Linter: FAILED" not in text:
        raise ValueError("Incomplete linter output; expected command rules and custom pylint results.")
    failures = set(re.findall(r"^- FAIL - (?:HIGH|MEDIUM) severity: (\w+)\s*$", text, re.M))
    if failures - {finding["rule"] for finding in findings}:
        raise ValueError("A failed linter rule had no readable findings.")
    return findings


def check_toolchain(index_repo):
    pipeline = read_yaml(index_repo / "azure-pipelines.yml")
    job = next(job for job in pipeline["jobs"] if job.get("job") == "AzdevLinterModifiedExtensions")
    expected_python = next(
        step["inputs"]["versionSpec"] for step in job["steps"]
        if step.get("task") == "UsePythonVersion@0"
    )
    setup = (index_repo / ".azure-pipelines/templates/azdev_setup.yml").read_text(encoding="utf-8")
    pins = re.findall(r"\bazdev==([\w.]+)", setup)
    if len(set(pins)) != 1 or "-b dev https://github.com/Azure/azure-cli.git" not in setup:
        raise ValueError("Upstream azdev/CLI setup changed; review the compatibility workflow.")
    actual = {"python": platform.python_version(), "azdev": importlib.metadata.version("azdev"),
              "azure_cli": importlib.metadata.version("azure-cli")}
    if str(expected_python) != f"{sys.version_info.major}.{sys.version_info.minor}" or actual["azdev"] != pins[0]:
        raise ValueError(
            f"Toolchain drift: index CI requires Python {expected_python}, azdev {pins[0]}; "
            f"this job uses Python {actual['python']}, azdev {actual['azdev']}. Update the compatibility workflow."
        )
    return actual


def verify_wheel(wheel, extension_path):
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Candidate wheel must contain exactly one distribution.")
        metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
        if metadata["Name"].replace("_", "-") != "azure-iot":
            raise ValueError("The candidate wheel is not azure-iot.")
        files = [name for name in archive.namelist() if name.startswith("azext_iot/") and not name.endswith("/")]
        if "azext_iot/__init__.py" not in files:
            raise ValueError("Candidate wheel does not contain the IoT extension.")
        for name in files:
            installed = (extension_path / name).resolve()
            if not installed.is_relative_to(extension_path.resolve()) or installed.read_bytes() != archive.read(name):
                raise ValueError(f"Installed extension differs from candidate wheel: {name}")
    return {"name": wheel.name, "version": metadata["Version"],
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}


def verify_environment(work_dir, source_root):
    if sys.prefix == sys.base_prefix or site.ENABLE_USER_SITE or os.environ.get("PYTHONPATH"):
        raise ValueError("Use a clean virtual environment without user packages or PYTHONPATH.")
    config = Path(sys.prefix) / "pyvenv.cfg"
    if (Path(sys.prefix).resolve() != work_dir / "venv"
            or not re.search(r"(?mi)^include-system-site-packages\s*=\s*false\s*$",
                             config.read_text(encoding="utf-8"))):
        raise ValueError("The isolated virtual environment must not include system packages.")
    if Path.cwd().resolve().is_relative_to(source_root):
        raise ValueError("Run outside the IoT source checkout.")
    for name, directory in [
        ("AZURE_CONFIG_DIR", "azure-config"), ("AZDEV_CONFIG_DIR", "azdev-config"),
        ("AZURE_EXTENSION_DIR", "extensions"), ("AZURE_EXTENSION_DEV_SOURCES", "azure-cli-extensions"),
    ]:
        if Path(os.environ.get(name, "")).resolve() != work_dir / directory:
            raise ValueError(f"{name} must point to the isolated {directory} directory.")
    from azdev.utilities.path import get_cli_repo_path, get_ext_repo_paths

    if Path(get_cli_repo_path()).resolve() != work_dir / "azure-cli":
        raise ValueError("azdev is not registered against the isolated CLI checkout.")
    if [Path(path).resolve() for path in get_ext_repo_paths()] != [work_dir / "azure-cli-extensions"]:
        raise ValueError("Only the upstream index checkout may be registered with azdev.")


def verify_loaded_extension(extension_path):
    from azdev.utilities.path import get_path_table
    from azdev.operations.linter.util import filter_modules
    from azure.cli.core import get_default_cli
    from azure.cli.core.file_util import create_invoker_and_load_cmds_and_args

    selected = get_path_table(include_only=["azure-iot"], include_whl_extensions=True)
    if (selected["mod"] or selected["core"] or set(selected["ext"]) != {"azure-iot"}
            or Path(selected["ext"]["azure-iot"]).resolve() != extension_path):
        raise ValueError(f"Unexpected linter module selection: {selected}")
    cli = get_default_cli()
    create_invoker_and_load_cmds_and_args(cli)
    loader, _ = filter_modules(cli.invocation.commands_loader, {}, modules=["azure-iot"],
                               include_whl_extensions=True)
    if not loader.command_table:
        raise ValueError("The installed wheel loaded no extension commands.")
    module = importlib.import_module("azext_iot")
    if Path(module.__file__).resolve() != extension_path / "azext_iot/__init__.py":
        raise ValueError(f"IoT imports are shadowed by {module.__file__}")
    return {"module": module.__file__, "command_count": len(loader.command_table)}


def cell(value):
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def summary(report):
    lines = ["# Index compatibility", "",
             "**Advisory:** HIGH/tool failures are red; MEDIUM-only findings are warnings. "
             "This check is not a release approval dependency.", "",
             f"**Result:** {report['result']}", ""]
    if report.get("error"):
        lines.extend([f"**Error:** {cell(report['error'])}", ""])
    lines.extend(["## Provenance", "", "| Item | Value |", "|---|---|"])
    for key, value in report["provenance"].items():
        lines.append(f"| {cell(key)} | {cell(value)} |")
    if report["findings"]:
        lines.extend(["", "## HIGH / MEDIUM findings", "",
                      "| Severity | Command/group | Parameter | Rule | Locally exempted | Detail |",
                      "|---|---|---|---|---|---|"])
        for finding in report["findings"]:
            keys = ("severity", "command", "parameter", "rule", "local_exclusion", "message")
            lines.append("| " + " | ".join(cell(finding.get(key, "")) for key in keys) + " |")
    lines.extend(["", "<details><summary>Local exclusions missing from effective index configuration "
                  f"({len(report['missing_exclusions'])})</summary>", "",
                  "Informational only: a missing exemption does not necessarily cause a lint finding. "
                  "Malformed upstream keys such as `rule exclusions` are not effective exemptions.", "",
                  "| Command/group | Parameter | Rule |", "|---|---|---|"])
    for entry in report["missing_exclusions"]:
        lines.append(f"| {cell(entry['command'])} | {cell(entry['parameter'])} | {cell(entry['rule'])} |")
    lines.extend(["", "</details>", "", "See the `index-compatibility` artifact for logs, JSON results, "
                  "and the exclusion files used. Only merged upstream configuration is used.", ""])
    return "\n".join(lines)


def annotate(level, message):
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::{escaped}")


def check(work_dir, source_root):
    reports = work_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report = {"result": "Incomplete", "error": "Checker did not complete; inspect the job log.",
              "provenance": {}, "findings": [], "missing_exclusions": []}
    exit_code = 1
    try:
        cli_repo, index_repo = work_dir / "azure-cli", work_dir / "azure-cli-extensions"
        for label, repo in [("source_commit", source_root), ("cli_commit", cli_repo), ("index_commit", index_repo)]:
            report["provenance"][label] = run(["git", "rev-parse", "HEAD"], repo).strip()
        report["provenance"].update(check_toolchain(index_repo))
        verify_environment(work_dir, source_root)
        wheels = sorted((work_dir / "wheels").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError(f"Expected one candidate wheel, found {len(wheels)}.")
        wheel = wheels[0]
        extension_path = work_dir / "extensions/azure-iot"
        install_log = run(["az", "extension", "add", "--source", str(wheel), "--yes"], work_dir / "run")
        (reports / "install.log").write_text(install_log, encoding="utf-8")
        report["provenance"].update(verify_wheel(wheel, extension_path))
        report["provenance"].update(verify_loaded_extension(extension_path))
        upstream = []
        for label, path in [
            ("cli", cli_repo / "linter_exclusions.yml"),
            ("index", index_repo / "linter_exclusions.yml"),
            ("wheel", extension_path / "linter_exclusions.yml"),
        ]:
            if label != "wheel" or path.exists():
                upstream.append(read_yaml(path))
                shutil.copyfile(path, reports / f"{label}-linter_exclusions.yml")
        local_path = source_root / "linter_exclusions.yml"
        local = read_yaml(local_path)
        shutil.copyfile(local_path, reports / "local-linter_exclusions.yml")
        report["missing_exclusions"] = compare_exclusions(local, upstream)
        report["provenance"]["invocation"] = " ".join(LINT_COMMAND)
        # azdev's coverage rules inspect the current Git repository even for wheel-only lint.
        completed = subprocess.run(LINT_COMMAND, cwd=index_repo, check=False, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (reports / "linter.log").write_text(completed.stdout, encoding="utf-8")
        print(completed.stdout)
        report["lint_exit_code"] = completed.returncode
        exit_code = completed.returncode
        report["findings"] = parse_lint(completed.stdout)
        local_keys = flatten_exclusions(local)
        for finding in report["findings"]:
            finding["local_exclusion"] = (
                "yes" if (finding["command"], finding["parameter"], finding["rule"]) in local_keys else "no"
            )
            annotate("error" if finding["severity"] == "HIGH" else "warning",
                     f"{finding['severity']} {finding['rule']}: {finding['command']} "
                     f"{finding['parameter']} - {finding['message']}")
        high = any(finding["severity"] == "HIGH" for finding in report["findings"])
        exit_code = exit_code or int(high)
        report["result"] = "Failed" if exit_code else "Passed with MEDIUM warnings" if report["findings"] else "Passed"
        report["error"] = ""
        if completed.returncode:
            report["error"] = f"azdev exited {completed.returncode}; inspect linter.log, including custom pylint results."
            annotate("error", report["error"])
        if report["missing_exclusions"]:
            annotate("notice", f"{len(report['missing_exclusions'])} local exemptions are missing from the effective "
                     "index configuration. Review the summary; differences alone do not fail this check.")
    except (OSError, ValueError, ImportError, StopIteration, subprocess.SubprocessError, zipfile.BadZipFile,
            yaml.YAMLError) as error:
        exit_code = exit_code or 1
        report["result"] = "Failed"
        report["error"] = f"{type(error).__name__}: {error}"
        if isinstance(error, subprocess.CalledProcessError):
            report["error"] += f"\n{getattr(error, 'stdout', '') or ''}"
        annotate("error", report["error"])
    finally:
        (reports / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (reports / "summary.md").write_text(summary(report), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.exit(check(args.work_dir.resolve(), Path(__file__).resolve().parents[1]))
