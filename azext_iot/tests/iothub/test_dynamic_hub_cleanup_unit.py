# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Real fixture finalization and ownership guards over an offline, in-memory transport."""

from copy import deepcopy
import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests

from azext_iot.tests import _focused_live, _hub_ownership as ownership, _hub_suite_manifest as manifest
from azext_iot.tests._hub_suite_plugin import PhaseReceipt
from azext_iot.tests.iothub import conftest as fixtures


UID = "c" * 32
NAME = "test-hub-" + "a" * 32
PREFIX = f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups/{ownership.GROUP}/providers/".casefold()
SHARED = PREFIX + "microsoft.devices/iothubs/" + NAME
OTHER = PREFIX + "microsoft.devices/iothubs/aziotclitest-hub-" + "b" * 18
COSMOS_NODE = (
    "azext_iot/tests/iothub/state/test_hub_state_int.py::"
    "test_export_cosmosdb_endpoint_resource_name_starting_with_scheme_char"
)
CONTEXT = ("SUITE", "PHASE", "RUN_ID", "OWNERSHIP", "RECEIPT")


def finish_cleanup(request):
    cleanup = fixtures._cleanup_dynamic_hub.__wrapped__(request)
    next(cleanup)
    next(cleanup)


@pytest.fixture
def owned_phase(tmp_path, monkeypatch, request):
    suite, phase, debug = getattr(request, "param", ("HubControl", "regular", True))
    expected = list(manifest.nodes(suite, phase))
    if debug:
        expected = [COSMOS_NODE if suite == "HubControl" else expected[0]]
    selection = _focused_live.select(suite, phase, expected) if debug else None
    runtime = PhaseReceipt(suite, phase, expected, tmp_path / "pytest.json", UID, debug=selection)
    resources = {}

    def read(method, resource_id, _api):
        assert method == "GET"
        return (200, deepcopy(resources[resource_id])) if resource_id in resources else (404, None)

    arm = SimpleNamespace(request=Mock(side_effect=read), inventory=Mock(return_value=[]), deadline=None)
    observer = ownership.Observer(tmp_path / "ownership.json", UID, phase, arm)
    runtime.observer = observer
    wire = Mock()

    def send(_session, prepared, **_kwargs):
        wire(prepared.method, prepared.url)
        assert prepared.method == "DELETE"
        target = urlsplit(prepared.url).path.casefold()
        durable = json.loads(observer.path.read_text(encoding="utf-8"))["resources"][target]
        assert durable["mutations"][-1]["method"] == "DELETE"
        assert durable["mutations"][-1]["status"] is None
        resources.pop(target, None)
        response = requests.Response()
        response.status_code = 204
        response._content = b""  # pylint: disable=protected-access
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    observer.install()
    original_send = observer.original_send
    for name, value in zip(CONTEXT, (suite, phase, UID, str(observer.path), str(runtime.path))):
        monkeypatch.setenv("AZEXT_IOT_HUB_" + name, value)
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    monkeypatch.setattr(fixtures, "ENTITY_NAME", NAME)
    monkeypatch.setattr(fixtures, "ENTITY_RG", ownership.GROUP)
    monkeypatch.setattr(fixtures, "iothub_settings", SimpleNamespace(env=SimpleNamespace(azext_iot_testhub=None)))
    monkeypatch.setattr(fixtures._sas_phase, "enabled", lambda: False)
    sleep = Mock(side_effect=AssertionError("Cleanup must not retry an ownership rejection"))
    monkeypatch.setattr(fixtures, "sleep", sleep)
    manager = SimpleNamespace(get_plugin=Mock(return_value=runtime))
    fixture_request = SimpleNamespace(
        config=SimpleNamespace(pluginmanager=manager),
        session=SimpleNamespace(items=[SimpleNamespace(nodeid=node) for node in expected]),
    )

    def invoke(command, **kwargs):
        assert command == f"iot hub delete --name {NAME} --resource-group {ownership.GROUP}"
        assert kwargs == {"capture_stderr": True}
        requests.Session().delete(ownership.ARM + SHARED, params={"api-version": "test"})
        return SimpleNamespace(success=lambda: True)

    invoke = Mock(side_effect=invoke)
    monkeypatch.setattr(fixtures.cli, "invoke", invoke)

    def create(resource_id=SHARED, status=201):
        body = {"location": ownership.REGION, "properties": {"disableLocalAuth": True}}
        observer.prepare("PUT", resource_id, "test", body)
        resources[resource_id] = {
            "id": resource_id, "tags": {ownership.OWNER_TAG: UID},
            "properties": {"provisioningState": "Succeeded"},
        }
        if status is not None:
            observer.complete(resource_id, status, resource=resources[resource_id] if status == 201 else None)

    try:
        yield SimpleNamespace(
            request=fixture_request, manager=manager, runtime=runtime, observer=observer, arm=arm,
            resources=resources, wire=wire, invoke=invoke, sleep=sleep, create=create,
        )
    finally:
        observer.original_send = original_send
        observer.restore()


