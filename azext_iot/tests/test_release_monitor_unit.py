# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = "a" * 40
SOURCE = "b" * 40


@pytest.fixture
def monitor(monkeypatch):
    monkeypatch.setenv("TESTPYTHONS", "3.13")
    monkeypatch.setenv("TESTMODE", "Integration tests")
    monkeypatch.setenv("MONITOR_PYTHONS", "3.13")
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


def test_health_plan_forwards_python_and_region_selections(monitor, mocker, monkeypatch, tmp_path):
    mocker.patch.dict("sys.modules", {"release_monitor": monitor})
    spec = importlib.util.spec_from_file_location("monitor_plan_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    mocker.patch.object(adapter, "stage")
    plan = mocker.Mock(return_value=[])
    mocker.patch.object(adapter.runpy, "run_path", return_value={"plan": plan})
    for key, value in {
        "MONITOR_SERVICES": "DPS,HubControl", "MONITOR_PYTHONS": "3.10,3.13",
        "MONITOR_REGION": "westus2,eastus", "MONITOR_ENDPOINT": "public",
    }.items():
        monkeypatch.setenv(key, value)
    adapter.plan(tmp_path, tmp_path / "source")
    plan.assert_called_once_with(["DPS", "HubControl"], ["3.10", "3.13"], ["westus2", "eastus"], "public")


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
    with pytest.raises(ValueError, match="matching published release"):
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
    monitor.check_definition(config, config["extension"], "public", item["variables"]["MonitorTrack"])
    monkeypatch.setenv("MONITORRESOURCEGROUP", "another-resource-group")
    with pytest.raises(ValueError, match="reviewed monitor configuration"):
        monitor.check_definition(config, config["extension"], "public", item["variables"]["MonitorTrack"])


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
        pipeline = yaml.safe_load((ROOT / item["process"]["yamlFilename"]).read_text(encoding="utf-8"))
        parameters = {parameter["name"]: parameter for parameter in pipeline["parameters"]}
        common = yaml.safe_load((ROOT / ".azure-devops/integration_tests.yml").read_text())["parameters"]
        assert list(parameters) == [p["name"] for p in common] + ["sourceBranch"]
        for expected in common:
            actual = parameters[expected["name"]]
            assert {k: v for k, v in actual.items() if k != "default"} == {
                k: v for k, v in expected.items() if k != "default"
            }
        track = item["variables"]["MonitorTrack"]["value"]
        assert parameters["cloud"]["default"] == item["variables"]["MonitorCloud"]["value"].capitalize()
        profile = next(value for value in pipeline["variables"] if "template" in value)
        assert profile["parameters"]["version"] == track
        assert profile["parameters"]["region"] == "${{ join(',', parameters.regions) }}"
        assert parameters["regions"]["default"] == ["Australia East"]
        assert parameters["services"]["default"] == item["variables"]["MonitorServices"]["value"].split(",")
        assert parameters["sourceBranch"]["default"] == {
            "ga": "dev", "preview": "release/1.2.0-preview",
        }[track]
        assert pipeline["stages"] == [{
            "template": "templates/release-monitor-stages.yml",
            "parameters": {
                **{name: "${{ parameters." + name + " }}" for name in ("mode", "sourceBranch")},
                "regions": "${{ variables.TestRegion }}",
                "pythonVersions": "${{ join(' ', parameters.pythonVersions) }}",
            },
        }]
    with pytest.raises(ValueError, match="GitHub definition"):
        monitor.definitions(config, baseline, "refs/heads/../other")


def test_health_stages_plan_or_execute_the_selected_cohorts():
    template = yaml.safe_load(
        (ROOT / ".azure-devops/templates/release-monitor-stages.yml").read_text(encoding="utf-8")
    )
    assert next(item for item in template["parameters"] if item["name"] == "pythonVersions")["type"] == "string"
    live = template["stages"][1]["${{ if eq(parameters.mode, 'Integration tests') }}"]
    stages = {stage["stage"]: stage for stage in [template["stages"][0], *live] if "stage" in stage}
    assert set(stages) == {"Prepare", "Build", "Lint", "Unit", "Results"}
    steps = stages["Prepare"]["jobs"][0]["steps"]
    assert any("release_monitor_adapter.py plan" in step.get("bash", "") for step in steps)
    assert stages["Results"]["dependsOn"] == [
        "Prepare", "Build", "Lint", "Unit", "DPS", "HubControl", "HubData", "ADU", "ADR",
    ]
    cohorts = next(stage for stage in live if "stage" not in stage)
    assert next(iter(cohorts.values()))[0]["template"] == "integration-service.yml"
    assert "runIntegration" not in str(template)
    assert "qualify-profile" not in str(template)


@pytest.mark.parametrize("source_only", [False, True])
@pytest.mark.parametrize("cloud", ["public", "fairfax"])
def test_staging_preserves_released_cases_manifests_and_product(
        monitor, bundle, mocker, monkeypatch, tmp_path, source_only, cloud):
    import sys

    directory, manifest = bundle
    manifest = {**manifest, "cloud": "AzureUSGovernment" if cloud == "fairfax" else "AzureCloud"}
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
    (automation / "tox.ini").write_text("DPS: python -m pytest -vv --timeout=900 tests\n", encoding="utf-8")
    (directory / "source/azext_iot/tests/ci_budgets.json").write_bytes(
        (ROOT / "azext_iot/tests/ci_budgets.json").read_bytes()
    )
    released_manifest = directory / "source/azext_iot/tests/_phase_manifest.py"
    released_manifest.write_text("released selection", encoding="utf-8")
    monkeypatch.setattr(adapter, "ROOT", automation)
    mocker.patch.object(adapter, "verify_bundle", return_value=manifest)
    monkeypatch.setenv("BUILD_SOURCEVERSION", AUTOMATION)
    monkeypatch.setenv("MONITOR_CLOUD", cloud)
    monkeypatch.setenv("MONITOR_TRACK", "ga")
    destination = tmp_path / "stage"
    compatibility = mocker.spy(adapter, "adapt_harness")
    adapter.stage(directory, destination, source_only=source_only)
    assert not (destination / "candidate").exists()
    for relative in (
        "azext_iot/__init__.py", "azext_iot/tests/test_case_int.py", "azext_iot/tests/_phase_manifest.py",
    ):
        assert (destination / relative).read_bytes() == (directory / "source" / relative).read_bytes()
    assert (destination / "azext_iot/tests/_ado_pipeline.py").read_text() == "current protocol"
    staged = monitor.read_json(destination / "release-monitor.json")
    if source_only:
        compatibility.assert_not_called()
        assert "testCompatibility" not in staged
    else:
        compatibility.assert_called_once()
        assert staged["testCompatibility"]["sourceCommit"] == manifest["testSourceCommit"]
        assert staged["testCompatibility"]["automationCommit"] == AUTOMATION
        if cloud == "fairfax":
            assert {item["path"] for item in staged["testCompatibility"]["files"]} == {
                "tox.ini", "azext_iot/tests/ci_budgets.json",
            }
            assert "--timeout=2100" in (destination / "tox.ini").read_text()
        else:
            assert staged["testCompatibility"]["files"] == []
    if source_only or cloud == "public":
        assert "--timeout=900" in (destination / "tox.ini").read_text()
        assert (destination / "azext_iot/tests/ci_budgets.json").read_bytes() == (
            directory / "source/azext_iot/tests/ci_budgets.json"
        ).read_bytes()
    with pytest.raises(ValueError, match="fresh"):
        adapter.stage(directory, destination)


def test_diagnostic_deadlines_include_fixture_setup_and_preserve_cleanup(monitor, mocker, tmp_path):
    mocker.patch.dict("sys.modules", {"release_monitor": monitor})
    spec = importlib.util.spec_from_file_location("monitor_budgets_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    for relative in ("tox.ini", "azext_iot/tests/ci_budgets.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    original = json.loads((tmp_path / "azext_iot/tests/ci_budgets.json").read_text())
    changes = adapter.diagnostic_budgets(tmp_path)
    staged = json.loads((tmp_path / "azext_iot/tests/ci_budgets.json").read_text())
    timeout = int(next(
        line for line in (tmp_path / "tox.ini").read_text().splitlines() if "DPS: python -m pytest" in line
    ).split("--timeout=")[1].split()[0])
    assert timeout > 900 + 2 * 300 + 300  # Hub auth, two role-visibility windows, DPS auth.
    for phase in staged["DPS"]["phases"]:
        assert phase["runtime_minutes"] * 60 > timeout
    budget = staged["DPS"]
    total = max(p["runtime_minutes"] + p["cleanup_minutes"] for p in budget["phases"])
    total += sum(p["cleanup_minutes"] for p in budget["phases"]) + budget["reserve_minutes"] + budget["setup_minutes"]
    assert total <= budget["job_timeout_minutes"]
    for before, after in zip(original["DPS"]["phases"], staged["DPS"]["phases"]):
        assert after["runtime_minutes"] > before["runtime_minutes"]
        after["runtime_minutes"] = before["runtime_minutes"]
    assert staged == original
    assert len(changes) == 2 and all(item["originalSha256"] != item["adaptedSha256"] for item in changes)
    with pytest.raises(ValueError, match="Unexpected DPS pytest timeout"):
        adapter.diagnostic_budgets(tmp_path)


@pytest.mark.parametrize("relative", ["azext_iot/tests/dps/conftest.py", "azext_iot/tests/iothub/_sas_phase.py"])
def test_harness_compatibility_records_only_allowlisted_function_changes(monitor, mocker, monkeypatch, tmp_path, relative):
    mocker.patch.dict("sys.modules", {"release_monitor": monitor})
    spec = importlib.util.spec_from_file_location("monitor_harness_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    monkeypatch.setattr(adapter, "ROOT", tmp_path / "automation")
    output = tmp_path / "stage"
    source, donor = output / relative, adapter.ROOT / relative
    source.parent.mkdir(parents=True)
    donor.parent.mkdir(parents=True)
    header = '# Frozen header\n"""Frozen module."""\nfrom __future__ import annotations\n\n'
    methods = []
    symbols = adapter.COMPATIBILITY[relative]["symbols"] + adapter.COMPATIBILITY[relative].get("helpers", ())
    for symbol in symbols:
        prefix, name = ("    ", symbol.split(".")[1]) if "." in symbol else ("", symbol)
        methods.append(f"{prefix}def {name}(value):\n{prefix}    return 'original'\n\n")
    strict = "def test_required_assertion():\n    assert 1 == 2\n"
    original = header + ("class HubSasPhase:\n" if "iothub" in relative else "") + "".join(methods) + strict
    source.write_text(original, encoding="utf-8")
    donor.write_text(original.replace("'original'", "'adapted'").replace("assert 1 == 2", "assert True"), encoding="utf-8")
    result = adapter.adapt_harness(output, {"testSourceCommit": SOURCE, "automationCommit": AUTOMATION})
    changed = source.read_text(encoding="utf-8")
    assert changed.startswith(header)
    assert strict in changed and "assert True" not in changed
    assert "'original'" not in changed and "'adapted'" in changed
    change, = result["files"]
    assert change["originalSha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert change["adaptedSha256"] == hashlib.sha256(changed.encode()).hexdigest()
    assert change["symbols"] == list(symbols)
    assert adapter.adapt_harness(output, {"testSourceCommit": SOURCE, "automationCommit": AUTOMATION})["files"] == []


def test_harness_includes_missing_dps_authorization_helper(monitor, mocker, tmp_path):
    mocker.patch.dict("sys.modules", {"release_monitor": monitor})
    spec = importlib.util.spec_from_file_location("monitor_helper_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    relative = "azext_iot/tests/dps/conftest.py"
    original = (ROOT / relative).read_text()
    tree = ast.parse(original)
    helper = adapter.function(tree, "_dps_authorization_failed_response")
    lines = original.splitlines(keepends=True)
    del lines[helper.lineno - 1:helper.end_lineno]
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("".join(lines))
    result = adapter.adapt_harness(tmp_path, {"testSourceCommit": SOURCE, "automationCommit": AUTOMATION})
    staged = ast.parse(source.read_text())
    added = adapter.function(staged, "_dps_authorization_failed_response")
    assert ast.dump(added) == ast.dump(helper)
    namespace = {}
    exec(compile(ast.Module(body=[added], type_ignores=[]), str(source), "exec"), namespace)
    assert namespace["_dps_authorization_failed_response"](mocker.Mock(json=lambda: {
        "errorCode": 401002, "message": "Authorization failed for the request",
    }))
    assert "_dps_authorization_failed_response" in result["files"][0]["symbols"]
    assert adapter.adapt_harness(tmp_path, {"testSourceCommit": SOURCE, "automationCommit": AUTOMATION})["files"] == []


@pytest.mark.parametrize("replacement", ["def renamed(value):\n    pass\n", "def _readiness_http_error():\n    pass\n"])
def test_harness_compatibility_rejects_missing_or_changed_functions(monitor, mocker, monkeypatch, tmp_path, replacement):
    mocker.patch.dict("sys.modules", {"release_monitor": monitor})
    spec = importlib.util.spec_from_file_location("monitor_harness_rejection_unit", ROOT / "scripts/release_monitor_adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    monkeypatch.setattr(adapter, "ROOT", tmp_path / "automation")
    relative = "azext_iot/tests/dps/conftest.py"
    source, donor = tmp_path / "stage" / relative, adapter.ROOT / relative
    source.parent.mkdir(parents=True)
    donor.parent.mkdir(parents=True)
    source.write_text("def _readiness_http_error(value):\n    pass\n", encoding="utf-8")
    donor.write_text(replacement, encoding="utf-8")
    with pytest.raises(ValueError, match="adapter"):
        adapter.adapt_harness(tmp_path / "stage", {"testSourceCommit": SOURCE, "automationCommit": AUTOMATION})
    assert source.read_text() == "def _readiness_http_error(value):\n    pass\n"


@pytest.fixture
def source_manifest(monitor):
    return {
        **monitor.settings("azure-iot"), "schema": 2, "kind": "source", "cloudKey": "public", "cloud": "AzureCloud",
        "track": "ga", "slot": "ga", "automationCommit": AUTOMATION, "testSourceCommit": SOURCE,
        "source": {"branch": "refs/heads/dev", "commit": SOURCE, "version": "1.0.0"},
        "wheel": None, "runtime": None, "blockers": [], "releaseQualified": False,
    }


def test_source_selection_freezes_branch_and_retries_without_rediscovery(monitor, source_manifest, tmp_path):
    monitor.write_json(tmp_path / "source-selection-1/manifest.json", source_manifest)
    assert monitor.frozen_source_manifest(tmp_path, "public", "ga", "dev", AUTOMATION, 2) == source_manifest
    with pytest.raises(ValueError, match="identity changed"):
        monitor.frozen_source_manifest(tmp_path, "public", "ga", "preview", AUTOMATION, 2)
    with pytest.raises(ValueError, match="without its frozen"):
        monitor.frozen_source_manifest(tmp_path / "missing", "public", "preview", "preview", AUTOMATION, 2)
    source_manifest["track"] = source_manifest["slot"] = "preview"
    source_manifest["source"]["branch"] = "refs/heads/users/release-next"
    monitor.write_json(tmp_path / "source-selection-1/manifest.json", source_manifest)
    assert monitor.frozen_source_manifest(
        tmp_path, "public", "preview", "users/release-next", AUTOMATION, 2,
    ) == source_manifest
    with pytest.raises(ValueError, match="identity changed"):
        monitor.frozen_source_manifest(tmp_path, "public", "preview", "users/other", AUTOMATION, 2)


@pytest.mark.parametrize("override", [None, "region", "services", "cloud", "version", "branch"])
def test_health_overrides_preserve_selection_and_retry_identity(
        monitor, source_manifest, monkeypatch, override):
    config = monitor.read_json(ROOT / ".azure-devops/release-monitors.json")
    manifest = source_manifest
    if override == "cloud":
        manifest.update(cloudKey="fairfax", cloud="AzureUSGovernment")
    if override == "version":
        manifest.update(track="preview", slot="preview")
        manifest["source"]["branch"] = "refs/heads/release/1.2.0-preview"
    if override == "branch":
        manifest["source"]["branch"] = "refs/heads/users/test"
    selected = next(item["variables"] for item in monitor.configurations(config)
                    if item["variables"]["MonitorCloud"] == manifest["cloudKey"]
                    and item["variables"]["MonitorTrack"] == manifest["slot"])
    monkeypatch.setenv("MONITORCLOUD", "public")
    monkeypatch.setenv("MONITORTRACK", "ga")
    for key, value in selected.items():
        monkeypatch.setenv("TEST" + key.removeprefix("Monitor").upper(), value)
    if override == "region":
        monkeypatch.setenv("TESTREGION", "westus2")
    if override == "services":
        monkeypatch.setenv("TESTSERVICES", "DPS")
    monitor.bind_profile(manifest, config)
    if override:
        assert monitor.run_title(manifest, "123").endswith("-manual")
    monkeypatch.setenv("TESTREGION", "eastus")
    with pytest.raises(ValueError, match="changed between attempts"):
        monitor.bind_profile(manifest, config)
    monkeypatch.setenv("TESTAZURESERVICECONNECTION", "unreviewed-connection")
    with pytest.raises(ValueError, match="reviewed cloud profile"):
        monitor.bind_profile(manifest, config)


@pytest.mark.parametrize("track,branch", [
    ("ga", "dev"),
    ("preview", "release/1.2.0-preview"),
    ("preview", "users/release-next"),
])
def test_source_selection_resolves_exact_branch_commit_and_literal_version(monitor, mocker, track, branch):
    git = monitor.subprocess.run
    version = "1.0.0" if track == "ga" else "1.2.0b1"

    def run(arguments, **kwargs):
        if arguments[1] == "ls-remote":
            assert arguments[-1] == f"refs/heads/{branch}"
            return mocker.Mock(stdout=f"{SOURCE}\trefs/heads/{branch}\n")
        return git(arguments, **kwargs)

    mocker.patch.object(monitor.subprocess, "run", side_effect=run)
    download = mocker.patch.object(monitor, "download", return_value=f"VERSION = '{version}'\n".encode())
    manifest = monitor.frozen_source_manifest(None, "fairfax", track, branch, AUTOMATION, 1)
    assert manifest["source"] == {
        "branch": f"refs/heads/{branch}", "commit": SOURCE, "version": version,
    }
    assert manifest["wheel"] is None
    download.assert_called_once_with(
        f"https://raw.githubusercontent.com/Azure/azure-iot-cli-extension/{SOURCE}/azext_iot/constants.py",
    )
    assert monitor.run_title(manifest, "123") == f"iot-health-fairfax-{track}-cli{version}-srcbbbbbbbbbbbb-b123"


def test_source_build_preserves_frozen_source_and_binds_wheel(monitor, source_manifest, bundle, mocker):
    directory, released = bundle
    wheel = directory / released["wheel"]["name"]
    wheel_bytes = wheel.read_bytes()
    wheel.unlink()
    source_manifest["sourceSha256"] = released["sourceSha256"]
    monitor.write_json(directory / "manifest.json", source_manifest)
    before = monitor.source_files(directory / "source")
    assert monitor.verify_bundle(directory, require_wheel=False) == source_manifest
    with pytest.raises(ValueError, match="has not produced"):
        monitor.verify_bundle(directory)
    git = monitor.subprocess.run

    def run(arguments, **kwargs):
        if "-m" in arguments and "build" in arguments:
            assert kwargs["cwd"] != directory / "source"
            wheel.write_bytes(wheel_bytes)
            (kwargs["cwd"] / "generated.txt").write_text("build output", encoding="utf-8")
            return mocker.Mock(returncode=0)
        return git(arguments, **kwargs)

    mocker.patch.object(monitor.subprocess, "run", side_effect=run)
    monitor.build_source(directory)
    built = monitor.verify_bundle(directory)
    assert built["source"] == source_manifest["source"]
    assert built["wheel"]["sha256"] == hashlib.sha256(wheel_bytes).hexdigest()
    assert monitor.source_files(directory / "source") == before
    assert built["releaseQualified"] is False
    with pytest.raises(ValueError, match="unbuilt"):
        monitor.build_source(directory)
