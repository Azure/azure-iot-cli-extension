# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import requests

from azext_iot.tests import _owned_resources as owned

ROOT = Path(__file__).resolve().parents[2]

SUBSCRIPTION = "11111111-2222-4333-8444-555555555555"
GROUP = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/shared"
RESOURCE = GROUP + "/providers/microsoft.storage/storageaccounts/teststore"


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "ownership.json"
    owned.create_context(
        path, product="azure-iot", cloud="AzureCloud", subscription=SUBSCRIPTION,
        resourceGroup="shared", producer={"build": "42"}, scenario="edge", attempt=1,
        wheel="a" * 64, locations={"clusterRegion": "westus2"},
    )
    return owned.Journal(path)


@pytest.fixture
def http_arm(journal):
    arm = owned.Arm.__new__(owned.Arm)
    arm.journal, arm.deadline = journal, None
    arm.endpoint = arm.audience = "https://management.azure.com"
    arm.profile = Mock()
    arm.profile.get_raw_token.return_value = (("Bearer", "unit-token", {}), SUBSCRIPTION, "tenant")
    arm.session = Mock()
    return arm


def test_root_intent_precedes_creation_and_retains_user_tag_shape(journal):
    arm = Mock()
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    body = {"location": "westus2"}
    headers = observer.prepare_root(RESOURCE, "2023-05-01", body, "PUT")
    assert headers == {"If-None-Match": "*"}
    assert body["tags"] == {owned.TAG: journal.owner}
    assert journal.records()[RESOURCE]["tagShape"] == "null"
    assert observer.visible({"id": RESOURCE, **body})["tags"] is None

    arm.verify.return_value = {"id": RESOURCE, **body}
    update = {"tags": {"user-tag": "value"}}
    observer.prepare_root(RESOURCE, "2023-05-01", update, "PATCH")
    assert observer.visible({"id": RESOURCE, **update})["tags"] == {"user-tag": "value"}
    observer.prepare_root(RESOURCE, "2023-05-01", {"tags": {}}, "PATCH")
    assert observer.visible({"id": RESOURCE, "tags": {owned.TAG: journal.owner}})["tags"] == {}


def test_foreign_resource_is_rejected_without_recording_ownership(journal):
    arm = Mock()
    arm.verify.side_effect = ValueError("foreign owner")
    observer = owned.Observer(journal, arm)
    with pytest.raises(ValueError, match="foreign owner"):
        observer.prepare_root(RESOURCE, "2023-05-01", {"location": "westus2"}, "PUT")
    assert journal.records() == {}


def test_parallel_journal_writers_never_publish_partial_records(journal):
    resources = [RESOURCE + str(index) for index in range(80)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(journal.record, resource, "2023-05-01", kind="root") for resource in resources]
        while not all(future.done() for future in futures):
            assert set(journal.records()) <= set(resources)
        for future in futures:
            future.result()
    assert set(journal.records()) == set(resources)


@pytest.mark.skipif(os.name != "posix", reason="Native live-test agents require Linux.")
def test_parallel_launcher_publication_runs_the_current_cli(journal, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", os.environ["PATH"])
    monkeypatch.setenv(owned.ENV, "")
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path / "azure-config"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: owned.activate(journal.path), range(16)))
    assert all(result.owner == journal.owner for result in results)
    result = subprocess.run(
        ["az", "version", "--output", "json"], check=True, capture_output=True, text=True, timeout=60,
    )
    from azure.cli.core import __version__
    assert json.loads(result.stdout)["azure-cli-core"] == __version__


@pytest.mark.skipif(os.name != "posix", reason="Native live-test agents require Linux.")
def test_real_xdist_collection_and_runtime_names_are_isolated(journal, tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_names.py").write_text(
        "import random\nimport pytest\n"
        "from azext_iot.tests.generators import generate_generic_id\n"
        "@pytest.mark.parametrize('name', range(10))\n"
        "def test_names(name):\n"
        "    random.seed(123)\n"
        "    first = generate_generic_id()\n"
        "    random.seed(123)\n"
        "    second = generate_generic_id()\n"
        "    assert first != second\n"
        "    assert len(first) == len(second) == 32\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "azext_iot.tests._ado_ownership_plugin",
         "-c", str(tmp_path / "pytest.ini"), "--confcutdir", str(tmp_path), str(tmp_path / "test_names.py")],
        capture_output=True, text=True, timeout=90, check=False,
        env=dict(os.environ, **{
            owned.ENV: str(journal.path), "AZURE_CONFIG_DIR": str(tmp_path / "azure-config"),
            "PYTHONPATH": os.pathsep.join((str(ROOT), os.environ.get("PYTHONPATH", ""))),
        }),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "10 passed" in result.stdout


