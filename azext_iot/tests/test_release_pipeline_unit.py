# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock
from urllib.error import HTTPError
import zipfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_pipeline", ROOT / "scripts/release_pipeline.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SOURCE_SHA = "b" * 40
AUTOMATION_SHA = "a" * 40
PROJECT = "9c543948-e573-4146-832a-bf16b1531204"


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    for name, value in {
        "SYSTEM_DEFINITIONID": "150", "BUILD_BUILDID": "900", "BUILD_SOURCEVERSION": AUTOMATION_SHA,
        "BUILD_SOURCEBRANCH": "refs/heads/dev", "BUILD_REPOSITORY_NAME": release.REPOSITORY,
        "SYSTEM_TEAMPROJECTID": PROJECT, "SYSTEM_JOBATTEMPT": "1",
        "RELEASE_SOURCE_BRANCH": "release/1.1.0-preview", "RELEASE_SOURCE_COMMIT": SOURCE_SHA,
        "RELEASE_PIP_FEED_URL": "https://pkgs.dev.azure.com/test-project/feed/simple/", "RELEASE_MODE": "Validate",
        "RELEASE_GITHUB_TOKEN": "offline-test-placeholder", "INDEX_FORK_REPOSITORY": "test-bot/azure-cli-extensions",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(release, "ado", Mock(side_effect=AssertionError("Unexpected ADO request")))
    monkeypatch.setattr(release, "github", Mock(side_effect=AssertionError("Unexpected GitHub request")))
    directory = tmp_path / "candidate"
    directory.mkdir()
    filename = "azure_iot-1.1.0b1-py3-none-any.whl"
    with zipfile.ZipFile(directory / filename, "w") as wheel:
        wheel.writestr("azure_iot-1.1.0b1.dist-info/METADATA", "Name: azure-iot\nVersion: 1.1.0b1\n")
        wheel.writestr("azext_iot/__init__.py", "")
    with zipfile.ZipFile(directory / "SBOM.zip", "w") as sbom:
        sbom.writestr("_manifest/spdx_2.2/manifest.spdx.json", '{"spdxVersion": "SPDX-2.2"}')
    value = {
        "schema": 1, "repository": release.REPOSITORY, "sourceBranch": "refs/heads/release/1.1.0-preview",
        "sourceCommit": SOURCE_SHA, "producer": {"definition": "150", "build": "900", "commit": AUTOMATION_SHA},
        "wheel": {"file": filename, "sha256": release.digest(directory / filename), "version": "1.1.0b1"},
        "sbom": {"file": "SBOM.zip", "sha256": release.digest(directory / "SBOM.zip")},
    }
    release.write(directory / "candidate.json", value)
    return directory, value


def integration_build(value, result="succeeded"):
    return {
        "id": 901, "definition": {"id": 147}, "project": {"id": PROJECT},
        "repository": {"id": release.REPOSITORY, "type": "GitHub"},
        "sourceVersion": value["sourceCommit"], "sourceBranch": value["sourceBranch"],
        "status": "completed", "result": result,
        "templateParameters": {
            **release.INTEGRATION_PARAMETERS, "services": '[\r\n  "DPS/Hub/ADR/ADU"\r\n]',
            "pythonVersions": '["3.10", "3.13"]', "releaseBuildId": value["producer"]["build"],
        },
    }


def public_release(value, draft=False):
    return {
        "id": 10, "tag_name": "v1.1.0b1", "target_commitish": SOURCE_SHA, "draft": draft, "prerelease": True,
        "assets": [{"name": item["file"], "digest": "sha256:" + item["sha256"]}
                   for item in (value["wheel"], value["sbom"])],
    }


@pytest.mark.parametrize("value", ["", "$(unresolved)", "0", "-1", "1.5", True, "1\n2"])
def test_invalid_identifiers(value):
    with pytest.raises(ValueError):
        release.identifier(value)


@pytest.mark.parametrize("value", ["feature/test", "refs/tags/v1", "dev;echo bad", "dev\n"])
def test_unapproved_source_branches(value):
    with pytest.raises(ValueError):
        release.branch(value)


def test_plan_requires_no_cloud_credentials(candidate, monkeypatch, capsys):
    monkeypatch.delenv("RELEASE_GITHUB_TOKEN")
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["release_pipeline.py", "plan"])
    release.main()
    result = json.loads(capsys.readouterr().out)
    assert result["integrationPipeline"] == 147
    assert "no qualification" in result["mode"]
    release.ado.assert_not_called()
    release.github.assert_not_called()


