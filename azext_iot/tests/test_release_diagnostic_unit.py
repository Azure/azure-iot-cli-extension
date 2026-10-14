# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def diagnostic(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("release_diagnostic")
    monkeypatch.setenv("SYSTEM_TEAMPROJECTID", "9c543948-e573-4146-832a-bf16b1531204")
    monkeypatch.setenv("SYSTEM_DEFINITIONID", "161")
    monkeypatch.setenv("BUILD_BUILDID", "12345")
    monkeypatch.setenv("BUILD_SOURCEVERSION", "a" * 40)
    return module


def test_no_publish_or_scanner_substitute(diagnostic):
    pipeline = yaml.safe_load((ROOT / ".azure-devops/release.yml").read_text())
    assert pipeline["parameters"][0]["values"] == ["Partial"]
    text = (ROOT / ".azure-devops/templates/release-stages.yml").read_text()
    for forbidden in ("stage: Security", "stage: Publish", "ReleaseGitHubToken", "aziotcli_release_publish"):
        assert forbidden not in text
    assert "stage: MissingCoverage" in text
    assert "condition: always()" in text
    with pytest.raises(ValueError, match="disabled"):
        diagnostic.release.automation_allowed()


def test_followup_only_runs_windows_after_feed_authentication():
    template = yaml.safe_load((ROOT / ".azure-devops/templates/release-unit.yml").read_text())
    job = template["jobs"][0]
    assert job["strategy"]["matrix"] == {
        "Python310": {"python": "3.10"}, "Python311": {"python": "3.11"},
        "Python312": {"python": "3.12"}, "Python313": {"python": "3.13"},
    }
    steps = job["steps"]
    feed = next(index for index, step in enumerate(steps) if step.get("template") == "release-feed.yml")
    selection = next(index for index, step in enumerate(steps) if step.get("task") == "UsePythonVersion@0")
    assert feed < selection
    source = yaml.safe_load((ROOT / ".azure-devops/templates/release-source.yml").read_text())
    assert source["steps"][1]["inputs"] == {"versionSpec": "3.13", "disableDownloadFromRegistry": True}
    text = (ROOT / ".azure-devops/templates/release-stages.yml").read_text()
    assert "platform: Windows" in text and "platform: Linux" not in text and "platform: MacOS" not in text


@pytest.mark.parametrize("denied", [None, 0, 1, 2, 3, 4, 5])
def test_permissions_use_actual_token_and_fail_closed(diagnostic, monkeypatch, denied):
    calls = []

    def get(url, authenticated=False):
        assert authenticated
        calls.append(url)
        return {"count": 1, "value": [len(calls) - 1 != denied]}

    monkeypatch.setattr(diagnostic, "get", get)
    if denied is None:
        diagnostic.permissions()
    else:
        with pytest.raises(RuntimeError, match="Missing required"):
            diagnostic.permissions()
    assert len(calls) == 6
    assert all("alwaysAllowAdministrators=false" in url for url in calls)


@pytest.mark.parametrize("competing", [False, True])
def test_admission_blocks_other_ado_workloads(diagnostic, monkeypatch, competing):
    builds = [{"id": 12345}] + ([{"id": 45678}] if competing else [])
    monkeypatch.setattr(diagnostic.release, "ado", lambda _url: {"value": builds})
    monkeypatch.setattr(diagnostic, "get", lambda _url: {"total_count": 0})
    monkeypatch.setattr(diagnostic, "ADMISSION_DEADLINE", diagnostic.datetime.max.replace(
        tzinfo=diagnostic.timezone.utc))
    if competing:
        with pytest.raises(RuntimeError, match="Other ADO"):
            diagnostic.admission()
    else:
        diagnostic.admission()


def test_admission_blocks_github_workloads(diagnostic, monkeypatch):
    monkeypatch.setattr(diagnostic.release, "ado", lambda _url: {"value": [{"id": 12345}]})
    monkeypatch.setattr(diagnostic, "get", lambda _url: {"total_count": 1})
    monkeypatch.setattr(diagnostic, "ADMISSION_DEADLINE", diagnostic.datetime.max.replace(
        tzinfo=diagnostic.timezone.utc))
    with pytest.raises(RuntimeError, match="GitHub workflows"):
        diagnostic.admission()


def test_expired_admission_never_queues(diagnostic, monkeypatch):
    monkeypatch.setattr(diagnostic, "ADMISSION_DEADLINE", diagnostic.datetime.min.replace(
        tzinfo=diagnostic.timezone.utc))
    with pytest.raises(RuntimeError, match="expired"):
        diagnostic.admission()


def test_report_cannot_qualify_even_when_components_succeed(diagnostic, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(diagnostic.release, "ado", lambda _url: {"records": [
        {"type": "Stage", "name": "Build", "state": "completed", "result": "succeeded"},
    ]})
    output = tmp_path / "report.json"
    assert diagnostic.report(output) == 1
    report = json.loads(output.read_text())
    assert report["releaseQualified"] is False
    assert report["publicationAllowed"] is False
    assert report["missingChecks"] == ["MicrosoftSecurityDevOps@1"]
    assert "INCOMPLETE" in capsys.readouterr().out