@pytest.mark.parametrize("owned_phase", [
    ("HubControl", "regular", True), ("HubControl", "regular", False), ("HubData", "entra", True),
    ("HubData", "entra", False),
], indirect=True)
@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("other_fixture", [False, True])
def test_unused_shared_hub_never_reads_or_deletes_even_a_foreign_same_named_hub(
    owned_phase, caplog, foreign, other_fixture,
):
    fixture = owned_phase
    if other_fixture:
        fixture.create(OTHER)
    if foreign:
        fixture.resources[SHARED] = {"id": SHARED, "tags": {ownership.OWNER_TAG: "foreign-owner"}}
    before = deepcopy(fixture.observer.data)
    fixture.arm.request.reset_mock()
    fixture.arm.inventory.reset_mock()
    caplog.set_level(logging.INFO)
    with pytest.raises(StopIteration):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_not_called()
    fixture.wire.assert_not_called()
    fixture.arm.request.assert_not_called()
    fixture.arm.inventory.assert_not_called()
    assert fixture.observer.data == before
    assert json.loads(fixture.observer.path.read_text(encoding="utf-8")) == before
    assert "Skipping unused dynamically named hub" in caplog.text
    if foreign:
        assert fixture.resources[SHARED]["tags"][ownership.OWNER_TAG] == "foreign-owner"


@pytest.mark.parametrize("owned_phase", [
    ("HubControl", "regular", True), ("HubControl", "regular", False),
    ("HubData", "entra", True), ("HubData", "entra", False),
], indirect=True)
@pytest.mark.parametrize("status", [201, 202])
def test_used_shared_hub_keeps_verified_cleanup_and_acknowledgement_reconciliation(owned_phase, status):
    fixture = owned_phase
    fixture.create(status=status)
    fixture.arm.request.reset_mock()
    with pytest.raises(StopIteration):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_called_once()
    fixture.wire.assert_called_once()
    assert fixture.wire.call_args.args[0] == "DELETE"
    assert fixture.arm.request.call_count == (2 if status == 202 else 1)
    record = fixture.observer.data["resources"][SHARED]
    assert [mutation["method"] for mutation in record["mutations"]] == ["PUT", "DELETE"]
    assert record["mutations"][-1]["status"] == 204 and not record["uncertain"]
    assert not fixture.observer.data["violations"] and SHARED not in fixture.resources


@pytest.mark.parametrize("state", ["pre-create", "unknown-response", "failed-response"])
def test_uncertain_shared_hub_is_not_skipped_or_replayed(owned_phase, state):
    fixture = owned_phase
    fixture.create(status=500 if state == "failed-response" else None)
    if state == "pre-create":
        fixture.observer.data["resources"][SHARED]["mutations"] = []
        fixture.observer.save()
    before = deepcopy(fixture.observer.data["resources"])
    fixture.arm.request.reset_mock()
    with pytest.raises(ownership.OwnershipError, match="Uncertain mutation cannot be replayed"):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_called_once()
    fixture.wire.assert_not_called()
    fixture.sleep.assert_not_called()
    fixture.arm.request.assert_not_called()
    assert fixture.observer.data["resources"] == before
    assert fixture.observer.data["violations"] == ["Uncertain mutation cannot be replayed"]
    assert json.loads(fixture.observer.path.read_text(encoding="utf-8"))["resources"] == before