def test_resolve_freezes_branch_tip_and_downstream_ignores_later_pushes(candidate, tmp_path, monkeypatch, capsys):
    repository = tmp_path / "source-repository"
    release.subprocess.run(["git", "init", "--quiet", "--initial-branch=release/1.1.0-preview", str(repository)],
                           check=True)
    for relative in (
        ".azure-devops/templates/integration-service.yml", ".azure-devops/integration_tests.yml",
        "azext_iot/tests/_ado_pipeline.py", "scripts/check_index_compatibility.py", "scripts/select-openssl.sh",
    ):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("releaseBuildId\n", encoding="utf-8")
    release.subprocess.run(["git", "add", "."], cwd=repository, check=True)
    commit_command = ["git", "-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid",
                      "commit", "--quiet", "-m",
                      "Test release source\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"]
    release.subprocess.run(commit_command, cwd=repository, check=True)
    initial = release.command(["git", "rev-parse", "HEAD"], repository)
    original_run = release.subprocess.run
    fetches = []

    def local_run(args, **kwargs):
        if args[:4] == ["git", "remote", "add", "origin"]:
            args = args[:4] + [repository.as_uri()]
        if args[:2] == ["git", "fetch"]:
            fetches.append(args[-1])
        return original_run(args, **kwargs)

    monkeypatch.setattr(release.subprocess, "run", local_run)
    monkeypatch.setenv("RELEASE_SOURCE_COMMIT", "no-longer-a-source-override")
    resolved = release.checkout(tmp_path / "resolve", resolving=True)
    assert resolved == initial
    assert f"##vso[task.setvariable variable=commit;isOutput=true]{initial}" in capsys.readouterr().out

    changed = repository / "scripts/select-openssl.sh"
    changed.write_text("new branch tip\n", encoding="utf-8")
    release.subprocess.run(["git", "add", "."], cwd=repository, check=True)
    release.subprocess.run(commit_command, cwd=repository, check=True)
    assert release.command(["git", "rev-parse", "HEAD"], repository) != resolved

    monkeypatch.setenv("RELEASE_SOURCE_COMMIT", resolved)
    downstream = tmp_path / "downstream"
    assert release.checkout(downstream) == resolved
    assert (downstream / "scripts/select-openssl.sh").read_text(encoding="utf-8") == "releaseBuildId\n"
    assert fetches == ["refs/heads/release/1.1.0-preview", resolved]


def test_downstream_checkout_requires_internal_resolved_commit(candidate, tmp_path, monkeypatch):
    monkeypatch.delenv("RELEASE_SOURCE_COMMIT")
    with pytest.raises(ValueError, match="RELEASE_SOURCE_COMMIT"):
        release.checkout(tmp_path / "downstream")


def test_valid_candidate_keeps_distinct_automation_and_source(candidate):
    directory, value = candidate
    assert release.verify_candidate(directory) == value
    assert value["producer"]["commit"] != value["sourceCommit"]


@pytest.mark.parametrize("field,new_value", [
    ("schema", True), ("schema", 2), ("repository", "other/repo"), ("sourceCommit", AUTOMATION_SHA),
    ("sourceBranch", "refs/heads/dev"), ("producer", {"definition": "999", "build": "900", "commit": AUTOMATION_SHA}),
])
def test_candidate_provenance_rejected(candidate, field, new_value):
    directory, value = candidate
    value[field] = new_value
    release.write(directory / "candidate.json", value)
    with pytest.raises(ValueError):
        release.verify_candidate(directory)


