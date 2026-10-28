# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import yaml

from azext_iot.tests import _integration_health as health


@pytest.fixture
def setup_health(monkeypatch):
    for name, value in {
        "BUILD_BUILDID": "123", "SYSTEM_DEFINITIONID": "170", "BUILD_SOURCEVERSION": "a" * 40,
        "BUILD_SOURCEBRANCH": "refs/heads/dev", "SYSTEM_JOBATTEMPT": "1",
    }.items():
        monkeypatch.setenv(name, value)
    profile = {"region": "eastus", "pythonVersions": ["3.13"], "services": ["DPS"]}
    config = {"schema": 1, "branches": {"refs/heads/dev": {"sat": profile}}}
    build = {"id": 123, "definition": {"id": 170}, "sourceVersion": "a" * 40,
             "sourceBranch": "refs/heads/dev", "queueTime": "2026-10-17T23:59:00Z"}
    monkeypatch.setenv("VALIDATION_PROFILES", json.dumps(config))
    monkeypatch.setattr(health, "ado_get", Mock(return_value=build))
    return config, build


def test_profile_uses_queued_utc_day_and_pins_source(setup_health, tmp_path):
    config, build = setup_health
    build["queueTime"] = "2026-10-18T01:59:00+02:00"
    chosen = health.choose(config, build, health.identity())
    assert chosen["day"] == "sat"
    health.plan(tmp_path / "output", tmp_path / "history")
    value = json.loads((tmp_path / "output/plan.json").read_text())
    assert value == [{"service": "DPS", "python": "3.13", "region": "eastus",
                      "endpoint": "https://management.azure.com", "minutes": 100}]


def test_canary_profile_pins_endpoint_in_plan_and_job_matrix(setup_health, tmp_path, monkeypatch, capsys):
    config, _ = setup_health
    config["branches"]["refs/heads/dev"]["sat"].update(region="centraluseuap", armEndpoint="canary")
    monkeypatch.setenv("VALIDATION_PROFILES", json.dumps(config))
    health.plan(tmp_path / "output", tmp_path / "history")
    expected_endpoint = "https://centraluseuap.management.azure.com"
    jobs = json.loads((tmp_path / "output/plan.json").read_text())
    assert jobs[0]["region"] == "centraluseuap" and jobs[0]["endpoint"] == expected_endpoint
    matrix = json.loads(capsys.readouterr().out.splitlines()[0].split("]", 1)[1])
    assert matrix == {"py313_centraluseuap": {
        "python": "3.13", "region": "centraluseuap", "endpoint": expected_endpoint,
    }}


@pytest.mark.parametrize("field,value", [
    ("sourceVersion", "b" * 40), ("sourceBranch", "refs/heads/preview"),
    ("queueTime", "2026-10-17T20:00:00"), ("id", 124), ("definition", {"id": 999}),
])
def test_profile_rejects_wrong_source_and_ambiguous_time(setup_health, field, value):
    config, build = setup_health
    build[field] = value
    with pytest.raises(ValueError):
        health.choose(config, build, health.identity())


@pytest.mark.parametrize("field,value", [
    ("region", "centraluseuap"), ("region", "eastus;echo x"), ("services", []),
    ("services", ["DPS", "DPS"]), ("services", ["Unknown"]), ("pythonVersions", ["3.9"]),
    ("pythonVersions", "3.13"), ("command", "anything"), ("armEndpoint", "canary"),
    ("armEndpoint", "https://unapproved.invalid"), ("armEndpoint", "unknown"), ("armEndpoint", []),
])
def test_profile_rejects_invalid_selections(setup_health, field, value):
    config, _ = setup_health
    profile = deepcopy(config["branches"]["refs/heads/dev"]["sat"])
    profile[field] = value
    with pytest.raises(ValueError):
        health.validate(profile)


def test_missing_day_and_branch_do_not_fall_back(setup_health):
    config, build = setup_health
    config["branches"]["refs/heads/dev"] = {"mon": {}}
    with pytest.raises(ValueError, match="No valid profile"):
        health.choose(config, build, health.identity())
    config["branches"] = {}
    with pytest.raises(ValueError, match="No valid profile"):
        health.choose(config, build, health.identity())


def test_rerun_uses_original_profile_not_library_changes(setup_health, tmp_path, monkeypatch):
    directory = tmp_path / "integration-plan-1"
    health.plan(directory, tmp_path / "empty")
    monkeypatch.setenv("SYSTEM_JOBATTEMPT", "2")
    monkeypatch.setenv("VALIDATION_PROFILES", "invalid replacement")
    lookup = Mock(side_effect=AssertionError("A retry must not resolve another profile."))
    monkeypatch.setattr(health, "ado_get", lookup)
    value = health.resolve(tmp_path)
    assert value["profile"]["region"] == "eastus"
    lookup.assert_not_called()
    value["producer"]["build"] = "999"
    (directory / "health-profile.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="history"):
        health.resolve(tmp_path)


@pytest.mark.parametrize("definition", [
    {"id": 147, "name": "manual"}, {"id": 170, "name": "Azure IoT CLI - Integration Health"},
])
def test_admission_checks_both_pipeline_definitions(setup_health, monkeypatch, definition):
    monkeypatch.setattr(health, "ado_get", Mock(return_value={"value": [{"id": 999, "definition": definition}]}))
    with pytest.raises(ValueError, match="Another IoT"):
        health.admission()


def test_cleanup_window_and_unrelated_runs(setup_health, monkeypatch):
    monkeypatch.setattr(health, "ado_get", Mock(return_value={
        "value": [{"id": 999, "definition": {"id": 164, "name": "ops"}}],
    }))
    health.admission(datetime(2026, 10, 17, 20, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="13:00"):
        health.admission(datetime(2026, 10, 17, 10, tzinfo=timezone.utc))
    health.admission(datetime(2026, 10, 17, 10, tzinfo=timezone.utc), check_cleanup=False)


def test_health_entrypoint_always_executes_shared_live_pipeline():
    root = health.ROOT
    entry = yaml.safe_load((root / ".azure-devops/integration-health.yml").read_text())
    assert entry["trigger"] == entry["pr"] == "none" and "schedules" not in entry
    assert entry["extends"] == {
        "template": "templates/integration-pipeline.yml", "parameters": {"health": True, "mode": "Integration tests"},
    }
    template = yaml.safe_load((root / ".azure-devops/templates/integration-pipeline.yml").read_text())
    assert {"${{ if parameters.health }}": [{"group": "iot-cli-integration-health"}]} in template["variables"]
    stage = yaml.safe_load((root / ".azure-devops/templates/integration-service.yml").read_text())["stages"][0]
    assert "Plan.health.${{ parameters.service }}" in stage["${{ if parameters.health }}"]["condition"]
    assert stage["jobs"][0]["strategy"]["${{ if parameters.health }}"]["matrix"].endswith("['health.matrix'] ]")
