# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import time
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
import requests
import yaml


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 10, 22, tzinfo=timezone.utc)
FINISHED = (NOW - timedelta(hours=8)).isoformat()
JOB = "11111111-2222-4333-8444-555555555555"
TIMELINE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@pytest.fixture
def cleanup():
    spec = importlib.util.spec_from_file_location("test_resource_cleanup", ROOT / "scripts/cleanup_test_resources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["azure-iot", "azure-iot-ops"])
def evidence(cleanup, request):
    product = request.param
    profile = json.loads((ROOT / ".azure-devops/cleanup-profiles.json").read_text())[
        "iot-public" if product == "azure-iot" else "aio-public"
    ]
    build = {
        "id": 42, "definition": {"id": profile["definitions"][0]}, "sourceVersion": "a" * 40,
        "repository": {"id": profile["repository"], "type": "GitHub"}, "sourceBranch": "refs/heads/approved",
        "status": "completed", "reason": "manual", "finishTime": FINISHED,
    }
    scope = {"product": product, "cloud": profile["cloud"], "subscription": profile["subscription"],
             "resourceGroup": profile["groups"][0], "attempt": 1}
    producer = {"build": "42", "commit": "a" * 40}
    if product == "azure-iot":
        scope.update(endpoint="https://management.azure.com", identity={
            **producer, "definition": str(build["definition"]["id"]), "service": "ADR", "python": "3.13",
            "region": "australiaeast", "subscription": profile["subscription"],
            "resource_group": profile["groups"][0], "endpoint": "https://management.azure.com",
        })
        name, final, filename = "ownership-ADR-3.13-australiaeast-1", "attempt-ADR-3.13-australiaeast-1", "manifest.json"
    else:
        scope.update(producer={**producer, "pipeline": str(build["definition"]["id"])}, scenario="stable-python-edge")
        name, final, filename = "ops-manifest-stable-python-edge-1", "ops-attempt-stable-python-edge-1", "state.json"
    context = cleanup.OWNED["new_context"](**scope)
    artifact = {"name": name, "source": JOB, "resource": {"type": "PipelineArtifact"}}
    final_artifact = {**artifact, "name": final}
    timeline = {"records": [
        {"id": JOB, "type": "Job", "state": "completed", "result": "failed", "attempt": 1, "finishTime": FINISHED},
        {"id": "final", "parentId": JOB, "type": "Task", "name": "Finalize Job", "state": "completed",
         "result": "succeeded", "attempt": 1, "finishTime": FINISHED},
    ]}
    ado = Mock(deadline=time.monotonic() + 300)
    ado.json.side_effect = lambda path: deepcopy(build if path == "/builds/42" else timeline)
    return {"profile": profile, "build": build, "context": context, "artifact": artifact,
            "final_artifact": final_artifact, "timeline": timeline, "ado": ado, "filename": filename}


def archive(files):
    stream = BytesIO()
    with ZipFile(stream, "w") as result:
        for name, value in files.items():
            result.writestr(name, json.dumps(value))
    return ZipFile(BytesIO(stream.getvalue()))


def check(cleanup, evidence):
    cleanup.eligible(evidence["ado"], 42, evidence["artifact"], evidence["context"], evidence["profile"], NOW)


def test_finished_original_job_is_eligible_even_when_tests_failed(cleanup, evidence):
    check(cleanup, evidence)


@pytest.mark.parametrize("state", ["inProgress", "cancelling", "notStarted", None])
def test_active_or_unknown_producer_never_inherits_parent_completion(cleanup, evidence, state):
    evidence["build"]["status"] = state
    evidence["build"]["triggeredByBuild"] = {"id": 41, "status": "completed"}
    with pytest.raises(cleanup.Deferred, match="completion is unproven"):
        check(cleanup, evidence)


def test_missing_status_is_not_treated_as_finished(cleanup, evidence):
    evidence["ado"].json.side_effect = RuntimeError("ADO read failed with HTTP 403")
    with pytest.raises(RuntimeError, match="403"):
        check(cleanup, evidence)


@pytest.mark.parametrize("change", ["unfinished-job", "lost-agent", "canceled-finalizer", "young", "wrong-source"])
def test_finalization_and_grace_are_required(cleanup, evidence, change):
    records = evidence["timeline"]["records"]
    if change == "unfinished-job":
        records.append({"id": "other", "type": "Job", "state": "inProgress"})
    elif change == "lost-agent":
        records.pop()
    elif change == "canceled-finalizer":
        records[-1]["result"] = "canceled"
    elif change == "young":
        records[-1]["finishTime"] = (NOW - timedelta(hours=1)).isoformat()
    else:
        evidence["artifact"]["source"] = "different-job"
    with pytest.raises(cleanup.Deferred):
        check(cleanup, evidence)


def test_old_attempt_requires_its_own_finalized_timeline(cleanup, evidence):
    previous = deepcopy(evidence["timeline"])
    current = evidence["timeline"]
    current["records"][0].update(attempt=2, previousAttempts=[
        {"attempt": 1, "timelineId": TIMELINE, "recordId": JOB},
    ])
    current["records"][1]["attempt"] = 2
    evidence["ado"].json.side_effect = lambda path: deepcopy({
        "/builds/42": evidence["build"], "/builds/42/timeline": current,
        f"/builds/42/timeline/{TIMELINE}": previous,
    }[path])
    check(cleanup, evidence)
    previous["records"].pop()
    with pytest.raises(cleanup.Deferred, match="finalization"):
        check(cleanup, evidence)


@pytest.mark.parametrize("change", ["commit", "definition", "repository", "pull-request", "scope", "artifact", "digest"])
def test_cross_origin_or_scope_manifest_cannot_authorize_deletion(cleanup, evidence, change):
    if change == "commit":
        evidence["build"]["sourceVersion"] = "b" * 40
    elif change == "definition":
        evidence["build"]["definition"]["id"] = 165
    elif change == "repository":
        evidence["build"]["repository"]["id"] = "someone/fork"
    elif change == "pull-request":
        evidence["build"]["reason"] = "pullRequest"
    elif change == "scope":
        evidence["profile"]["groups"] = ["other-group"]
    elif change == "artifact":
        evidence["artifact"]["name"] += "-other"
    else:
        evidence["context"]["owner"] = "b" * 64
    with pytest.raises(ValueError):
        check(cleanup, evidence)


def test_recovery_imports_only_matching_context_events(cleanup, evidence, tmp_path):
    context = evidence["context"]
    group = f"/subscriptions/{context['subscription']}/resourceGroups/{context['resourceGroup']}"
    resource = group.lower() + "/providers/microsoft.storage/storageaccounts/owned"
    event = {"owner": context["owner"], "id": resource, "api": "2023-05-01",
             "timeNs": 123, "creates": {"pending": 202}}
    with archive({
        "phase/ownership.json": context,
        "phase/ownership.events/00000000000000000123-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json": event,
        "../outside.json": {"never": "extract"},
        "foreign/ownership.json": {"owner": "other"},
        "foreign/ownership.events/ignored.json": {},
    }) as source:
        journal = cleanup.recover(source, context, tmp_path / "evidence")
    assert cleanup.OWNED["pending_creates"](journal.records()[resource]) == {"pending"}
    assert not (tmp_path / "outside.json").exists()
    with archive({"state.json": {"ownership": {**context, "owner": "changed"}}}) as source:
        with pytest.raises(cleanup.Deferred, match="original ownership"):
            cleanup.recover(source, context, tmp_path / "other")


@pytest.fixture
def owned(cleanup, evidence, tmp_path):
    path = tmp_path / "ownership.json"
    cleanup.OWNED["write_new"](path, evidence["context"])
    journal = cleanup.OWNED["Journal"](path)
    resource = journal.group + "/providers/microsoft.storage/storageaccounts/owned"
    value = {"id": resource, "name": "owned", "etag": "original", "tags": {"cliTestOwner": journal.owner}}
    arm = Mock()
    arm.api_for.return_value = "2023-05-01"
    arm.verify.return_value = value
    return journal, resource, value, arm


def test_unresolved_create_404_is_preserved(cleanup, owned):
    journal, resource, _, arm = owned
    journal.record(resource, "2023-05-01", creates={"pending": 202})
    arm.verify.return_value = None
    with pytest.raises(cleanup.Deferred, match="unresolved creation"):
        cleanup.snapshot(journal, arm, {}, set())
    arm.request.assert_not_called()


@pytest.mark.parametrize("state", ["Accepted", "Creating", "Deleting"])
def test_pending_azure_operations_are_report_only(cleanup, owned, state):
    journal, resource, value, arm = owned
    value["properties"] = {"provisioningState": state}
    with pytest.raises(cleanup.Deferred, match="still pending"):
        cleanup.snapshot(journal, arm, {resource: value}, set())


def test_protection_covers_journal_only_resources_and_parent_cascades(cleanup, owned):
    journal, resource, value, arm = owned
    journal.record(resource, "2023-05-01", confirmed=True)
    for exclusions in ({resource}, {"owned"}, {resource + "/blobservices/default/containers/protected"}):
        with pytest.raises(cleanup.Deferred, match="protected"):
            cleanup.snapshot(journal, arm, {}, exclusions)
    foreign = {**value, "id": resource + "/providers/other/children/foreign", "tags": {"cliTestOwner": "b" * 64}}
    with pytest.raises(cleanup.Deferred, match="another owner"):
        cleanup.snapshot(journal, arm, {resource: value, foreign["id"]: foreign}, set())


def test_delete_guard_rechecks_live_status_etag_and_budget(cleanup, owned, mocker):
    _, resource, value, _ = owned
    base = cleanup.GuardedArm.__bases__[0]
    request = mocker.patch.object(base, "request", return_value=(202, None, {}))
    mocker.patch.object(cleanup.time, "sleep")
    arm = cleanup.GuardedArm.__new__(cleanup.GuardedArm)
    arm.authorize = Mock()
    arm.approved = {resource: value}
    arm.budget = {"remaining": 1}
    with pytest.raises(cleanup.Deferred, match="changed"):
        arm.request("DELETE", resource, "2023-05-01", headers={"If-Match": "changed"})
    arm.authorize.side_effect = cleanup.Deferred("Producer rerun is active")
    with pytest.raises(cleanup.Deferred, match="rerun"):
        arm.request("DELETE", resource, "2023-05-01", headers={"If-Match": "original"})
    request.assert_not_called()
    arm.authorize.side_effect = None
    arm.request("DELETE", resource, "2023-05-01", headers={"If-Match": "original"})
    assert request.call_count == 1
    with pytest.raises(cleanup.Deferred, match="budget"):
        arm.request("DELETE", resource, "2023-05-01", headers={"If-Match": "original"})
    with pytest.raises(ValueError, match="only reads"):
        arm.request("PUT", resource, "2023-05-01")


def test_report_classifies_without_invoking_cleanup(cleanup, evidence, owned, tmp_path, mocker):
    mocker.patch.object(cleanup, "datetime", wraps=datetime).now.return_value = NOW
    journal, resource, value, arm = owned
    ado = evidence["ado"]
    ado.builds.return_value = [evidence["build"]]
    ado.json.side_effect = lambda path: deepcopy(
        {"value": [evidence["artifact"], evidence["final_artifact"]]} if path.endswith("/artifacts")
        else evidence["build"] if path == "/builds/42" else evidence["timeline"]
    )
    initial = evidence["context"] if evidence["filename"] == "manifest.json" else {"ownership": evidence["context"]}
    ado.archive.side_effect = lambda _, item: archive(
        {evidence["filename"]: initial} if item["name"] == evidence["artifact"]["name"]
        else {"phase/ownership.json": evidence["context"]}
    )
    mocker.patch.object(cleanup.subprocess, "check_output", return_value=json.dumps({
        "id": evidence["profile"]["subscription"], "environmentName": evidence["profile"]["cloud"],
    }))
    mocker.patch.object(cleanup, "inventory", return_value={resource: value})
    mocker.patch.dict(cleanup.OWNED, {"Arm": Mock(return_value=arm)})
    deleted = Mock()
    mocker.patch.dict(cleanup.OWNED, {"cleanup": deleted})
    result = cleanup.run(evidence["profile"], "report", 0, tmp_path / "report", set(), ado=ado)
    assert result["owners"][0]["status"] == "eligible"
    assert result["resources"][0]["status"] == "eligible"
    assert (tmp_path / "report/evidence" / journal.owner / "original.json").exists()
    deleted.assert_not_called()


def test_unknown_native_or_untagged_resources_never_trigger_deletion(cleanup, evidence, tmp_path, mocker):
    group = f"/subscriptions/{evidence['profile']['subscription']}/resourceGroups/{evidence['profile']['groups'][0]}"
    resource = group.lower() + "/providers/microsoft.devices/iothubs/test-hub-" + "a" * 32
    mocker.patch.object(cleanup.subprocess, "check_output", return_value=json.dumps({
        "id": evidence["profile"]["subscription"], "environmentName": evidence["profile"]["cloud"],
    }))
    mocker.patch.dict(cleanup.OWNED, {"Arm": Mock()})
    mocker.patch.object(cleanup, "inventory", return_value={
        resource: {"id": resource, "tags": {"intTest": "true", "runUid": "owned", "createdEpoch": "1"}},
    })
    result = cleanup.run(evidence["profile"], "delete", 0, tmp_path, set(), ado=evidence["ado"])
    assert result["resources"][0]["status"] == "unowned-or-native"
    evidence["ado"].builds.assert_not_called()


def test_permission_failure_is_reported_not_swallowed(cleanup, evidence, owned, tmp_path, mocker):
    _, resource, value, _ = owned
    mocker.patch.object(cleanup.subprocess, "check_output", return_value=json.dumps({
        "id": evidence["profile"]["subscription"], "environmentName": evidence["profile"]["cloud"],
    }))
    mocker.patch.dict(cleanup.OWNED, {"Arm": Mock()})
    mocker.patch.object(cleanup, "inventory", return_value={resource: value})
    evidence["ado"].builds.side_effect = RuntimeError("ADO read failed with HTTP 403")
    with pytest.raises(RuntimeError, match="incomplete"):
        cleanup.run(evidence["profile"], "delete", 0, tmp_path, set(), ado=evidence["ado"])
    assert "403" in json.loads((tmp_path / "report.json").read_text())["errors"][0]


def response(status, content=b"", **headers):
    value = Mock(status_code=status, headers=headers)
    value.iter_content.return_value = [content]
    value.__enter__ = Mock(return_value=value)
    value.__exit__ = Mock(return_value=False)
    return value


def test_artifact_auth_is_scoped_to_ado_gateway_not_blob_storage(cleanup):
    ado = cleanup.Ado("secret-test-token", time.monotonic() + 300)
    ado.session = Mock()
    ado.session.get.side_effect = [
        response(302, Location="https://artprodwus21.artifacts.visualstudio.com"
                 + cleanup.GATEWAY_PATH + "descriptor/content"),
        response(302, Location="https://artifacts.vsblob.vsassets.io/file?sig=private"),
        response(200, b"archive"),
    ]
    assert ado.get("/builds/42/artifacts", binary=True)[0] == b"archive"
    assert ado.session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer secret-test-token"
    assert ado.session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer secret-test-token"
    assert ado.session.get.call_args_list[2].kwargs["headers"] == {}
    for location in ("https://unapproved.example/file",
                     "https://artprodwus21.artifacts.visualstudio.com/other-project/file",
                     "https://artprodwus21.artifacts.visualstudio.com" + cleanup.GATEWAY_PATH + "%2e%2e/other"):
        ado.session.get.side_effect = [response(302, Location=location)]
        with pytest.raises(ValueError, match="Unexpected"):
            ado.get("/builds/42/artifacts", binary=True)


def test_transport_errors_do_not_expose_signed_download_urls(cleanup):
    ado = cleanup.Ado("test-token", time.monotonic() + 300)
    ado.session = Mock()
    ado.session.get.side_effect = requests.ConnectionError("https://storage/file?sig=private")
    with pytest.raises(RuntimeError, match="ConnectionError") as error:
        ado.get("/builds/42/artifacts", binary=True)
    assert "private" not in str(error.value)


def test_pipeline_is_report_first_daily_and_does_not_mask_scope_failures():
    pipeline = yaml.safe_load((ROOT / ".azure-devops/cleanup.yml").read_text())
    defaults = {item["name"]: item["default"] for item in pipeline["parameters"]}
    assert defaults["mode"] == "report"
    assert pipeline["schedules"][0]["cron"] == "0 13 * * *"
    job, = pipeline["jobs"]
    assert job["pool"] == {"vmImage": "ubuntu-24.04"}
    loop = next(step for step in job["steps"] if "${{ each profile in parameters.profiles }}" in step)
    task, = loop["${{ each profile in parameters.profiles }}"]
    assert task["condition"] == "succeededOrFailed()"
    assert "continueOnError" not in task
    assert job["steps"][-1]["condition"] == "always()"