@pytest.mark.parametrize("asset", ["wheel", "sbom"])
def test_candidate_asset_tampering_rejected(candidate, asset):
    directory, value = candidate
    (directory / value[asset]["file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        release.verify_candidate(directory)


@pytest.mark.parametrize("filename", ["../candidate.whl", "/tmp/other.whl", "azure_iot-x\\other.whl"])
def test_candidate_path_traversal_rejected(candidate, filename):
    directory, value = candidate
    value["wheel"]["file"] = filename
    release.write(directory / "candidate.json", value)
    with pytest.raises(ValueError):
        release.verify_candidate(directory)


def test_candidate_extra_file_rejected(candidate):
    directory, _ = candidate
    (directory / "another.whl").touch()
    with pytest.raises(ValueError, match="three declared"):
        release.verify_candidate(directory)


def test_candidate_creation_preserves_wheel_and_packages_runtime_sbom(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    source = tmp_path / "source"
    dist = source / "dist"
    manifest = dist / "_manifest/spdx_2.2/manifest.spdx.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"spdxVersion":"SPDX-2.2"}', encoding="utf-8")
    (dist / value["wheel"]["file"]).write_bytes((directory / value["wheel"]["file"]).read_bytes())
    monkeypatch.setattr(release, "command", Mock(return_value=SOURCE_SHA))
    monkeypatch.setattr(release.subprocess, "run", Mock())
    output = tmp_path / "generated"
    generated = release.create_candidate(source, output)
    assert generated["wheel"] == value["wheel"]
    assert generated["producer"] == value["producer"]
    with zipfile.ZipFile(output / "SBOM.zip") as archive:
        assert archive.read("_manifest/spdx_2.2/manifest.spdx.json") == manifest.read_bytes()
    assert release.verify_candidate(output) == generated


@pytest.mark.parametrize("url", [
    "http://feed.invalid/simple", "https://user:password@feed.invalid/simple",
    "https://feed.invalid/simple?token=x", "https://feed.invalid/simple#x", "https://feed.invalid:80/simple",
])
def test_invalid_feed_configuration_rejected(url):
    with pytest.raises(ValueError, match="approved HTTPS"):
        release.feed_url(url)


def test_feed_url_normalization():
    assert release.feed_url("https://feed.invalid/path") == "https://feed.invalid/path/simple/"
    assert release.feed_url("https://feed.invalid/path/simple/") == "https://feed.invalid/path/simple/"


def test_build_token_is_scoped_to_child_environment_not_command_or_artifact(candidate, tmp_path, monkeypatch, capsys):
    directory, value = candidate
    source = tmp_path / "source"
    dist = source / "dist"
    dist.mkdir(parents=True)
    (dist / value["wheel"]["file"]).write_bytes((directory / value["wheel"]["file"]).read_bytes())
    (tmp_path / "sbom-tool").touch()
    secret = "offline-placeholder-not-a-real-token"
    token_command = Mock(return_value=secret)
    monkeypatch.setattr(release, "command", token_command)
    run = Mock()
    monkeypatch.setattr(release.subprocess, "run", run)
    monkeypatch.setattr(release.subprocess, "check_output", Mock(return_value="runtime-dependency==1.0\n"))
    monkeypatch.setattr(release, "digest", Mock(
        return_value="bf5d4f99bc98c119d549d08fc02ae92598a7a42772f17317c01031a92632e05b"))
    release.build_candidate(source, tmp_path)
    assert "--resource" in token_command.call_args.args[0]
    assert "https://management.azure.com/" in token_command.call_args.args[0]
    for call in run.call_args_list:
        assert secret not in json.dumps(call.args)
        if "env" in call.kwargs:
            assert secret in call.kwargs["env"]["PIP_INDEX_URL"]
            assert call.kwargs["env"]["PIP_EXTRA_INDEX_URL"] == ""
    assert secret not in capsys.readouterr().out
    assert not (dist / "requirements.txt").exists()


def test_real_ado_repository_and_serialized_parameter_shape(candidate):
    _, value = candidate
    release.validate_integration(integration_build(value), value)


@pytest.mark.parametrize("field,bad", [
    ("definition", {"id": 11}), ("repository", {"id": "other/repo", "type": "GitHub"}),
    ("project", {"id": "other-project"}), ("sourceVersion", AUTOMATION_SHA),
    ("sourceBranch", "refs/heads/dev"),
])
def test_wrong_integration_identity_rejected(candidate, field, bad):
    _, value = candidate
    build = integration_build(value)
    build[field] = bad
    with pytest.raises(ValueError):
        release.validate_integration(build, value)


@pytest.mark.parametrize("field,bad", [
    ("mode", "Dry run"), ("releaseBuildId", "899"), ("services", '["DPS"]'),
    ("pythonVersions", '["3.13"]'), ("regions", "westus"), ("armEndpoint", "canary"),
])
def test_wrong_integration_scope_rejected(candidate, field, bad):
    _, value = candidate
    build = integration_build(value)
    build["templateParameters"][field] = bad
    with pytest.raises(ValueError):
        release.validate_integration(build, value)


def test_existing_child_is_found_by_parent_not_latest_build(candidate, monkeypatch):
    _, value = candidate
    owned = integration_build(value)
    unrelated = integration_build(value)
    unrelated["templateParameters"]["releaseBuildId"] = "899"
    responses = [
        {"definition": {"id": 150}, "sourceVersion": AUTOMATION_SHA, "queueTime": "2026-10-08T00:00:00Z"},
        {"value": [unrelated, owned]},
    ]
    mocked = Mock(side_effect=responses)
    monkeypatch.setattr(release, "ado", mocked)
    assert release.existing_integration(value) == owned
    assert "minTime=" in mocked.call_args_list[1].args[0]
    assert "%24top=1000" in mocked.call_args_list[1].args[0]


def test_duplicate_child_ownership_rejected(candidate, monkeypatch):
    _, value = candidate
    monkeypatch.setattr(release, "ado", Mock(side_effect=[
        {"definition": {"id": 150}, "sourceVersion": AUTOMATION_SHA, "queueTime": "2026-10-08T00:00:00Z"},
        {"value": [integration_build(value), integration_build(value)]},
    ]))
    with pytest.raises(ValueError, match="Multiple children"):
        release.existing_integration(value)


def test_integration_queues_exact_candidate_once(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    monkeypatch.setattr(release, "existing_integration", Mock(return_value=None))
    mocked = Mock(side_effect=[{"id": 901}, integration_build(value)])
    monkeypatch.setattr(release, "ado", mocked)
    record = tmp_path / "child.json"
    assert release.integrate(directory, record) == "901"
    payload = mocked.call_args_list[0].kwargs["data"]
    assert payload["resources"]["repositories"]["self"] == {
        "refName": value["sourceBranch"], "version": SOURCE_SHA,
    }
    assert payload["templateParameters"]["releaseBuildId"] == 900
    assert release.read(record)["producer"] == value["producer"]


def test_retry_reattaches_without_queuing(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "2")
    monkeypatch.setattr(release, "existing_integration", Mock(return_value=integration_build(value)))
    mocked = Mock(return_value=integration_build(value))
    monkeypatch.setattr(release, "ado", mocked)
    assert release.integrate(directory, tmp_path / "child.json") == "901"
    mocked.assert_called_once_with("build/builds/901")


def test_uncertain_retry_does_not_create_another_cohort(candidate, tmp_path, monkeypatch):
    directory, _ = candidate
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "2")
    monkeypatch.setattr(release, "existing_integration", Mock(return_value=None))
    with pytest.raises(ValueError, match="uncertain prior"):
        release.integrate(directory, tmp_path / "child.json")
    release.ado.assert_not_called()


@pytest.mark.parametrize("result", ["failed", "canceled", "partiallySucceeded", "skipped", None])
def test_only_succeeded_child_qualifies(candidate, tmp_path, monkeypatch, result):
    directory, value = candidate
    build = integration_build(value, result)
    monkeypatch.setattr(release, "existing_integration", Mock(return_value=build))
    monkeypatch.setattr(release, "ado", Mock(return_value=build))
    with pytest.raises(RuntimeError, match="finished"):
        release.integrate(directory, tmp_path / "child.json")


def test_timeout_cancels_only_owned_child(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    build = integration_build(value)
    build["status"] = "inProgress"
    build["result"] = None
    monkeypatch.setattr(release, "existing_integration", Mock(return_value=build))
    mocked = Mock(return_value=build)
    monkeypatch.setattr(release, "ado", mocked)
    with pytest.raises(TimeoutError):
        release.integrate(directory, tmp_path / "child.json", timeout=0)
    patches = [call for call in mocked.call_args_list if call.kwargs.get("method") == "PATCH"]
    assert patches
    assert all(call.args == ("build/builds/901",) and call.kwargs["data"] == {"status": "cancelling"}
               for call in patches)


def test_cancellation_rejects_other_parent_receipt(candidate, tmp_path):
    directory, value = candidate
    record = tmp_path / "child.json"
    release.write(record, {"id": "901", "producer": {**value["producer"], "build": "899"}})
    with pytest.raises(ValueError, match="another release"):
        release.cancel_integration(record, directory)
    release.ado.assert_not_called()


def test_integration_artifact_proof_requires_original_bytes_and_manifest(candidate, tmp_path):
    directory, value = candidate
    artifacts = tmp_path / "artifacts"
    wheel_dir = artifacts / "integration-wheel-1"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / value["wheel"]["file"]).write_bytes((directory / value["wheel"]["file"]).read_bytes())
    release.write(wheel_dir / "candidate.json", value)
    release.verify_integration_artifacts(directory, artifacts)
    (wheel_dir / value["wheel"]["file"]).write_bytes(b"rebuilt")
    with pytest.raises(ValueError, match="exact release candidate"):
        release.verify_integration_artifacts(directory, artifacts)


@pytest.mark.parametrize("source_branch", ["refs/heads/feature/test", "refs/heads/preview", "refs/tags/v1"])
def test_feature_automation_cannot_publish(candidate, tmp_path, monkeypatch, source_branch):
    directory, _ = candidate
    monkeypatch.setenv("BUILD_SOURCEBRANCH", source_branch)
    with pytest.raises(ValueError, match="reviewed release automation"):
        release.publish(directory, tmp_path / "release.json")
    release.github.assert_not_called()


def test_release_mode_fails_before_checkout_on_feature_automation(candidate, tmp_path, monkeypatch):
    monkeypatch.setenv("RELEASE_MODE", "Release")
    monkeypatch.setenv("BUILD_SOURCEBRANCH", "refs/heads/feature/test")
    with pytest.raises(ValueError, match="reviewed release automation"):
        release.checkout(tmp_path / "checkout", resolving=True)


def test_existing_public_release_is_reused_without_writes(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    published = public_release(value)
    monkeypatch.setattr(release, "tag_commit", Mock(return_value=SOURCE_SHA))
    monkeypatch.setattr(release, "find_release", Mock(return_value=published))
    mocked = Mock(return_value=published)
    monkeypatch.setattr(release, "github", mocked)
    result = release.publish(directory, tmp_path / "release.json")
    assert result["candidate"] == value
    assert result["tag"] == "v1.1.0b1"
    assert all("method" not in call.kwargs for call in mocked.call_args_list)


@pytest.mark.parametrize("problem", ["tag", "digest", "missing-digest", "missing-asset", "prerelease"])
def test_existing_release_conflicts_are_never_overwritten(candidate, tmp_path, monkeypatch, problem):
    directory, value = candidate
    published = public_release(value)
    if problem in ("digest", "missing-digest"):
        published["assets"][0]["digest"] = "sha256:wrong" if problem == "digest" else None
    if problem == "missing-asset":
        published["assets"] = []
    if problem == "prerelease":
        published["prerelease"] = False
    monkeypatch.setattr(release, "tag_commit", Mock(return_value=AUTOMATION_SHA if problem == "tag" else SOURCE_SHA))
    monkeypatch.setattr(release, "find_release", Mock(return_value=published))
    with pytest.raises(ValueError):
        release.publish(directory, tmp_path / "release.json")
    release.github.assert_not_called()


def test_draft_is_only_published_after_both_verified_uploads(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    staged = public_release(value, draft=True)
    staged["assets"] = []
    events = []
    monkeypatch.setattr(release, "find_release", Mock(return_value=None))
    monkeypatch.setattr(release, "tag_commit", Mock(side_effect=[None, None, SOURCE_SHA]))

    def github(resource, method="GET", data=None):
        events.append((method, resource, data))
        if method == "PATCH":
            assert len(staged["assets"]) == 2
            staged["draft"] = False
        return staged

    def upload(_url, _token, **kwargs):
        expected = next(item for item in (value["wheel"], value["sbom"])
                        if release.hashlib.sha256(kwargs["data"]).hexdigest() == item["sha256"])
        asset = {"name": expected["file"], "digest": "sha256:" + expected["sha256"]}
        staged["assets"].append(asset)
        return asset

    monkeypatch.setattr(release, "github", github)
    monkeypatch.setattr(release, "api", upload)
    result = release.publish(directory, tmp_path / "release.json")
    assert result["candidate"] == value
    assert [method for method, _, _ in events] == ["POST", "POST", "PATCH", "GET"]
    assert events[1][2] == {"ref": "refs/tags/v1.1.0b1", "sha": SOURCE_SHA}


def test_bad_upload_never_promotes_draft(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    staged = public_release(value, draft=True)
    staged["assets"] = []
    monkeypatch.setattr(release, "find_release", Mock(return_value=staged))
    monkeypatch.setattr(release, "tag_commit", Mock(return_value=None))
    monkeypatch.setattr(release, "api", Mock(return_value={"digest": "sha256:wrong"}))
    with pytest.raises(ValueError, match="remains a draft"):
        release.publish(directory, tmp_path / "release.json")
    release.github.assert_not_called()


def test_required_index_check_overrides_advisory_summary(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    work = tmp_path / "compat"
    (work / "wheels").mkdir(parents=True)
    (work / "wheels" / value["wheel"]["file"]).write_bytes((directory / value["wheel"]["file"]).read_bytes())
    release.write(work / "reports/report.json", {"result": "Passed with MEDIUM warnings", "error": ""})
    check = Mock(return_value=0)
    monkeypatch.setattr(release.runpy, "run_path", Mock(return_value={"check": check}))
    release.index_check(tmp_path / "source", directory, work)
    assert "Required release" in (work / "reports/summary.md").read_text(encoding="utf-8")
    check.return_value = 1
    with pytest.raises(RuntimeError, match="Required index compatibility failed"):
        release.index_check(tmp_path / "source", directory, work)


@pytest.fixture
def index_context(candidate, tmp_path, monkeypatch):
    directory, value = candidate
    published = public_release(value)
    monkeypatch.setattr(release, "find_release", Mock(return_value=published))
    monkeypatch.setattr(release, "tag_commit", Mock(return_value=SOURCE_SHA))
    receipt = tmp_path / "release.json"
    url = f"https://github.com/{release.REPOSITORY}/releases/download/v1.1.0b1/{value['wheel']['file']}"
    release.write(receipt, {"release": 10, "tag": "v1.1.0b1", "wheelUrl": url, "candidate": value})
    work = tmp_path / "submission"
    index = work / "azure-cli-extensions/src/index.json"
    before = {"extensions": {"azure-iot": [{
        "metadata": {"version": "0.31.0"}, "downloadUrl": "https://example.invalid/old.whl",
        "filename": "old.whl", "sha256Digest": "c" * 64,
    }], "other": [{"metadata": {"version": "1.0"}}]}}
    release.write(index, before)
    entry = {"metadata": {"version": "1.1.0b1"}, "downloadUrl": url,
             "filename": value["wheel"]["file"], "sha256Digest": value["wheel"]["sha256"]}

    def run(args, **_kwargs):
        if args[:3] == ["azdev", "extension", "update-index"]:
            updated = deepcopy(before)
            updated["extensions"]["azure-iot"].append(entry)
            release.write(index, updated)

    monkeypatch.setattr(release.subprocess, "run", Mock(side_effect=run))
    monkeypatch.setattr(release, "command", Mock(return_value="c" * 40))
    return directory, receipt, work, index, entry


def test_index_submission_preserves_versions_and_never_merges(index_context, monkeypatch):
    directory, receipt, work, index, _ = index_context
    writes = []

    def github(resource, method="GET", **kwargs):
        if method != "GET":
            writes.append((resource, method, kwargs["data"]))
            return {"html_url": "https://github.com/Azure/azure-cli-extensions/pull/123"}
        if resource == "repos/test-bot/azure-cli-extensions":
            return {"fork": True, "parent": {"full_name": release.INDEX_REPOSITORY}}
        if "/git/ref/heads/" in resource:
            return None
        if "/contents/" in resource:
            return {"sha": "old-index-sha"}
        if "/pulls?" in resource:
            return []
        raise AssertionError(resource)

    monkeypatch.setattr(release, "github", github)
    result = release.index_pull_request(directory, receipt, work)
    assert result["status"] == "review-required"
    assert len(release.read(index)["extensions"]["azure-iot"]) == 2
    assert [method for _, method, _ in writes] == ["POST", "PUT", "POST"]
    assert all("/merge" not in resource for resource, _, _ in writes)
    assert writes[1][0].startswith("repos/test-bot/")
    assert writes[2][0] == "repos/Azure/azure-cli-extensions/pulls"
    assert writes[2][2]["base"] == "main"


def test_index_identical_branch_reuses_open_pr(index_context, monkeypatch):
    directory, receipt, work, index, _ = index_context

    def github(resource, **kwargs):
        assert "method" not in kwargs
        if resource == "repos/test-bot/azure-cli-extensions":
            return {"fork": True, "parent": {"full_name": release.INDEX_REPOSITORY}}
        if "/git/ref/heads/" in resource:
            return {"object": {"sha": "d" * 40}}
        if "/contents/" in resource:
            return {"encoding": "base64", "content": base64.b64encode(index.read_bytes()).decode()}
        if "/pulls?" in resource:
            return [{"html_url": "https://github.com/Azure/azure-cli-extensions/pull/123"}]
        raise AssertionError(resource)

    monkeypatch.setattr(release, "github", github)
    assert release.index_pull_request(directory, receipt, work)["status"] == "review-required"


def test_index_existing_version_cannot_point_elsewhere(index_context, monkeypatch):
    directory, receipt, work, index, entry = index_context
    before = release.read(index)
    before["extensions"]["azure-iot"].append({**entry, "sha256Digest": "wrong"})
    release.write(index, before)
    monkeypatch.setattr(release, "github", Mock(return_value={
        "fork": True, "parent": {"full_name": release.INDEX_REPOSITORY},
    }))
    with pytest.raises(ValueError, match="conflicting metadata"):
        release.index_pull_request(directory, receipt, work)


def test_large_index_content_uses_blob_api(monkeypatch):
    data = b'{"extensions": {}}'
    mocked = Mock(side_effect=[
        {"encoding": "none", "sha": "blob-sha", "content": ""},
        {"encoding": "base64", "content": base64.b64encode(data).decode()},
    ])
    monkeypatch.setattr(release, "github", mocked)
    assert release.github_contents("test/repo", "main") == data
    assert mocked.call_args_list[-1].args == ("repos/test/repo/git/blobs/blob-sha",)


def test_existing_index_branch_can_be_reused_after_unrelated_main_updates(monkeypatch):
    before = {"extensions": {"azure-iot": [], "other": []}}
    entry = {"metadata": {"version": "1.1.0b1"}, "sha256Digest": "a" * 64}
    after = deepcopy(before)
    after["extensions"]["azure-iot"] = [entry]
    monkeypatch.setattr(release, "github", Mock(return_value={
        "ahead_by": 1, "behind_by": 3, "files": [{"filename": "src/index.json"}],
        "commits": [{"parents": [{"sha": "base-sha"}]}], "merge_base_commit": {"sha": "base-sha"},
    }))
    monkeypatch.setattr(release, "github_contents", Mock(return_value=json.dumps(before).encode()))
    release.verify_existing_index_branch("test-bot/azure-cli-extensions", "release/azure-iot-1.1.0b1",
                                         json.dumps(after).encode(), entry)
    after["extensions"]["other"].append({"unrelated": True})
    with pytest.raises(ValueError, match="more than"):
        release.verify_existing_index_branch("test-bot/azure-cli-extensions", "release/azure-iot-1.1.0b1",
                                             json.dumps(after).encode(), entry)


def test_existing_index_branch_unrelated_files_are_rejected(monkeypatch):
    monkeypatch.setattr(release, "github", Mock(return_value={
        "ahead_by": 1, "files": [{"filename": "other.py"}],
        "commits": [{"parents": [{"sha": "base-sha"}]}], "merge_base_commit": {"sha": "base-sha"},
    }))
    with pytest.raises(ValueError, match="unrelated commits or files"):
        release.verify_existing_index_branch("test-bot/azure-cli-extensions", "release/test", b"{}", {})


def test_api_does_not_retry_writes_or_follow_redirects(monkeypatch):
    opener = Mock()
    opener.open.side_effect = HTTPError("https://api.github.com/test", 503, "unavailable", {}, None)
    monkeypatch.setattr(release, "build_opener", Mock(return_value=opener))
    with pytest.raises(RuntimeError, match="no automatic write retry"):
        release.api("https://api.github.com/test", "offline-placeholder", method="POST", data={})
    opener.open.assert_called_once()
    assert release.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None


def all_stages():
    pipeline = yaml.safe_load((ROOT / ".azure-devops/release.yml").read_text(encoding="utf-8"))
    stages = [pipeline["stages"][0]]
    for group in pipeline["stages"][1:]:
        stages.extend(next(iter(group.values())))
    return pipeline, {stage["stage"]: stage for stage in stages}


def test_yaml_is_manual_plan_by_default_and_never_continues_on_error():
    pipeline, stages = all_stages()
    assert pipeline["trigger"] == "none"
    assert pipeline["pr"] == "none"
    assert pipeline["parameters"][0]["default"] == "Plan"
    assert {parameter["name"] for parameter in pipeline["parameters"]} == {"mode", "sourceBranch"}
    assert "RELEASE_SOURCE_COMMIT" not in json.dumps(stages["Resolve"])
    assert set(stages) == {
        "Resolve", "Build", "Unit", "Security", "CommandLint", "IndexCompatibility", "Integration", "Publish", "IndexPR",
    }
    text = (ROOT / ".azure-devops/release.yml").read_text(encoding="utf-8")
    assert "continueOnError" not in text
    assert "azure/login" not in text
    assert "ADO_PAT" not in text


def test_yaml_preserves_all_twelve_unit_style_combinations():
    _, stages = all_stages()
    matrix = stages["Unit"]["jobs"][0]["strategy"]["matrix"]
    assert {(leg["image"], leg["python"]) for leg in matrix.values()} == {
        (image, version) for image in ("ubuntu-24.04", "windows-2025", "macOS-15")
        for version in ("3.10", "3.11", "3.12", "3.13")
    }
    steps = stages["Unit"]["jobs"][0]["steps"]
    assert any(step.get("script") == "tox run --skip-pkg-install" for step in steps)


@pytest.mark.parametrize("name", ["Integration", "Publish", "IndexPR"])
def test_yaml_requires_every_dependency_to_succeed_not_skip_or_partial(name):
    _, stages = all_stages()
    stage = stages[name]
    for dependency in stage["dependsOn"]:
        assert f"eq(dependencies.{dependency}.result, 'Succeeded')" in stage["condition"]
    assert "not(canceled())" in stage["condition"]


def test_yaml_exact_candidate_and_narrow_credential_mapping():
    _, stages = all_stages()
    build = stages["Build"]["jobs"][0]["steps"]
    assert build[-1]["artifact"] == "release-candidate"
    security = stages["Security"]["jobs"][0]["steps"]
    assert any("git checkout --detach" in step.get("pwsh", "") for step in security)
    scanner = next(step for step in security if step.get("task") == "MicrosoftSecurityDevOps@1")
    assert scanner["inputs"]["break"] is True
    integration = stages["Integration"]["jobs"][0]["steps"]
    download = next(step for step in integration if step.get("task") == "DownloadPipelineArtifact@2")
    assert download["inputs"]["pipelineId"] == "$(integrationBuildId)"
    assert download["inputs"]["definition"] == "147"
    for name, stage in stages.items():
        if name not in ("Publish", "IndexPR"):
            assert "ReleaseGitHubToken" not in json.dumps(stage)
    assert "refs/heads/dev" in stages["Publish"]["condition"]
    for name in ("Publish", "IndexPR"):
        assert stages[name]["variables"][0] == {"group": "aziotcli_release_publish"}