@pytest.mark.parametrize("confirmed", [False, True])
def test_missing_delete_requires_previous_confirmed_ownership(journal, confirmed):
    journal.record(RESOURCE, "2023-05-01", kind="root", confirmed=confirmed, etag="previous-etag")
    arm = Mock()
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    if confirmed:
        assert observer.prepare_root(RESOURCE, "2023-05-01", {}, "DELETE") == {"If-Match": "previous-etag"}
    else:
        with pytest.raises(ValueError, match="existing owned resource"):
            observer.prepare_root(RESOURCE, "2023-05-01", {}, "DELETE")


@pytest.mark.parametrize("operation", ["Merge", "Replace"])
def test_generic_tag_update_preserves_owner(journal, operation):
    arm = Mock()
    arm.api_for.return_value = "2023-05-01"
    arm.verify.return_value = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    observer = owned.Observer(journal, arm)
    body = {"operation": operation, "properties": {"tags": {"user-tag": "value"}}}
    observer.prepare_tags(RESOURCE + "/providers/microsoft.resources/tags/default", body, "PATCH")
    assert body["properties"]["tags"] == {owned.TAG: journal.owner, "user-tag": "value"}


def test_generic_tag_delete_cannot_remove_owner(journal):
    arm = Mock()
    arm.verify.return_value = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    observer = owned.Observer(journal, arm)
    body = {"operation": "Delete", "properties": {"tags": {owned.TAG: journal.owner}}}
    with pytest.raises(ValueError, match="ownership"):
        observer.prepare_tags(RESOURCE + "/providers/microsoft.resources/tags/default", body, "PATCH")


@pytest.mark.parametrize("resource", [
    GROUP, GROUP + "/providers", GROUP.replace("shared", "foreign") + "/providers/Microsoft.Storage/storageAccounts/a",
    GROUP + "/providers/Microsoft.Storage/storageAccounts/../foreign",
])
def test_group_and_foreign_resource_mutations_never_reach_transport(journal, resource):
    arm = Mock(endpoint="https://management.azure.com")
    observer = owned.Observer(journal, arm)
    original_send = requests.Session.send
    observer.install()
    try:
        observer.original_send = Mock(side_effect=AssertionError("transport must not run"))
        with pytest.raises(ValueError):
            requests.Session().delete("https://management.azure.com" + resource + "?api-version=2023-05-01")
        observer.original_send.assert_not_called()
    finally:
        observer.original_send = original_send
        observer.uninstall()


@pytest.mark.parametrize("endpoint", [
    "https://management.azure.com", "https://centraluseuap.management.azure.com",
    "https://management.usgovcloudapi.net",
])
def test_prepared_mutation_serializes_owner_and_normalizes_the_response(journal, endpoint):
    arm = Mock(endpoint="https://management.azure.com")
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    original_send = requests.Session.send

    def transport(_session, request, **_kwargs):
        body = json.loads(request.body)
        assert body["tags"] == {owned.TAG: journal.owner, "user-tag": "value"}
        assert request.headers["If-None-Match"] == "*"
        assert int(request.headers["Content-Length"]) == len(request.body)
        response = requests.Response()
        response.status_code = 201
        response._content = json.dumps({"id": RESOURCE, **body}).encode()
        return response

    observer.install()
    try:
        observer.original_send = Mock(side_effect=transport)
        url = endpoint + RESOURCE + "?api-version=2023-05-01"
        if endpoint.endswith("usgovcloudapi.net"):
            with pytest.raises(ValueError, match="another Azure cloud"):
                requests.Session().put(url, json={"location": "westus2", "tags": {"user-tag": "value"}})
            observer.original_send.assert_not_called()
            assert journal.records() == {}
        else:
            response = requests.Session().put(url, json={"location": "westus2", "tags": {"user-tag": "value"}})
            assert response.json()["tags"] == {"user-tag": "value"}
            assert int(response.headers["Content-Length"]) == len(response.content)
            record = journal.records()[RESOURCE]
            assert record["confirmed"] is True
            assert list(record["creates"].values()) == [201]
            observer.original_send.assert_called_once()
    finally:
        observer.original_send = original_send
        observer.uninstall()


