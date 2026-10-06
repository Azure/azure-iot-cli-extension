# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Cleanup handoff must preserve ownership without polling for Azure deletion."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from azure.core.exceptions import HttpResponseError

from azext_iot.tests import _cleanup_handoff as handoff
from azext_iot.tests import _ado_pipeline as pipeline
from azext_iot.tests import _hub_phase_runner as hub
from azext_iot.tests.test_hub_phase_runner_unit import PREFIX, record


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setenv(handoff.ENV, str(tmp_path / "cleanup-receipts"))
    return tmp_path


def test_submission_acknowledgment_and_failure_are_not_absence(records, capsys):
    with handoff.submission("/owned/one"):
        pass
    assert handoff.summary(records)[0]["status"] == "accepted"
    handoff.cleanup("/owned/two", Mock(side_effect=HttpResponseError("private-secret")))
    values = handoff.summary(records)
    assert [value["status"] for value in values] == ["accepted", "failed"]
    assert values[1]["errorType"] == "HttpResponseError"
    assert "private-secret" not in str(values) + capsys.readouterr().out
    assert "Cleanup failed: 1" in pipeline.cleanup_report(records)
    assert (records / "cleanup-status.json").is_file()


def test_latest_cleanup_state_supersedes_pending_without_erasing_events(records):
    handoff.record("/owned/one", "pending")
    handoff.record("/OWNED/one", "accepted")
    assert len(list((records / "cleanup-receipts").glob("*.json"))) == 2
    assert [value["status"] for value in handoff.summary(records)] == ["accepted"]


def test_successful_submission_while_unwinding_a_test_failure_is_still_accepted(records):
    with pytest.raises(AssertionError, match="test failed"):
        try:
            raise AssertionError("test failed")
        finally:
            with handoff.submission("/owned/one"):
                pass
    assert handoff.summary(records)[0]["status"] == "accepted"


@pytest.mark.parametrize("status", [202, 500])
def test_hub_handoff_does_not_poll_or_replay_delete(records, mocker, status):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/owned").casefold()
    evidence = {
        "schemaVersion": 1, "installed": True, "phase": "regular", "runId": "uid", "violations": [],
        "target": hub.TARGETS["target"]("centraluseuap"),
        "resources": {resource_id: record(resource_id)},
    }
    resource = {"id": resource_id, "tags": {hub.helper()["OWNER_TAG"]: "uid"}}
    arm = Mock()
    arm.request.side_effect = lambda method, *_: (200, resource) if method == "GET" else (status, {})
    mocker.patch.object(hub.time, "sleep", side_effect=AssertionError("Cleanup must not poll"))
    result = hub.cleanup_regular(arm, evidence, "uid", "regular", float("inf"), records / "owner.json", handoff=True)
    assert result["mode"] == "handoff" and result["complete"] is False
    assert [call.args[0] for call in arm.request.call_args_list] == ["GET", "DELETE"]
    assert handoff.summary(records)[0]["status"] == ("accepted" if status == 202 else "failed")
    assert hub.helper()["ownership_errors"](evidence, "uid", "regular", allow_pending_cleanup=True) == []
    assert hub.helper()["ownership_errors"](evidence, "uid", "regular")
    hub.cleanup_regular(arm, evidence, "uid", "regular", float("inf"), records / "owner.json", handoff=True)
    assert [call.args[0] for call in arm.request.call_args_list] == ["GET", "DELETE", "GET"]


def test_handoff_does_not_relax_creation_or_owned_scope_validation(records):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/owned").casefold()
    evidence = {
        "schemaVersion": 1, "installed": True, "phase": "regular", "runId": "uid", "violations": [],
        "target": hub.TARGETS["target"]("centraluseuap"),
        "resources": {resource_id: record(resource_id)},
    }
    for change in ("unresolved-create", "foreign-owner"):
        bad = deepcopy(evidence)
        if change == "unresolved-create":
            bad["resources"][resource_id]["resolved"] = False
        else:
            bad["resources"][resource_id]["ownerTag"] = "foreign"
        arm = Mock()
        result = hub.cleanup_regular(arm, bad, "uid", "regular", float("inf"), records / "owner.json", handoff=True)
        assert result["errors"]
        arm.request.assert_not_called()


@pytest.mark.parametrize("pending", [False, True])
def test_adr_namespace_handoff_observes_children_once_without_polling(records, mocker, pending):
    from azext_iot.tests.adr import _readiness as readiness
    from azext_iot.tests.adr.conftest import TEST_SUBSCRIPTION

    resource_id = f"/subscriptions/{TEST_SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
    getter = mocker.patch.object(readiness, "_get_resource", side_effect=[
        {"id": resource_id, "properties": {}}, {"id": resource_id + "/jobs/job"} if pending else None,
    ])
    clock, sleeper, scenario = Mock(), Mock(), Mock()
    readiness.delete_test_namespace(scenario, "ns", "rg", jobs=("job",), clock=clock, sleeper=sleeper)
    assert getter.call_count == 2
    clock.assert_not_called()
    sleeper.assert_not_called()
    if pending:
        scenario.cmd.assert_not_called()
        assert handoff.summary(records)[0]["status"] == "pending"
    else:
        scenario.cmd.assert_called_once_with("iot adr ns delete --namespace ns -g rg -y --no-wait")
        assert handoff.summary(records)[0]["status"] == "accepted"


@pytest.mark.parametrize("kind", ["hub", "dps", "namespace", "su", "identity"])
def test_adr_infrastructure_cleanup_handoff_is_cleanup_only(records, mocker, kind):
    from azext_iot import _factory
    from azext_iot.tests.adr._helpers import ADRFullInfraHelper

    helper = ADRFullInfraHelper()
    helper.cli_ctx, helper.cmd = Mock(), Mock()
    resource = (kind, "owned", "rg")
    helper._owned_resources = {resource: None}
    mocker.patch.object(helper, "_resource_is_absent", return_value=False)
    synchronous = mocker.patch.object(helper, "_delete_owned_resource", side_effect=AssertionError("Synchronous cleanup"))
    factories = [mocker.patch.object(_factory, name) for name in ("iot_hub_service_factory", "iot_service_provisioning_factory")]
    helper.cleanup_full_infra()
    synchronous.assert_not_called()
    assert handoff.summary(records)[0]["status"] == "accepted"
    assert not helper._owned_resources
    if kind in ("hub", "dps"):
        client = factories[int(kind == "dps")].return_value.__enter__.return_value
        operation = client.iot_hub_resource if kind == "hub" else client.iot_dps_resource
        assert operation.begin_delete.call_args.kwargs["polling"] is False
        operation.begin_delete.return_value.result.assert_not_called()
    else:
        assert ("--no-wait" in helper.cmd.call_args.args[0]) == (kind != "identity")
