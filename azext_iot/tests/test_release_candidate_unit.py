# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline tests for pipeline 147's optional, pinned release candidate input."""

from copy import deepcopy
import hashlib
from http.client import HTTPException
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
import zipfile

import pytest
import yaml

from azext_iot.tests import _ado_pipeline as pipeline
from azext_iot.tests import _release_candidate as release

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "a" * 40
AUTOMATION = "b" * 40
PROJECT = "11111111-2222-3333-4444-555555555555"
WHEEL = "azure_iot-1.1.0b1-py3-none-any.whl"


@pytest.fixture
def environment():
    return {
        "RELEASE_BUILD_ID": "2468", "RELEASE_PIPELINE_ID": "222",
        "SYSTEM_TEAMPROJECTID": PROJECT, "SYSTEM_COLLECTIONURI": "https://dev.azure.com/offline/",
        "SYSTEM_ACCESSTOKEN": "offline-token-never-real",
        "BUILD_REPOSITORY_NAME": release.REPOSITORY,
        "BUILD_SOURCEVERSION": SOURCE, "BUILD_SOURCEBRANCH": "refs/heads/release/1.1.0-preview",
    }


@pytest.fixture
def parent():
    return {
        "id": 2468, "definition": {"id": 222, "project": {"id": PROJECT}}, "project": {"id": PROJECT},
        "repository": {"id": release.REPOSITORY, "name": release.REPOSITORY, "type": "GitHub"},
        "sourceVersion": AUTOMATION, "sourceBranch": "refs/heads/dev",
        "status": "inProgress", "result": None,
    }


