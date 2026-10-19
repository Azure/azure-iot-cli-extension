# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for the explicit metadata lease's deadlines and ownership cleanup."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import responses
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.transport import HttpRequest, RequestsTransportResponse

from azext_iot.tests.iothub.metadata import test_hub_metadata_int as subject
from azext_iot.tests.iothub.test_dataplane_adapter_unit import adapter
from azext_iot.tests.iothub.test_dataplane_wire_unit import ENDPOINT


def _error(status):
    response = requests.Response()
    response.status_code = status
    response._content = b"{}"  # pylint: disable=protected-access
    return HttpResponseError(response=RequestsTransportResponse(HttpRequest("GET", "https://unit.invalid"), response))


@pytest.mark.parametrize("failure", [
    _error(403), _error(404), HttpResponseError("credential failure"), ValueError("bad response"),
])
def test_only_native_resource_404_is_absent(failure):
    with pytest.raises(type(failure)) as observed:
        subject._absent(Mock(side_effect=failure))
    assert observed.value is failure
    assert not subject._absent(Mock(return_value={}))


def test_absence_requires_the_real_resource_transport_response(mocker):
    client = adapter()

    def read(**kwargs):
        return client.devices.get_identity(id="device", **kwargs)

    with responses.RequestsMock() as network:
        network.add("GET", ENDPOINT + "/devices/device", status=404, json={"Message": "Missing."})
        assert subject._absent(read)
        assert len(network.calls) == 1
    credential_error = _error(404)
    mocker.patch.object(client.sdk._config.authentication_policy, "on_request", side_effect=credential_error)
    with responses.RequestsMock() as network:
        with pytest.raises(HttpResponseError) as observed:
            subject._absent(read)
        assert observed.value is credential_error
        assert not network.calls
    client.close()


def test_wait_rejects_late_success_and_never_retries_service_errors(mocker):
    mocker.patch.object(subject, "monotonic", side_effect=[0, 0, 2])
    read = Mock(return_value=True)
    with pytest.raises(AssertionError, match="deadline"):
        subject._wait(read, bool, "late", timeout=1)
    read.assert_called_once()
    mocker.patch.object(subject, "monotonic", return_value=0)
    failure = _error(403)
    read = Mock(side_effect=failure)
    with pytest.raises(HttpResponseError) as observed:
        subject._wait(read, bool, "denied", timeout=1)
    assert observed.value is failure
    read.assert_called_once()


def test_wait_polls_state_with_one_elapsed_time_budget(mocker):
    mocker.patch.object(subject, "monotonic", side_effect=[0, 0, 0.5, 0.75, 1])
    pause = mocker.patch.object(subject, "sleep")
    assert subject._wait(Mock(side_effect=[False, True]), bool, "ready", timeout=1) is True
    pause.assert_called_once_with(0.5)


def test_cleanup_never_replays_accepted_or_uncertain_delete(mocker):
    client = Mock()
    client.devices.get_identity.return_value = {}
    sent = set()
    mocker.patch.object(subject, "_wait", side_effect=AssertionError("budget exhausted"))
    for _ in range(2):
        with pytest.raises(AssertionError, match="budget"):
            subject._cleanup_device(client, "owned", sent)
    client.devices.delete_identity.assert_called_once_with(id="owned", if_match="*", timeout=30)
    assert sent == {"owned"}


def test_cleanup_attempts_all_owned_ids_but_blocks_when_jobs_are_running(mocker):
    client = Mock()
    remove = mocker.patch.object(subject, "_cleanup_device", side_effect=[_error(403), None])
    with pytest.raises(HttpResponseError):
        subject._cleanup_devices(client, ["parent", "child"], set())
    assert [call.args[1] for call in remove.call_args_list] == ["child", "parent"]
    remove.reset_mock()
    with pytest.raises(AssertionError, match="undrained"):
        subject._cleanup_devices(client, ["parent", "child"], set(), [(0, "job")])
    remove.assert_not_called()


def test_accepted_job_cancel_is_followed_by_gets_not_another_delete(mocker):
    client = Mock()
    client.jobs.get_import_export_job.side_effect = [{"status": "running"}, {"status": "running"}, {"status": "cancelled"}]
    lease = SimpleNamespace(clients=[client], pending_jobs=[(0, "job")])
    mocker.patch.object(subject, "sleep")
    subject._drain_jobs(lease)
    client.jobs.cancel_import_export_job.assert_called_once_with(id="job", timeout=30)
    assert client.jobs.get_import_export_job.call_count == 3
    assert lease.pending_jobs == []


def test_failed_job_drain_retains_blocker_and_attempts_other_jobs():
    client = Mock()
    client.jobs.get_import_export_job.side_effect = [_error(403), {"status": "completed"}, {"status": "completed"}]
    lease = SimpleNamespace(clients=[client], pending_jobs=[(0, "first"), (0, "second")])
    with pytest.raises(HttpResponseError):
        subject._drain_jobs(lease)
    assert lease.pending_jobs == [(0, "second")]
    client.jobs.cancel_import_export_job.assert_not_called()


def test_missing_live_opt_in_prevents_any_credential_or_cli_construction(mocker, monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "False")
    factory = mocker.patch.object(subject, "adr_service_factory")
    cli = mocker.patch.object(subject, "EmbeddedCLI")
    with pytest.raises(AssertionError, match="AZURE_TEST_RUN_LIVE"):
        next(subject.preview_lease.__wrapped__())
    factory.assert_not_called()
    cli.assert_not_called()


@pytest.mark.parametrize("result", [None, {}, {"jobId": ""}])
def test_uncertain_job_submission_blocks_cleanup_without_replay(mocker, result):
    lease = SimpleNamespace(cli=Mock(), clients=[Mock()], pending_jobs=[])
    submit = mocker.patch.object(subject, "_checked")
    submit.return_value.as_json.return_value = result
    with pytest.raises(AssertionError, match="job ID"):
        subject._submit_job(lease, 0, "owned export command")
    assert lease.pending_jobs == [(0, None)]
    with pytest.raises(AssertionError, match="confirmed job ID"):
        subject._drain_jobs(lease)
    submit.assert_called_once()
    lease.clients[0].jobs.get_import_export_job.assert_not_called()


def test_failed_job_submission_retains_uncertainty_and_success_gets_its_id(mocker):
    lease = SimpleNamespace(cli=Mock(), pending_jobs=[])
    failure = _error(503)
    submit = mocker.patch.object(subject, "_checked", side_effect=failure)
    with pytest.raises(HttpResponseError) as observed:
        subject._submit_job(lease, 0, "owned export command")
    assert observed.value is failure
    assert lease.pending_jobs == [(0, None)]
    lease.pending_jobs.clear()
    submit.side_effect = None
    submit.return_value.as_json.return_value = {"jobId": "job"}
    complete = mocker.patch.object(subject, "_job_completed")
    assert subject._submit_job(lease, 0, "owned export command") == {"jobId": "job"}
    complete.assert_called_once_with(lease, 0, "job")
    assert lease.pending_jobs == [(0, "job")]
