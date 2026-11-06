# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = "a" * 40
SOURCE = "b" * 40


@pytest.fixture
def monitor():
    spec = importlib.util.spec_from_file_location("release_monitor_unit", ROOT / "scripts/release_monitor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release(version, extension="azure-iot", *, preview=False, draft=False):
    repository = "Azure/azure-iot-cli-extension" if extension == "azure-iot" else "Azure/azure-iot-ops-cli-extension"
    name = f"{extension.replace('-', '_')}-{version}-py3-none-any.whl"
    return {
        "id": 123, "tag_name": f"v{version}", "draft": draft, "prerelease": preview,
        "assets": [{
            "name": name, "digest": "sha256:" + "d" * 64,
            "browser_download_url": f"https://github.com/{repository}/releases/download/v{version}/{name}",
        }],
    }


@pytest.fixture
def manifest(monitor, mocker):
    mocker.patch.object(monitor, "tag_commit", return_value=SOURCE)
    return monitor.resolve("azure-iot", "public", "ga", AUTOMATION, [release("1.0.0")])


def profile(version, cloud="public"):
    return {
        "version": version, "milestone": ".".join(version.split(".")[:2]), "train": "stable",
        "template": "azext_edge/edge/providers/orchestration/template"
        + ("_fairfax" if cloud == "fairfax" else "") + ".py",
    }


@pytest.mark.parametrize("track,expected", [("ga", "1.0.1"), ("preview", "1.2.0b1")])
def test_select_published_track_without_drafts(monitor, mocker, track, expected):
    mocker.patch.object(monitor, "tag_commit", return_value=SOURCE)
    values = [
        release("1.0.0"), release("1.1.0b1", preview=True), release("9.0.0", draft=True),
        release("1.0.1"), release("1.2.0b1", preview=True),
    ]
    result = monitor.resolve("azure-iot", "public", track, AUTOMATION, values)
    assert result["release"]["version"] == expected
    assert result["testSourceCommit"] == SOURCE


def test_distinct_milestones_use_latest_cli_patch_and_cloud_profile(monitor, mocker):
    versions = {"2.11.1": "1.5.45", "2.11.0": "1.5.41", "2.10.0": "1.4.112", "2.9.0": "1.4.73", "2.7.0": "1.3.137"}
    commits = {f"v{version}": f"{index:040x}" for index, version in enumerate(versions, 1)}
    by_commit = {commits[f"v{version}"]: runtime for version, runtime in versions.items()}
    mocker.patch.object(monitor, "tag_commit", side_effect=lambda _, tag: commits[tag])
    mocker.patch.object(
        monitor, "runtime_profile",
        side_effect=lambda _, source, cloud: profile("1.5.46" if cloud == "fairfax" else by_commit[source], cloud),
    )
    releases = [release(version, "azure-iot-ops") for version in versions]
    latest = monitor.resolve("azure-iot-ops", "fairfax", "1.5", AUTOMATION, releases)
    previous = monitor.resolve("azure-iot-ops", "public", "1.4", AUTOMATION, releases)
    oldest = monitor.resolve("azure-iot-ops", "public", "1.3", AUTOMATION, releases)
    assert latest["release"]["version"] == "2.11.1"
    assert latest["runtime"]["version"] == "1.5.46"
    assert previous["release"]["version"] == "2.10.0"
    assert oldest["release"]["version"] == "2.7.0"
    with pytest.raises(ValueError, match="latest three"):
        monitor.resolve("azure-iot-ops", "public", "1.2", AUTOMATION, releases)


def test_missing_fairfax_profile_stays_blocked_and_mooncake_is_rejected(monitor, mocker):
    values = [release(version, "azure-iot-ops") for version in ("2.11.1", "2.10.0", "2.7.0")]
    commits = {value["tag_name"]: f"{index:040x}" for index, value in enumerate(values, 1)}
    runtimes = dict(zip(commits.values(), ("1.5.45", "1.4.112", "1.3.137")))
    mocker.patch.object(monitor, "tag_commit", side_effect=lambda _, tag: commits[tag])
    mocker.patch.object(
        monitor, "runtime_profile",
        side_effect=lambda _, source, cloud: None if cloud == "fairfax" else profile(runtimes[source]),
    )
    result = monitor.resolve("azure-iot-ops", "fairfax", "1.4", AUTOMATION, values)
    assert result["runtime"] is None
    assert result["blockers"]
    monitor.validate_manifest(result)
    with pytest.raises(ValueError, match="not supported"):
        monitor.resolve("azure-iot-ops", "mooncake", "1.5", AUTOMATION, values)


def test_runtime_metadata_is_parsed_without_executing_release_code(monitor):
    source = (
        "raise RuntimeError('release code must not execute')\n"
        "blueprint = {'VERSIONS': {'iotOperations': '1.5.45'}, 'TRAINS': {'iotOperations': 'stable'}}\n"
    )
    assert monitor.parse_runtime_profile(source, "public") == profile("1.5.45")
    with pytest.raises(ValueError, match="stable bundled"):
        monitor.parse_runtime_profile(source.replace("'stable'", "'integration'"), "public")


def test_retry_retains_selection_and_rejects_missing_or_changed_history(monitor, manifest, tmp_path, mocker):
    monitor.write_json(tmp_path / "release-selection-1/manifest.json", manifest)
    discovery = mocker.patch.object(monitor, "resolve")
    assert monitor.frozen_manifest(tmp_path, "azure-iot", "public", "ga", AUTOMATION, 2) == manifest
    discovery.assert_not_called()
    with pytest.raises(ValueError, match="cannot rediscover"):
        monitor.frozen_manifest(tmp_path / "missing", "azure-iot", "public", "ga", AUTOMATION, 2)
    changed = deepcopy(manifest)
    changed["release"]["id"] = 456
    monitor.write_json(tmp_path / "release-selection-2/manifest.json", changed)
    with pytest.raises(ValueError, match="changed between attempts"):
        monitor.frozen_manifest(tmp_path, "azure-iot", "public", "ga", AUTOMATION, 3)


@pytest.mark.parametrize("url", [
    "http://github.com/Azure/release.whl", "https://github.com.evil.example/release.whl",
    "https://user:password@github.com/Azure/release.whl", "file:///tmp/release.whl",
])
def test_download_url_boundary(monitor, url):
    with pytest.raises(ValueError, match="approved"):
        monitor.validate_url(url)


def test_asset_requires_published_digest_and_expected_repository(monitor):
    asset = release("1.0.0")
    asset["assets"][0]["digest"] = None
    with pytest.raises(ValueError, match="missing its GitHub SHA256"):
        monitor.wheel_asset(asset, "azure-iot", "1.0.0")
    asset = release("1.0.0")
    asset["assets"][0]["browser_download_url"] = "https://github.com/other/repository/release.whl"
    with pytest.raises(ValueError, match="selected release"):
        monitor.wheel_asset(asset, "azure-iot", "1.0.0")


@pytest.fixture
def bundle(monitor, manifest, tmp_path):
    path = tmp_path / manifest["wheel"]["name"]
    package = "VERSION = '1.0.0'\n"
    with ZipFile(path, "w") as archive:
        archive.writestr("azext_iot/__init__.py", package)
        archive.writestr("azure_iot-1.0.0.dist-info/METADATA", "Name: azure-iot\nVersion: 1.0.0\n")
    manifest["wheel"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = tmp_path / "source/azext_iot"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(package.encode("utf-8"))
    (source / "tests").mkdir()
    (source / "tests/test_case_int.py").write_text("def test_case():\n    assert True\n", encoding="utf-8")
    monitor.write_json(tmp_path / "source.json", {
        "commit": SOURCE, "files": monitor.source_files(tmp_path / "source"),
    })
    manifest["sourceSha256"] = hashlib.sha256((tmp_path / "source.json").read_bytes()).hexdigest()
    monitor.write_json(tmp_path / "manifest.json", manifest)
    return tmp_path, manifest


def test_bundle_verification_survives_artifact_git_exclusion_and_rejects_changed_tests(monitor, bundle):
    directory, manifest = bundle
    assert monitor.verify_bundle(directory) == manifest
    (directory / "source/azext_iot/tests/test_case_int.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="test source"):
        monitor.verify_bundle(directory)


def test_bundle_rejects_tampered_wheel_and_wrong_target(monitor, bundle):
    directory, manifest = bundle
    with pytest.raises(ValueError, match="requested cloudKey"):
        monitor.verify_bundle(directory, cloud="fairfax")
    wheel = directory / manifest["wheel"]["name"]
    wheel.write_bytes(wheel.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        monitor.verify_bundle(directory)


def test_definition_binding_rejects_scope_overrides(monitor, monkeypatch):
    config = monitor.read_json(ROOT / ".azure-devops/release-monitors.json")
    item = monitor.configurations(config)[0]
    monkeypatch.setenv("BUILD_DEFINITIONNAME", item["name"])
    monkeypatch.setenv("BUILD_REPOSITORY_NAME", monitor.REPOSITORIES[config["extension"]])
    for key, value in item["variables"].items():
        monkeypatch.setenv(key.upper(), value)
    monitor.check_definition(config, config["extension"], "public", config["tracks"][0])
    monkeypatch.setenv("MONITORRESOURCEGROUP", "another-resource-group")
    with pytest.raises(ValueError, match="reviewed monitor configuration"):
        monitor.check_definition(config, config["extension"], "public", config["tracks"][0])


def test_definition_generation_cannot_enable_runs_or_copy_secrets(monitor):
    config = monitor.read_json(ROOT / ".azure-devops/release-monitors.json")
    repository = monitor.REPOSITORIES[config["extension"]]
    baseline = {
        "queue": {"id": 1},
        "repository": {
            "id": repository, "name": repository, "type": "GitHub", "url": f"https://github.com/{repository}",
            "properties": {"connectedServiceId": "github-connection", "unrelated": "do-not-copy"},
        },
        "variables": {"Secret": {"isSecret": True, "value": "do-not-copy"}},
        "triggers": [{"triggerType": "schedule"}],
    }
    definitions = monitor.definitions(config, baseline, "refs/heads/monitor-test")
    assert len(definitions) == 6
    for item in definitions:
        assert item["queueStatus"] == "disabled" and item["triggers"] == []
        assert "Secret" not in item["variables"]
        assert item["repository"]["properties"] == {"connectedServiceId": "github-connection"}
        assert all(not value["allowOverride"] for value in item["variables"].values())
    with pytest.raises(ValueError, match="GitHub definition"):
        monitor.definitions(config, baseline, "refs/heads/../other")


def test_staging_preserves_released_cases_manifests_and_product(monitor, bundle, mocker, monkeypatch, tmp_path):
    import sys

    directory, manifest = bundle
    monkeypatch.setitem(sys.modules, "release_monitor", monitor)
    spec = importlib.util.spec_from_file_location("monitor_adapter_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    automation = tmp_path / "automation"
    helpers = automation / "azext_iot/tests"
    helpers.mkdir(parents=True)
    (helpers / "_ado_pipeline.py").write_text("current protocol", encoding="utf-8")
    (helpers / "_phase_manifest.py").write_text("different release", encoding="utf-8")
    (helpers / "test_case_int.py").write_text("different assertions", encoding="utf-8")
    (automation / "tox.ini").write_text("current controller setup", encoding="utf-8")
    released_manifest = directory / "source/azext_iot/tests/_phase_manifest.py"
    released_manifest.write_text("released selection", encoding="utf-8")
    monkeypatch.setattr(adapter, "ROOT", automation)
    mocker.patch.object(adapter, "verify_bundle", return_value=manifest)
    monkeypatch.setenv("BUILD_SOURCEVERSION", AUTOMATION)
    monkeypatch.setenv("MONITOR_CLOUD", "public")
    monkeypatch.setenv("MONITOR_TRACK", "ga")
    destination = tmp_path / "stage"
    adapter.stage(directory, destination)
    assert not (destination / "candidate").exists()
    for relative in (
        "azext_iot/__init__.py", "azext_iot/tests/test_case_int.py", "azext_iot/tests/_phase_manifest.py",
    ):
        assert (destination / relative).read_bytes() == (directory / "source" / relative).read_bytes()
    assert (destination / "azext_iot/tests/_ado_pipeline.py").read_text() == "current protocol"
    with pytest.raises(ValueError, match="fresh"):
        adapter.stage(directory, destination)