def test_an_unrelated_uncertain_root_does_not_authorize_shared_hub_cleanup(owned_phase):
    fixture = owned_phase
    fixture.create(OTHER, status=None)
    before = deepcopy(fixture.observer.data)
    fixture.arm.request.reset_mock()
    with pytest.raises(StopIteration):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_not_called()
    fixture.arm.request.assert_not_called()
    assert fixture.observer.data == before and before["resources"][OTHER]["uncertain"]


def test_previously_owned_hub_with_changed_owner_is_not_deleted_or_skipped(owned_phase):
    fixture = owned_phase
    fixture.create()
    fixture.resources[SHARED]["tags"][ownership.OWNER_TAG] = "foreign-owner"
    with pytest.raises(ownership.OwnershipError, match="no longer has this phase's ownership tag"):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_called_once()
    fixture.wire.assert_not_called()
    fixture.sleep.assert_not_called()
    assert fixture.resources[SHARED]["tags"][ownership.OWNER_TAG] == "foreign-owner"
    assert len(fixture.observer.data["resources"][SHARED]["mutations"]) == 1


def test_original_unowned_delete_remains_rejected_before_send(owned_phase):
    fixture = owned_phase
    with pytest.raises(ownership.OwnershipError, match="Mutation has no owned fixture root"):
        fixtures._delete_fixture_resource(
            f"iot hub delete --name {NAME} --resource-group {ownership.GROUP}", NAME,
        )
    fixture.wire.assert_not_called()
    fixture.arm.request.assert_not_called()
    before = deepcopy(fixture.observer.data)
    with pytest.raises(StopIteration):
        finish_cleanup(fixture.request)
    assert fixture.observer.data == before
    assert before["violations"] == ["Mutation has no owned fixture root"]


@pytest.mark.parametrize("defect", [
    "runtime-missing", "runtime-wrong-type", "observer-missing", "observer-wrong-type", "context-missing",
    "empty-context", "orphan-debug",
    "run-id", "suite", "phase", "owner-path", "receipt-path", "relative-path", "runtime-data",
    "runtime-schema", "runtime-run-id", "runtime-suite", "runtime-phase", "observer-data", "observer-schema",
    "observer-run-id", "observer-phase", "not-installed", "not-hooked", "restored", "resources", "violations",
    "record-type", "record-id", "record-owner", "record-before", "record-attempted", "record-api",
    "record-resolved", "record-uncertain", "record-mutations", "mutation-type", "mutation-id", "mutation-method",
    "noncanonical-key", "foreign-key", "entity-group", "entity-name",
])
def test_malformed_or_mismatched_runtime_cannot_authorize_skip_or_delete(owned_phase, monkeypatch, defect):
    fixture = owned_phase
    if defect.startswith(("record-", "mutation-")) or defect.endswith("-key"):
        fixture.create(OTHER)
        record = fixture.observer.data["resources"][OTHER]
        if defect.startswith("record-"):
            field = defect.removeprefix("record-")
            field = {"owner": "ownerTag", "api": "apiVersion"}.get(field, field)
            if field == "type":
                fixture.observer.data["resources"][OTHER] = None
            else:
                record[field] = None
        elif defect.startswith("mutation-"):
            field = defect.removeprefix("mutation-")
            if field == "type":
                record["mutations"][0] = None
            else:
                record["mutations"][0][field] = SHARED if field == "id" else "GET"
        else:
            key = OTHER.upper() if defect == "noncanonical-key" else OTHER.replace(ownership.GROUP, "foreign-group")
            fixture.observer.data["resources"] = {key: dict(record, id=key)}
    elif defect == "runtime-missing":
        fixture.manager.get_plugin.return_value = None
    elif defect == "runtime-wrong-type":
        fixture.manager.get_plugin.return_value = SimpleNamespace(observer=fixture.observer)
    elif defect == "observer-missing":
        del fixture.runtime.observer
    elif defect == "observer-wrong-type":
        fixture.runtime.observer = SimpleNamespace(data=fixture.observer.data)
    elif defect == "context-missing":
        for name in CONTEXT:
            monkeypatch.delenv("AZEXT_IOT_HUB_" + name)
    elif defect in ("empty-context", "orphan-debug"):
        fixture.manager.get_plugin.return_value = None
        for name in CONTEXT:
            if defect == "empty-context":
                monkeypatch.setenv("AZEXT_IOT_HUB_" + name, "")
            else:
                monkeypatch.delenv("AZEXT_IOT_HUB_" + name)
        if defect == "orphan-debug":
            monkeypatch.setenv(_focused_live.ENV, "{}")
    elif defect in ("run-id", "suite", "phase", "owner-path", "receipt-path", "relative-path"):
        key = {"owner-path": "OWNERSHIP", "receipt-path": "RECEIPT", "relative-path": "OWNERSHIP"}.get(
            defect, defect.upper().replace("-", "_"),
        )
        monkeypatch.setenv("AZEXT_IOT_HUB_" + key, "mismatched")
    elif defect == "runtime-data":
        fixture.runtime.data = []
    elif defect.startswith("runtime-"):
        field = {"schema": "schemaVersion", "run-id": "runId"}.get(defect[8:], defect[8:])
        fixture.runtime.data[field] = "mismatched"
    elif defect == "observer-data":
        fixture.observer.data = []
    elif defect.startswith("observer-"):
        field = {"schema": "schemaVersion", "run-id": "runId"}.get(defect[9:], defect[9:])
        fixture.observer.data[field] = "mismatched"
    elif defect == "not-installed":
        fixture.observer.data["installed"] = False
    elif defect == "not-hooked":
        monkeypatch.setattr(fixture.observer, "original_send", None)
    elif defect == "restored":
        fixture.observer.restore()
    elif defect in ("resources", "violations"):
        fixture.observer.data[defect] = None
    else:
        monkeypatch.setattr(fixtures, "ENTITY_RG" if defect == "entity-group" else "ENTITY_NAME", "foreign")
    fixture.runtime.write()
    fixture.observer.save()
    fixture.arm.request.reset_mock()
    fixture.arm.inventory.reset_mock()
    with pytest.raises(ownership.OwnershipError, match="Cannot determine shared Hub usage"):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_not_called()
    fixture.wire.assert_not_called()
    fixture.arm.request.assert_not_called()
    fixture.arm.inventory.assert_not_called()