def write_wheel(directory, metadata=None, metadata_path=None, extra=None):
    with zipfile.ZipFile(directory / WHEEL, "w") as archive:
        archive.writestr(metadata_path or "azure_iot-1.1.0b1.dist-info/METADATA",
                         metadata or "Metadata-Version: 2.1\nName: azure-iot\nVersion: 1.1.0b1\n")
        archive.writestr("azure_iot-1.1.0b1.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
        archive.writestr("azext_iot/__init__.py", "# offline wheel fixture\n")
        if extra:
            archive.writestr(*extra)


def write_manifest(directory, manifest):
    (directory / "candidate.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def artifact(tmp_path, environment):
    directory = tmp_path / "release-candidate"
    directory.mkdir()
    write_wheel(directory)
    with zipfile.ZipFile(directory / "SBOM.zip", "w") as archive:
        archive.writestr("sbom.json", "{}")
    manifest = {
        "schema": 1, "repository": release.REPOSITORY,
        "sourceBranch": environment["BUILD_SOURCEBRANCH"], "sourceCommit": SOURCE,
        "producer": {"definition": "222", "build": "2468", "commit": AUTOMATION},
        "wheel": {"file": WHEEL, "sha256": hashlib.sha256((directory / WHEEL).read_bytes()).hexdigest(),
                  "version": "1.1.0b1"},
    }
    write_manifest(directory, manifest)
    return directory, manifest


def set_field(value, path, replacement):
    keys = path.split(".")
    for key in keys[:-1]:
        value = value[key]
    value[keys[-1]] = replacement


def test_external_mode_is_default_off_and_normal_build_is_unchanged():
    entry = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text(encoding="utf-8"))
    parameter = next(item for item in entry["parameters"] if item["name"] == "releaseBuildId")
    assert parameter["type"] == "number" and parameter["default"] == 0
    stages = entry["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    steps = next(stage for stage in stages if stage.get("stage") == "Build")["jobs"][0]["steps"]
    assert len(steps) == 2
    assert steps[0]["${{ if eq(parameters.releaseBuildId, 0) }}"] == [
        {"template": "templates/setup-python.yml", "parameters": {"pythonVersion": "3.13"}},
        {"bash": "python -m build --wheel", "displayName": "Build the immutable test candidate"},
        {"publish": "dist", "artifact": "integration-wheel-$(System.JobAttempt)"},
    ]
    assert not any(item.get("name") == "ReleasePipelineId" for item in entry["variables"])
    assert entry["variables"][0] == {"group": "aziotcli_test_primary"}
    external = steps[1]["${{ if ne(parameters.releaseBuildId, 0) }}"]
    assert len(external) == 5
    setup, lookup, download, verify, publish = external
    assert setup == {"task": "UsePythonVersion@0", "inputs": {"versionSpec": "3.13"}}
    assert "_release_candidate.py parent --metadata" in lookup["bash"]
    assert lookup["env"]["SYSTEM_ACCESSTOKEN"] == "$(System.AccessToken)"
    assert "_release_candidate.py verify" in verify["bash"]
    assert "SYSTEM_ACCESSTOKEN" not in verify["env"]
    for step in (lookup, verify):
        assert step["env"]["RELEASE_BUILD_ID"] == "${{ parameters.releaseBuildId }}"
        assert step["env"]["RELEASE_PIPELINE_ID"] == "$(ReleasePipelineId)"
        assert "condition" not in step and "continueOnError" not in step
    assert lookup["env"]["PARENT_METADATA"] == verify["env"]["PARENT_METADATA"]
    assert download == {
        "task": "DownloadPipelineArtifact@2",
        "inputs": {
            "buildType": "specific", "project": "$(System.TeamProjectId)", "definition": "$(ReleasePipelineId)",
            "buildVersionToDownload": "specific", "pipelineId": "${{ parameters.releaseBuildId }}",
            "artifactName": "release-candidate",
            "targetPath": "$(Pipeline.Workspace)/release-candidate-$(System.JobAttempt)",
        },
    }
    assert publish == {
        "publish": download["inputs"]["targetPath"], "artifact": "integration-wheel-$(System.JobAttempt)",
    }
    assert verify["env"]["CANDIDATE"] == publish["publish"]


@pytest.mark.parametrize("status,result", [("inProgress", None), ("inProgress", "none"), ("completed", "succeeded")])
def test_valid_parent_and_candidate_do_not_require_completed_parent_or_identical_automation_commit(
        parent, environment, artifact, status, result):
    parent.update(status=status, result=result)
    directory, _ = artifact
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    assert parent["sourceVersion"] != environment["BUILD_SOURCEVERSION"]
    release.validate_parent(parent, environment)
    release.verify_candidate(directory, parent, environment)
    assert original == {path.name: path.read_bytes() for path in directory.iterdir()}


@pytest.mark.parametrize("field,value,reason", [
    ("id", 2469, "build ID"), ("id", "2468", "build ID"), ("id", True, "build ID"),
    ("definition.id", 223, "definition"), ("definition.id", "222", "definition"),
    ("project.id", "99999999-2222-3333-4444-555555555555", "project"),
    ("definition.project.id", None, "project"),
    ("repository.name", "other/repository", "repository"), ("repository.id", "other/repository", "repository"),
    ("repository.type", "TfsGit", "repository"), ("sourceVersion", "not-a-commit", "commit"),
    ("status", "cancelling", "in progress"), ("status", "notStarted", "in progress"),
    ("status", "completed", "in progress"), ("result", "failed", "in progress"),
    ("result", "canceled", "in progress"), ("result", "partiallySucceeded", "in progress"),
    ("definition", None, "objects"), ("repository", [], "objects"),
])
def test_wrong_parent_fails_closed(parent, environment, field, value, reason):
    set_field(parent, field, value)
    with pytest.raises(release.ProvenanceError, match=reason):
        release.validate_parent(parent, environment)


@pytest.mark.parametrize("field", ["RELEASE_PIPELINE_ID", "RELEASE_BUILD_ID"])
@pytest.mark.parametrize("value", [None, "", "$(ReleasePipelineId)", "0", "-1", "1.5", "222.0", " 222", "all", "0222"])
def test_invalid_or_unconfigured_producer_never_makes_network_request(monkeypatch, environment, field, value):
    if value is None:
        del environment[field]
    else:
        environment[field] = value
    opener = Mock()
    monkeypatch.setattr(release, "build_opener", opener)
    with pytest.raises(release.ProvenanceError, match="positive integer"):
        release.fetch_parent(environment)
    opener.assert_not_called()


@pytest.mark.parametrize("field,value,reason", [
    ("schema", 2, "schema"), ("schema", True, "schema"),
    ("repository", "other/repository", "repository"),
    ("sourceCommit", AUTOMATION, "source commit/branch"),
    ("sourceCommit", SOURCE.upper(), "source commit/branch"),
    ("sourceBranch", "refs/heads/dev", "source commit/branch"),
    ("producer.definition", "223", "producer"), ("producer.build", "2469", "producer"),
    ("producer.build", 2468, "producer"), ("producer.commit", SOURCE, "producer"),
    ("wheel.sha256", "0" * 64, "SHA256"), ("wheel.sha256", None, "SHA256"),
    ("wheel.version", "1.2.0", "filename distribution/version"),
    ("wheel.file", "../" + WHEEL, "safe basename"), ("wheel.file", "/" + WHEEL, "safe basename"),
    ("wheel.file", "directory/" + WHEEL, "safe basename"), ("wheel.file", "C:\\" + WHEEL, "safe basename"),
    ("wheel.file", "other-1.1.0b1-py3-none-any.whl", "safe basename"),
    ("producer", [], "objects"), ("wheel", None, "objects"),
])
def test_invalid_manifest_fails_closed(parent, environment, artifact, field, value, reason):
    directory, manifest = artifact
    set_field(manifest, field, value)
    write_manifest(directory, manifest)
    with pytest.raises(release.ProvenanceError, match=reason):
        release.verify_candidate(directory, parent, environment)


@pytest.mark.parametrize("missing", ["candidate.json", "SBOM.zip", WHEEL])
def test_missing_candidate_files(parent, environment, artifact, missing):
    directory, _ = artifact
    (directory / missing).unlink()
    with pytest.raises(release.ProvenanceError, match="manifest|artifact"):
        release.verify_candidate(directory, parent, environment)


@pytest.mark.parametrize("extra", ["extra.whl", "nested", "unexpected.txt"])
def test_extra_files_and_nested_wheels_are_rejected(parent, environment, artifact, extra):
    directory, _ = artifact
    if extra == "nested":
        (directory / extra).mkdir()
        (directory / extra / WHEEL).write_bytes(b"extra wheel")
    else:
        (directory / extra).write_bytes(b"unexpected file")
    with pytest.raises(release.ProvenanceError, match="artifact"):
        release.verify_candidate(directory, parent, environment)


@pytest.mark.parametrize("name", ["candidate.json", "SBOM.zip", WHEEL])
def test_symlinks_are_rejected(parent, environment, artifact, name):
    directory, _ = artifact
    target = directory.parent / name
    (directory / name).rename(target)
    try:
        (directory / name).symlink_to(target)
    except OSError:
        pytest.skip("Symlinks are unavailable on this platform.")
    with pytest.raises(release.ProvenanceError, match="unsafe|artifact"):
        release.verify_candidate(directory, parent, environment)


def test_tampered_wheel_bytes(parent, environment, artifact):
    directory, _ = artifact
    with (directory / WHEEL).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(release.ProvenanceError, match="SHA256"):
        release.verify_candidate(directory, parent, environment)


@pytest.mark.parametrize("metadata,metadata_path,extra,reason", [
    ("Name: other\nVersion: 1.1.0b1\n", None, None, "distribution"),
    ("Name: azure-iot\nVersion: 1.2.0\n", None, None, "version"),
    ("Name: azure-iot\nName: other\nVersion: 1.1.0b1\n", None, None, "distribution"),
    (None, "other-1.1.0b1.dist-info/METADATA", None, "METADATA"),
    (None, None, ("other-1.1.0b1.dist-info/METADATA", "Name: other\n"), "METADATA"),
    (None, None, ("../unsafe.py", ""), "unsafe"),
    (None, None, ("/absolute.py", ""), "unsafe"),
    (None, None, ("dir\\unsafe.py", ""), "unsafe"),
])
def test_matching_hash_does_not_bypass_wheel_validation(
        parent, environment, artifact, metadata, metadata_path, extra, reason):
    directory, manifest = artifact
    write_wheel(directory, metadata, metadata_path, extra)
    manifest["wheel"]["sha256"] = hashlib.sha256((directory / WHEEL).read_bytes()).hexdigest()
    write_manifest(directory, manifest)
    with pytest.raises(release.ProvenanceError, match=reason):
        release.verify_candidate(directory, parent, environment)


@pytest.mark.parametrize("contents", ['{"schema":1,"schema":1}', "{", "[]"])
def test_malformed_or_duplicate_manifest(parent, environment, artifact, contents):
    directory, _ = artifact
    (directory / "candidate.json").write_text(contents, encoding="utf-8")
    with pytest.raises(release.ProvenanceError, match="provenance JSON"):
        release.verify_candidate(directory, parent, environment)


def mock_rest(monkeypatch, parent):
    response = BytesIO(json.dumps(parent).encode())
    response.status = 200
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(release, "build_opener", factory)
    return factory, opener


def test_authenticated_metadata_request_is_project_scoped_no_redirects_and_sanitized(
        monkeypatch, environment, parent, capsys):
    parent["url"] = "https://unused.invalid/?signed=not-for-logs"
    factory, opener = mock_rest(monkeypatch, parent)
    result = release.fetch_parent(environment)
    request = opener.open.call_args.args[0]
    assert request.full_url == f"https://dev.azure.com/offline/{PROJECT}/_apis/build/builds/2468?api-version=7.1"
    assert request.get_header("Authorization") == "Bearer offline-token-never-real"
    assert opener.open.call_args.kwargs == {"timeout": 30}
    assert isinstance(factory.call_args.args[0], release.NoRedirect)
    assert "url" not in result
    assert not any(capsys.readouterr())
    with pytest.raises(release.ProvenanceError, match="redirects"):
        factory.call_args.args[0].redirect_request(request, None, 302, "", {}, "https://unused.invalid/")


@pytest.mark.parametrize("error", [
    HTTPError("https://unused.invalid/?signed=never-log", 403, "offline-token-never-real", {}, None),
    URLError("offline-token-never-real"),
    HTTPException("offline-token-never-real"),
])
def test_metadata_failures_do_not_log_tokens_urls_or_tracebacks(monkeypatch, environment, error, tmp_path, capsys):
    monkeypatch.setattr(release.os, "environ", environment)
    factory, opener = mock_rest(monkeypatch, {})
    opener.open.side_effect = error
    output = tmp_path / "parent.json"
    assert release.main(["parent", "--metadata", str(output)]) == 1
    factory.assert_called_once()
    captured = capsys.readouterr()
    assert "metadata lookup failed" in captured.err
    assert "offline-token" not in captured.err and "signed" not in captured.err and "Traceback" not in captured.err
    assert not output.exists()


@pytest.mark.parametrize("key,value", [
    ("SYSTEM_ACCESSTOKEN", ""), ("SYSTEM_ACCESSTOKEN", "$(System.AccessToken)"),
    ("SYSTEM_COLLECTIONURI", "http://dev.azure.com/offline/"),
    ("SYSTEM_COLLECTIONURI", "https://unused.invalid/"),
    ("SYSTEM_COLLECTIONURI", "https://user:password@dev.azure.com/offline/"),
    ("SYSTEM_COLLECTIONURI", "https://dev.azure.com/offline/?signed=not-allowed"),
    ("SYSTEM_TEAMPROJECTID", "../other-project"),
])
def test_no_network_for_invalid_auth_or_project_context(monkeypatch, environment, key, value):
    environment[key] = value
    factory = Mock()
    monkeypatch.setattr(release, "build_opener", factory)
    with pytest.raises(release.ProvenanceError):
        release.fetch_parent(environment)
    factory.assert_not_called()


def test_cli_validates_then_preserves_candidate_for_existing_retry_selection(
        monkeypatch, environment, parent, artifact, tmp_path, capsys):
    monkeypatch.setattr(release.os, "environ", environment)
    mock_rest(monkeypatch, parent)
    metadata = tmp_path / "parent.json"
    assert release.main(["parent", "--metadata", str(metadata)]) == 0
    directory, _ = artifact
    assert release.main(["verify", "--metadata", str(metadata), "--candidate", str(directory)]) == 0
    history = tmp_path / "history"
    # Native publish/download keeps all original bytes, including the audit manifest.
    shutil.copytree(directory, history / "integration-wheel-1")
    shutil.copytree(directory, history / "integration-wheel-2")
    target = tmp_path / "selected"
    pipeline.candidate(history, target)
    assert (target / WHEEL).read_bytes() == (directory / WHEEL).read_bytes()
    assert (history / "integration-wheel-1/candidate.json").read_bytes() == (directory / "candidate.json").read_bytes()
    captured = capsys.readouterr()
    assert "without rebuilding" in captured.out and not captured.err


def test_standalone_stdlib_helper_fails_explicitly_without_manifest(environment, parent, tmp_path):
    metadata = tmp_path / "parent.json"
    metadata.write_text(json.dumps(parent), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "azext_iot/tests/_release_candidate.py"), "verify",
         "--metadata", str(metadata), "--candidate", str(tmp_path)],
        env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "manifest is missing" in result.stderr and "Traceback" not in result.stderr


def test_child_repository_and_source_context_are_required(parent, environment, artifact):
    for key in ("BUILD_REPOSITORY_NAME", "BUILD_SOURCEVERSION", "BUILD_SOURCEBRANCH"):
        invalid = deepcopy(environment)
        invalid.pop(key)
        with pytest.raises(release.ProvenanceError, match="Child"):
            release.verify_candidate(artifact[0], parent, invalid)