def test_expected_negative_test_cannot_hide_ownership_violation(journal, monkeypatch):
    arm = Mock(endpoint="https://management.azure.com")
    observer = owned.Observer(journal, arm)
    observer.install()
    try:
        with pytest.raises(ValueError):
            requests.Session().delete("https://management.azure.com" + GROUP + "?api-version=2021-04-01")
    finally:
        observer.uninstall()
    arm.pages.side_effect = [[], [], []]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    with pytest.raises(RuntimeError, match="cannot qualify"):
        owned.cleanup(journal.path)
    arm.request.assert_not_called()


def test_role_assignment_ownership_survives_without_mutating_the_fixed_group(journal):
    resource = GROUP + "/providers/Microsoft.Authorization/roleAssignments/role"
    body = {"properties": {"principalId": "principal", "description": "test grant"}}
    arm = Mock()
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    observer.prepare_root(resource.lower(), "2022-04-01", body, "PUT")
    assert journal.owns({"id": resource, **body})
    assert observer.visible(body)["properties"]["description"] == "test grant"
    assert not journal.owns({"id": resource, "properties": {"description": "another run"}})


def test_deployment_checks_resolved_parents_even_when_children_come_first(journal):
    resource = GROUP + "/providers/Microsoft.Resources/deployments/test-deployment"
    instance = GROUP + "/providers/microsoft.iotoperations/instances/owned-instance"
    arm = Mock(endpoint="https://management.azure.com")
    arm.request.side_effect = [
        (404, None, {}),
        (200, {"status": "Succeeded", "properties": {"changes": [
            {"resourceId": instance + "/brokers/default", "changeType": "Create"},
            {"resourceId": instance, "changeType": "Create"},
            {"resourceId": RESOURCE + "foreign", "changeType": "Ignore"},
        ]}}, {}),
    ]
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    body = {"properties": {"mode": "Incremental", "template": {"resources": {
        "instance": {"type": "Microsoft.IoTOperations/instances", "apiVersion": "2026-07-01",
                     "name": "owned-instance", "location": "westus2"},
        "broker": {"type": "Microsoft.IoTOperations/instances/brokers", "apiVersion": "2026-07-01",
                   "name": "owned-instance/default"},
    }}}}
    observer.prepare_deployment(resource.lower(), "2022-09-01", body)
    assert body["properties"]["parameters"][owned.PARAMETER]["value"] == journal.owner
    assert body["properties"]["template"]["resources"]["instance"]["tags"][owned.TAG] == journal.owner
    assert set(journal.records()) == {instance, resource.lower()}
    assert [call.args[0] for call in arm.verify.call_args_list] == [instance]


def test_real_cli_template_policy_is_guarded_before_deployment_transport(journal):
    from azure.cli.command_modules.resource.custom import JsonCTemplatePolicy
    from azure.core.pipeline import PipelineContext, PipelineRequest
    from azure.core.pipeline.transport import HttpRequest

    template = {"resources": [
        {"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-05-01",
         "name": "teststore", "location": "westus2", "tags": {"note": "literal template: stays unchanged"}},
    ]}
    deployment = GROUP + "/providers/microsoft.resources/deployments/policy"
    url = "https://management.azure.com" + deployment + "?api-version=2022-09-01"
    http = HttpRequest("PUT", url)
    http.set_json_body({"properties": {"mode": "Incremental", "template": json.dumps(template)}})
    JsonCTemplatePolicy().on_request(PipelineRequest(http, PipelineContext(None)))
    with pytest.raises(json.JSONDecodeError):
        json.loads(http.data)
    arm = Mock(endpoint="https://management.azure.com")
    arm.verify.return_value = None
    arm.request.side_effect = [(404, None, {}), (200, {"status": "Succeeded", "properties": {"changes": [
        {"resourceId": RESOURCE, "changeType": "Create"},
    ]}}, {})]
    observer = owned.Observer(journal, arm)
    original_send = requests.Session.send
    response = requests.Response()
    response.status_code = 201
    response._content = b"{}"
    observer.install()
    try:
        observer.original_send = Mock(return_value=response)
        requests.Session().send(requests.Request("PUT", url, data=http.data).prepare())
        sent = observer.original_send.call_args.args[1]
        body = json.loads(sent.body)
        resource = body["properties"]["template"]["resources"][0]
        assert resource["tags"] == {owned.TAG: journal.owner, "note": "literal template: stays unchanged"}
        assert body["properties"]["parameters"][owned.PARAMETER]["value"] == journal.owner
        assert int(sent.headers["Content-Length"]) == len(sent.body)
        assert set(journal.records()) == {RESOURCE, deployment}
    finally:
        observer.original_send = original_send
        observer.uninstall()


