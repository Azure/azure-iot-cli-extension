# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

import json
from types import SimpleNamespace

import pytest

from azext_iot.tests.dps import _phase, _phase_receipts as receipts
from azext_iot.tests.dps import conftest as fixtures

UID = "a" * 32
SUB = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv(receipts.DIRECTORY_ENV, str(tmp_path))
    monkeypatch.setenv(receipts.RUN_UID_ENV, UID)
    monkeypatch.setenv(receipts.SUBSCRIPTION_ENV, SUB)
    monkeypatch.setenv(receipts.RESOURCE_GROUP_ENV, "group")
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.REGULAR)
    return tmp_path


@pytest.mark.parametrize("name,value", [
    (receipts.DIRECTORY_ENV, ""), (receipts.DIRECTORY_ENV, "relative"),
    (receipts.RUN_UID_ENV, ""), (receipts.RUN_UID_ENV, "invalid"),
    (receipts.SUBSCRIPTION_ENV, ""), (receipts.SUBSCRIPTION_ENV, "-" * 36),
    (receipts.RESOURCE_GROUP_ENV, ""),
])
def test_receipt_configuration_rejects_incomplete_or_invalid_values(receipt_directory, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(pytest.UsageError):
        receipts.settings()
    assert not list(receipt_directory.iterdir())


def test_receipts_are_optional_without_orchestration(monkeypatch):
    for name in (receipts.DIRECTORY_ENV, receipts.RUN_UID_ENV, receipts.SUBSCRIPTION_ENV, receipts.RESOURCE_GROUP_ENV):
        monkeypatch.delenv(name, raising=False)
    assert receipts.settings() is None
    receipts.before_create("name", "group", "old-run", "h")
    assert receipts.before_delete("name")


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_create_receipt_precedes_mutation_and_refuses_replay(receipt_directory, monkeypatch, phase, kind):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    uid = UID if phase == _phase.REGULAR else UID + "-service-sas"
    receipts.before_create("owned", "group", uid, kind)
    path = receipt_directory / f"owned-{kind}.json"
    record = json.loads(path.read_text())
    assert record["subscription"] == SUB
    assert record["tags"] == {"intTest": "true", "runUid": uid, "kind": kind}
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match="repeat"):
        receipts.before_create("owned", "group", uid, kind)
    receipts.after_create("owned", dict(record, properties={"provisioningState": "Succeeded"}))
    assert (receipt_directory / f"created-{kind}.json").is_file()


@pytest.mark.parametrize("resource", [None, {}, {"properties": {"provisioningState": "Creating"}}])
def test_null_or_incomplete_create_result_cannot_resolve_an_uncertain_write(receipt_directory, resource):
    receipts.before_create("owned", "group", UID, "h")
    receipts.after_create("owned", resource)
    assert json.loads((receipt_directory / "created-h.json").read_text())["create_completed"] is False


@pytest.mark.parametrize("state", ["absent", "Deleting", "Succeeded", "foreign"])
def test_delete_requires_current_exact_ownership_and_never_repeats_delete(receipt_directory, state):
    receipts.before_create("owned", "group", UID, "h")
    record = json.loads((receipt_directory / "owned-h.json").read_text())
    resource = {"id": record["id"], "tags": record["tags"], "properties": {"provisioningState": state}}
    if state == "foreign":
        resource["tags"] = {}
        with pytest.raises(RuntimeError, match="ownership"):
            receipts.before_delete("owned", resource)
    else:
        assert receipts.before_delete("owned", None if state == "absent" else resource) == (state == "Succeeded")
    assert (receipt_directory / "delete-h.json").exists() == (state == "Succeeded")
    if state == "Succeeded":
        with pytest.raises(RuntimeError, match="repeat"):
            receipts.before_delete("owned", resource)
        receipts.after_delete("owned")
        assert (receipt_directory / "deleted-h.json").is_file()


def test_foreign_delete_without_receipt_is_rejected(receipt_directory):
    with pytest.raises(RuntimeError, match="receipt"):
        receipts.before_delete("borrowed", {})
    assert not list(receipt_directory.iterdir())


def test_session_and_worker_selection_receipts(receipt_directory):
    receipts.session_started(SimpleNamespace())
    receipts.session_started(SimpleNamespace(workerinput={"workerid": "gw0"}))
    receipts.selected(SimpleNamespace(workerinput={"workerid": "gw0"}), [
        SimpleNamespace(nodeid="azext_iot/tests/dps/test.py::test_one"),
        SimpleNamespace(nodeid="azext_iot/tests/dps/test.py::test_two"),
    ])
    assert json.loads((receipt_directory / "started.json").read_text())["started"]
    assert json.loads((receipt_directory / "selection-gw0.json").read_text())["selected"] == 2


@pytest.mark.parametrize("kind", ["dps", "hub"])
def test_managed_create_preflight_never_overwrites_existing_resource(receipt_directory, mocker, kind):
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    if kind == "dps":
        mocker.patch.object(fixtures, "_find_dps_by_name", return_value={"name": "existing"})

        def create():
            fixtures._create_managed_dps(UID, "h", None)
    else:
        mocker.patch.object(fixtures, "_find_hub_by_name", return_value={"name": "existing"})

        def create():
            fixtures._create_managed_hub(UID, "hub")
    with pytest.raises(Exception, match="refusing to overwrite"):
        create()
    invoke.assert_not_called()
    assert not list(receipt_directory.glob("owned-*.json"))


@pytest.mark.parametrize("invalid", ["pin", "group", "location"])
def test_receipt_mode_rejects_pytest_loaded_pins_and_scope_before_any_fixtures(receipt_directory, mocker, invalid):
    mocker.patch.object(fixtures, "ENTITY_RG", "group")
    mocker.patch.object(fixtures, "ENTITY_LOCATION", "centraluseuap")
    mocker.patch.object(fixtures, "HUB_TEST_LOCATION", "centraluseuap")
    settings = mocker.patch.object(fixtures, "settings")
    settings.env.azext_iot_testdps = ""
    settings.env.azext_iot_testdps_hub = ""
    settings.env.azext_iot_testhub = ""
    if invalid == "pin":
        settings.env.azext_iot_testdps = "borrowed"
    elif invalid == "group":
        mocker.patch.object(fixtures, "ENTITY_RG", "other")
    else:
        mocker.patch.object(fixtures, "ENTITY_LOCATION", "westus")
    with pytest.raises(pytest.UsageError, match="Isolated"):
        fixtures.pytest_configure(mocker.Mock())