@pytest.mark.parametrize("receipt", ["phase", "observer"])
@pytest.mark.parametrize("defect", ["missing", "malformed", "stale"])
def test_missing_or_invalid_durable_evidence_is_not_silently_ignored(owned_phase, receipt, defect):
    fixture = owned_phase
    path = fixture.runtime.path if receipt == "phase" else fixture.observer.path
    if defect == "missing":
        path.unlink()
    else:
        path.write_text("{" if defect == "malformed" else "{}", encoding="utf-8")
    expected = (
        FileNotFoundError if defect == "missing" else ValueError if defect == "malformed" else ownership.OwnershipError
    )
    with pytest.raises(expected):
        finish_cleanup(fixture.request)
    fixture.invoke.assert_not_called()
    fixture.wire.assert_not_called()
    fixture.arm.request.assert_not_called()


@pytest.mark.parametrize("bypass", ["sas", "pinned", "offline", "unit-only"])
def test_existing_non_dynamic_and_sas_cleanup_remain_separate(owned_phase, monkeypatch, bypass):
    fixture = owned_phase
    if bypass == "sas":
        monkeypatch.setattr(fixtures._sas_phase, "enabled", lambda: True)
    elif bypass == "pinned":
        monkeypatch.setattr(fixtures.iothub_settings.env, "azext_iot_testhub", "supplied-hub")
    elif bypass == "offline":
        monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "false")
    else:
        fixture.request.session.items = [SimpleNamespace(nodeid="test_example_unit.py::test_case")]
    with pytest.raises(StopIteration):
        finish_cleanup(fixture.request)
    fixture.manager.get_plugin.assert_not_called()
    fixture.invoke.assert_not_called()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_cleanup_logic_needs_no_native_process_or_signal_apis(owned_phase, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(StopIteration):
        finish_cleanup(owned_phase.request)
    owned_phase.invoke.assert_not_called()