@pytest.mark.parametrize("body", [
    '{properties: {"template": {}}}',
    '{"properties": {"template": {unquoted: "value"}}}',
    '{"properties": {"template": {"text": "template:"}, template: {}}}',
])
def test_cli_envelope_support_does_not_accept_other_unquoted_keys(body):
    with pytest.raises(ValueError):
        owned.request_body(body)


def test_cleanup_deletes_exact_owned_resources_and_preserves_other_attempts(journal, monkeypatch):
    other = RESOURCE + "other"
    own_resource = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    foreign = {"id": other, "tags": {owned.TAG: "another-attempt"}}
    arm = Mock()
    inherited = {"id": f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/roleAssignments/role"}
    unusual = {"id": GROUP + "/providers/Microsoft.Insights/actionGroups/Application Insights Smart Detection"}
    arm.pages.side_effect = [[own_resource, foreign, unusual], [inherited], []]
    arm.api_for.return_value = "2023-05-01"
    arm.verify.return_value = own_resource
    arm.request.side_effect = [(202, None, {}), (404, None, {})]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    owned.cleanup(journal.path)
    deletes = [call.args[1] for call in arm.request.call_args_list if call.args[0] == "DELETE"]
    assert deletes == [RESOURCE]
    assert journal.records()[RESOURCE]["cleanup"] == "absent"
    assert other not in journal.records()


def test_journal_preserves_independent_fields_and_does_not_repeat_confirmations(journal):
    journal.record(RESOURCE, "2023-05-01", confirmed=True, tagShape="null")
    journal.record(RESOURCE, "2023-05-01", etag="new-etag", confirmed=False)
    record = journal.records()[RESOURCE]
    assert record["confirmed"] is True
    assert record["tagShape"] == "null"
    assert record["etag"] == "new-etag"
    count = len(list(journal.directory.glob("*.json")))
    for _ in range(10):
        journal.record(RESOURCE, "2023-05-01", confirmed=True, etag="new-etag")
    assert len(list(journal.directory.glob("*.json"))) == count


@pytest.mark.parametrize("template", [False, True])
@pytest.mark.parametrize("status", [None, 202])
def test_recreation_cannot_inherit_an_older_incarnations_confirmation(journal, monkeypatch, template, status):
    journal.record(RESOURCE, "2023-05-01", kind="root", confirmed=True)
    arm = Mock(endpoint="https://management.azure.com", deadline=100)
    arm.verify.return_value = None
    observer = owned.Observer(journal, arm)
    if template:
        arm.request.side_effect = [
            (404, None, {}),
            (200, {"status": "Succeeded", "properties": {"changes": [
                {"resourceId": RESOURCE, "changeType": "Create"},
            ]}}, {}),
        ]
        observer.prepare_deployment(
            GROUP + "/providers/microsoft.resources/deployments/recreate", "2022-09-01",
            {"properties": {"mode": "Incremental", "template": {"resources": [
                {"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-05-01",
                 "name": "teststore", "location": "westus2"},
            ]}}}, creation_id="new",
        )
    else:
        observer.prepare_root(RESOURCE, "2023-05-01", {"location": "westus2"}, "PUT", creation_id="new")
    journal.record(RESOURCE, "2023-05-01", creates={"new": status})
    monkeypatch.setattr(owned.time, "monotonic", lambda: 0)
    assert owned.cleanup_submit(journal, arm, RESOURCE, journal.records()[RESOURCE]) == "creation"

    journal.record(RESOURCE, "2023-05-01", confirmed=True)
    assert owned.cleanup_submit(journal, arm, RESOURCE, journal.records()[RESOURCE]) is None


@pytest.mark.parametrize("state", ["Succeeded", "Failed", "Canceled"])
@pytest.mark.parametrize("appeared", [False, True])
def test_terminal_deployment_resolves_missing_roots_only_after_a_fresh_read(journal, monkeypatch, state, appeared):
    deployment = GROUP + "/providers/microsoft.resources/deployments/finished"
    journal.record(
        RESOURCE, "2023-05-01", kind="root", creates={"new": 201},
        deployments={"new": {"id": deployment, "api": "2022-09-01"}},
    )
    root = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    arm = Mock(deadline=100)
    arm.verify.side_effect = [None, {"properties": {"provisioningState": state}}, root if appeared else None]
    monkeypatch.setattr(owned.time, "monotonic", lambda: 0)
    result = owned.cleanup_submit(journal, arm, RESOURCE, journal.records()[RESOURCE])
    assert [call.args[0] for call in arm.verify.call_args_list] == [RESOURCE, deployment, RESOURCE]
    if appeared:
        assert result == "deletion"
        arm.request.assert_called_once_with("DELETE", RESOURCE, "2023-05-01", headers=None)
    else:
        assert result is None
        assert journal.records()[RESOURCE]["cleanup"] == "absent"
        arm.request.assert_not_called()


@pytest.mark.parametrize("kind,code,absent", [
    ("Microsoft.Authorization/roleAssignments", "RoleAssignmentNotFound", True),
    ("Microsoft.Resources/deployments", "DeploymentNotFound", True),
    ("Microsoft.Storage/storageAccounts", "ResourceNotFound", True),
    ("Microsoft.Storage/storageAccounts", "RoleAssignmentNotFound", False),
    ("Microsoft.Authorization/roleAssignments", "RoleAssignmentDoesNotExist", False),
    ("Microsoft.Authorization/roleAssignments", "NoRegisteredProviderFound", False),
])
def test_arm_absence_requires_resource_specific_not_found_code(http_arm, kind, code, absent):
    response = requests.Response()
    response.status_code = 404
    response._content = json.dumps({"error": {"code": code}}).encode()
    http_arm.session.request.return_value = response
    if absent:
        assert http_arm.request("GET", GROUP + "/providers/" + kind + "/missing", "2022-04-01")[0] == 404
    else:
        with pytest.raises(RuntimeError, match="did not prove"):
            http_arm.request("GET", GROUP + "/providers/" + kind + "/missing", "2022-04-01")


@pytest.mark.parametrize("method,delay", [("GET", "2"), ("GET", "1000"), ("DELETE", "2")])
def test_reads_retry_throttling_within_budget_but_deletes_do_not(http_arm, monkeypatch, method, delay):
    throttled, succeeded = requests.Response(), requests.Response()
    throttled.status_code = 429
    throttled.headers["Retry-After"] = delay
    succeeded.status_code = 200
    succeeded._content = b"{}"
    http_arm.session.request.side_effect = [throttled, succeeded]
    clock = [0]
    monkeypatch.setattr(owned.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(owned.time, "sleep", lambda wait: clock.__setitem__(0, clock[0] + wait))
    if delay == "1000":
        with pytest.raises(TimeoutError, match="bounded read budget"):
            http_arm.request(method, RESOURCE, "2023-05-01")
        assert http_arm.session.request.call_count == 1
    elif method == "DELETE":
        with pytest.raises(RuntimeError, match="HTTP 429"):
            http_arm.request(method, RESOURCE, "2023-05-01")
        assert http_arm.session.request.call_count == 1
    else:
        assert http_arm.request(method, RESOURCE, "2023-05-01")[0] == 200
        assert http_arm.session.request.call_count == 2
        assert clock[0] == 2


@pytest.mark.parametrize("prediction", [
    {"changes": []},
    {"properties": {"changes": [{"changeType": "Create"}]}},
    {"properties": {"changes": [{"changeType": "Unsupported", "resourceId": RESOURCE}]}},
])
def test_deployment_prediction_never_silently_ignores_unknown_changes(journal, prediction):
    with pytest.raises(ValueError):
        owned.Observer(journal, Mock()).deployment_targets(prediction)


def test_cleanup_waits_for_dependencies_before_deleting_roots(journal, monkeypatch):
    role = GROUP + "/providers/microsoft.authorization/roleassignments/grant"
    storage = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    grant = {"id": role, "properties": {"description": journal.role_prefix}}
    journal.record(RESOURCE, "2023-05-01", kind="root")
    journal.record(role, "2022-04-01", kind="role")
    arm = Mock()
    arm.pages.side_effect = [[storage], [grant], []]
    arm.verify.side_effect = [grant, storage]
    arm.request.side_effect = [(202, None, {}), (404, None, {}), (202, None, {}), (404, None, {})]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    owned.cleanup(journal.path)
    assert [call.args[:2] for call in arm.request.call_args_list] == [
        ("DELETE", role), ("GET", role), ("DELETE", RESOURCE), ("GET", RESOURCE),
    ]


def test_inventory_failure_still_attempts_journaled_cleanup(journal, monkeypatch):
    journal.record(RESOURCE, "2023-05-01", kind="root")
    arm = Mock()
    arm.pages.side_effect = [RuntimeError("inventory failed"), [], []]
    arm.verify.return_value = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    arm.request.side_effect = [(202, None, {}), (404, None, {})]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    with pytest.raises(RuntimeError, match="incomplete"):
        owned.cleanup(journal.path)
    assert arm.request.call_args_list[0].args[0] == "DELETE"
    assert journal.records()[RESOURCE]["cleanup"] == "absent"


@pytest.mark.parametrize("eventually_created", [False, True])
def test_unfinished_create_cannot_be_mistaken_for_completed_cleanup(journal, monkeypatch, eventually_created):
    journal.record(RESOURCE, "2023-05-01", kind="root", creates={"request": None})
    arm = Mock()
    arm.pages.side_effect = [[], [], []]
    if eventually_created:
        arm.verify.side_effect = [
            None, {"id": RESOURCE, "tags": {owned.TAG: journal.owner}, "properties": {"provisioningState": "Creating"}},
            {"id": RESOURCE, "tags": {owned.TAG: journal.owner}},
        ]
        arm.request.side_effect = [(202, None, {}), (404, None, {})]
    else:
        arm.verify.return_value = None
    clock = [0]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    monkeypatch.setattr(owned.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(owned.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    if eventually_created:
        owned.cleanup(journal.path, timeout=20)
        assert journal.records()[RESOURCE]["cleanup"] == "absent"
        assert [call.args[0] for call in arm.request.call_args_list] == ["DELETE", "GET"]
    else:
        with pytest.raises(RuntimeError, match="incomplete"):
            owned.cleanup(journal.path, timeout=20)
        assert journal.records()[RESOURCE]["cleanup"] == "failed"
        arm.request.assert_not_called()


def test_definitively_rejected_create_can_confirm_absence(journal, monkeypatch):
    journal.record(RESOURCE, "2023-05-01", kind="root", creates={"request": 400})
    arm = Mock()
    arm.pages.side_effect = [[], [], []]
    arm.verify.return_value = None
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    owned.cleanup(journal.path)
    assert journal.records()[RESOURCE]["cleanup"] == "absent"
    arm.request.assert_not_called()


def test_cleanup_ownership_failure_cannot_be_erased_by_later_absence(journal, monkeypatch):
    journal.record(RESOURCE, "2023-05-01", kind="root")
    arm = Mock()
    arm.pages.side_effect = [[], [], []]
    arm.verify.side_effect = ValueError("owner changed")
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    with pytest.raises(RuntimeError, match="incomplete"):
        owned.cleanup(journal.path)
    arm.request.assert_not_called()
    assert journal.records()[RESOURCE]["cleanup"] == "failed"


@pytest.mark.parametrize("stale_reads", [0, 2, 20])
def test_cleanup_waits_for_absence_with_a_bounded_budget(journal, monkeypatch, stale_reads):
    resource = {"id": RESOURCE, "tags": {owned.TAG: journal.owner}}
    journal.record(RESOURCE, "2023-05-01", kind="root")
    arm = Mock()
    arm.pages.side_effect = [[resource], [], []]
    arm.verify.return_value = resource
    arm.request.side_effect = [(202, None, {}), *([(200, resource, {})] * stale_reads), (404, None, {})]
    clock = [0]
    monkeypatch.setattr(owned, "Arm", Mock(return_value=arm))
    monkeypatch.setattr(owned.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(owned.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    if stale_reads == 20:
        with pytest.raises(RuntimeError, match="incomplete"):
            owned.cleanup(journal.path, timeout=15)
    else:
        owned.cleanup(journal.path, timeout=15)
        assert journal.records()[RESOURCE]["cleanup"] == "absent"
    assert clock[0] == min(stale_reads, 3) * 5
