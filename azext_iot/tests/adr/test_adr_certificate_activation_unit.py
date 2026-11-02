# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline evidence, real CLI/SDK transport, and independent cleanup reconciliation."""

from copy import deepcopy
from contextlib import contextmanager
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from azure.cli.core.azclierror import AzureResponseError
from azure.core.exceptions import HttpResponseError
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from azext_iot.adr.providers import certificate_activation as activation
from azext_iot.tests.adr import test_adr_sdk_unit as sdk
from azext_iot.tests.adr import test_adr_certificate_action_tracker_unit as tracking

ca_wire_cli = sdk.ca_wire_cli
wire_client = sdk.wire_client
tracker_factory = tracking.tracker_factory
live_action_scenario = tracking.live_action_scenario

RID = urlsplit(sdk.CA_URL).path
SECRET = "response-must-not-be-rendered"


@pytest.fixture
def states(ca_pki):
    before = sdk._ca_resource(ca_pki, "activate")
    before["id"] = RID
    before["properties"]["uuid"] = "owned-uuid"
    before["properties"]["issuer"]["status"] = "PendingActivation"
    after = deepcopy(before)
    after["properties"]["issuer"].update(
        status="Active", thumbprint=x509.load_pem_x509_certificate(ca_pki["leaf"].encode()).fingerprint(hashes.SHA1()).hex(),
    )
    return SimpleNamespace(
        before=before, after=after, chain=ca_pki["chain"],
        evidence=activation.ExternalActivationEvidence(before, ca_pki["chain"], resource_id=RID),
    )


@pytest.fixture
def fast_wait(mocker):
    ticks, sleeps = [0], []

    def pause(seconds):
        sleeps.append(seconds)
        ticks[0] += seconds

    def wait(*args, **kwargs):
        return activation.wait_for_activation(
            *args, **kwargs, timeout_sec=5, clock=lambda: ticks[0], sleeper=pause,
        )

    mocker.patch("azext_iot.adr.providers.certificate_authority.wait_for_activation", side_effect=wait)
    return ticks, sleeps


@pytest.mark.parametrize("algorithm", [hashes.SHA1, hashes.SHA256])
@pytest.mark.parametrize("colons", [False, True])
def test_exact_submitted_certificate_and_case_insensitive_id(states, algorithm, colons):
    digest = x509.load_pem_x509_certificate(states.chain.encode()).fingerprint(algorithm()).hex().upper()
    states.after["id"] = RID.swapcase()
    states.after["properties"]["issuer"]["thumbprint"] = (
        ":".join(digest[index:index + 2] for index in range(0, len(digest), 2)) if colons else digest
    )
    assert states.evidence.completed(states.after)


@pytest.mark.parametrize("change", [
    lambda r: r["properties"]["issuer"].update(thumbprint=None),
    lambda r: r["properties"]["issuer"].update(thumbprint="unrelated-active-certificate"),
    lambda r: r["properties"]["issuer"].update(thumbprint=42),
    lambda r: r["properties"]["issuer"].update(status="PendingActivation"),
    lambda r: r["properties"]["issuer"].pop("status"),
    lambda r: r["properties"].update(provisioningState="Updating"),
    lambda r: r["properties"].pop("provisioningState"),
])
def test_resource_success_or_any_active_is_not_enough(states, change):
    change(states.after)
    states.after["etag"] = "changed-version"
    assert states.evidence.completed(states.after) is False


@pytest.mark.parametrize("body", [None, [], {}, {"properties": None}, {"properties": {"issuer": None}}])
def test_malformed_evidence_never_renders_response(states, body):
    with pytest.raises(AzureResponseError, match="shape"):
        states.evidence.completed(body)


@pytest.mark.parametrize("change,match", [
    (lambda r: r.update(id=RID + "-foreign"), "identity"),
    (lambda r: r.pop("id"), "identity"),
    (lambda r: r.update(id=123), "identity"),
    (lambda r: r["properties"].update(certificateAuthorityType="Root"), "identity"),
    (lambda r: r["properties"]["issuer"].update(issuerType="Microsoft"), "identity"),
    (lambda r: r["properties"].update(uuid="replacement"), "UUID"),
    (lambda r: r["properties"].pop("uuid"), "UUID"),
    (lambda r: r["properties"].update(provisioningState="Failed"), "Failed/Canceled"),
    (lambda r: r["properties"].update(provisioningState="Canceled"), "Failed/Canceled"),
    (lambda r: r["properties"]["issuer"].update(status="Failed"), "Failed/Canceled"),
    (lambda r: r["properties"]["issuer"].update(status="Canceled"), "Failed/Canceled"),
])
def test_false_terminal_identity_or_failure_rejected(states, change, match):
    change(states.after)
    states.after["error"] = SECRET
    with pytest.raises(AzureResponseError, match=match) as raised:
        states.evidence.completed(states.after)
    assert SECRET not in str(raised.value)


@pytest.mark.parametrize("status", [
    None, "", "Pending", "pendingactivation", "PendingActivationExtra", "Active", "Failed", "Canceled",
])
def test_no_pending_baseline_cannot_enable_resource_completion(states, status):
    states.before["properties"]["issuer"]["status"] = status
    assert not activation.has_pending_activation(states.before)
    with pytest.raises(AzureResponseError, match="requires a PendingActivation"):
        activation.ExternalActivationEvidence(states.before, states.chain, resource_id=RID)


def test_live_pending_activation_baseline_selects_resource_evidence(ca_pki):
    # focused-live/adr.log:317,348 reports PendingActivation, not Pending.
    before = {
        "id": RID,
        "properties": {
            "certificateAuthorityType": "ICA",
            "provisioningState": "Succeeded",
            "issuer": {
                "issuerType": "External",
                "status": "PendingActivation",
                "certificateSigningRequest": ca_pki["resource"]["properties"]["issuer"]["certificateSigningRequest"],
            },
        },
    }
    assert activation.has_pending_activation(before)
    evidence = activation.ExternalActivationEvidence(before, ca_pki["chain"], resource_id=RID)
    assert not evidence.completed(before)
    after = deepcopy(before)
    after["properties"]["issuer"].update(
        status="Active", thumbprint=x509.load_pem_x509_certificate(ca_pki["leaf"].encode()).fingerprint(hashes.SHA1()).hex(),
    )
    assert evidence.completed(after)


def test_stale_baseline_certificate_is_not_new_activation(states):
    states.before["properties"]["issuer"]["thumbprint"] = states.after["properties"]["issuer"]["thumbprint"]
    with pytest.raises(AzureResponseError, match="already contains"):
        activation.ExternalActivationEvidence(states.before, states.chain, resource_id=RID)


def test_uuid_optional_and_constructor_checks_identity(states):
    states.before["properties"].pop("uuid")
    evidence = activation.ExternalActivationEvidence(states.before, states.chain, resource_id=RID)
    assert evidence.completed(states.after)
    with pytest.raises(AzureResponseError, match="identity"):
        activation.ExternalActivationEvidence(states.before, states.chain, resource_id=RID + "-foreign")


def test_wait_returns_proving_get_unchanged_and_honors_ack_delay(states):
    clock, sleeps, budgets = [0], [], []

    def pause(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def fetch(remaining):
        budgets.append(remaining)
        return states.before if len(budgets) == 1 else states.after

    result = activation.wait_for_activation(
        fetch, states.evidence, initial_response=SimpleNamespace(headers={"Retry-After": "2"}),
        timeout_sec=5, clock=lambda: clock[0], sleeper=pause,
    )
    assert result is states.after
    assert budgets == [3, 2] and sleeps == [2, 1]


@pytest.mark.parametrize("timeout,late", [(0, False), (1, False), (5, True)])
def test_wait_deadline_never_accepts_late_success(states, timeout, late, mocker):
    clock = [0]

    def fetch(_remaining):
        clock[0] = 6
        return states.after

    read = mocker.Mock(side_effect=fetch)
    with pytest.raises(AzureResponseError, match="Timed out"):
        activation.wait_for_activation(
            read, states.evidence, initial_response=None, timeout_sec=timeout,
            clock=lambda: clock[0], sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )
    assert read.call_count == int(late)


def test_default_clock_and_sleeper_are_resolved_at_call_time(states, mocker):
    clock = mocker.patch.object(activation, "monotonic", return_value=0)
    pause = mocker.patch.object(activation, "sleep")
    result = activation.wait_for_activation(lambda _budget: states.after, states.evidence, initial_response=None)
    assert result is states.after and clock.call_count >= 4
    pause.assert_called_once_with(1)


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("ack", [202, 204])
@pytest.mark.parametrize("location", [None, sdk.CA_LOCATION, "https://foreign.invalid/status?sig=private"])
def test_pending_cli_never_reads_location_or_starts_background_polling(
    states, fast_wait, ca_wire_cli, ca_pki, wire_client, mocked_response, mocker, tmp_path, no_wait, ack, location,
):
    mocked_response.add("GET", sdk.CA_URL, json=states.before)
    if not no_wait:
        mocked_response.add("GET", sdk.CA_URL, json=states.after)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=ack, headers={"Location": location} if location else {})
    begin = mocker.spy(wire_client.certificate_authorities, "begin_activate")
    code, output = sdk._invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path, no_wait=no_wait)
    assert code == 0, ca_wire_cli.result.error
    assert begin.call_args.kwargs["polling"] is False
    begin.spy_return.result()  # Join the SDK thread: no hidden Location/async-status calls.
    if no_wait:
        assert output.strip() in ("", "null")
        assert not fast_wait[1]
    else:
        assert json.loads(output) == dict(states.after, resourceGroup="rg")
    assert [call.request.method for call in mocked_response.calls] == (
        ["GET", "POST"] if no_wait else ["GET", "POST", "GET"]
    )
    assert all(urlsplit(call.request.url).path in (RID, RID + "/activate") for call in mocked_response.calls)


@pytest.mark.parametrize("stage", ["preflight", "post", "resource"])
@pytest.mark.parametrize("permission", [
    "Microsoft.DeviceRegistry/locations/asyncOperationStatuses/read",
    "Microsoft.DeviceRegistry/namespaces/certificateAuthorities/read",
    "Microsoft.DeviceRegistry/namespaces/certificateAuthorities/activate/action",
    "Microsoft.Other/unrelated/read",
])
def test_any_403_remains_failure_without_fallback_or_post_replay(
    states, fast_wait, ca_wire_cli, ca_pki, mocked_response, tmp_path, stage, permission,
):
    denied = {"error": {"code": "AuthorizationFailed", "message": permission}}
    mocked_response.add("GET", sdk.CA_URL, status=403 if stage == "preflight" else 200,
                        json=denied if stage == "preflight" else states.before)
    if stage != "preflight":
        mocked_response.add("POST", sdk.CA_URL + "/activate", status=403 if stage == "post" else 202,
                            json=denied if stage == "post" else None, headers={"Location": sdk.CA_LOCATION})
    if stage == "resource":
        mocked_response.add("GET", sdk.CA_URL, status=403, json=denied)
    code, output = sdk._invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path)
    assert code != 0 and not output.strip()
    assert permission in str(ca_wire_cli.result.error)
    assert len(mocked_response.calls) == {"preflight": 1, "post": 2, "resource": 3}[stage]


@pytest.mark.parametrize("failure", ["stale", "wrong-thumbprint", "identity", "failed", "canceled"])
def test_waited_cli_cannot_pass_with_false_terminal_resource(
    states, fast_wait, ca_wire_cli, ca_pki, mocked_response, tmp_path, failure,
):
    mocked_response.add("GET", sdk.CA_URL, json=states.before)
    if failure == "stale":
        states.after = states.before
    elif failure == "wrong-thumbprint":
        states.after["properties"]["issuer"]["thumbprint"] = "foreign"
    elif failure == "identity":
        states.after["properties"]["uuid"] = "foreign"
    else:
        states.after["properties"]["provisioningState"] = "Failed" if failure == "failed" else "Canceled"
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202, headers={"Location": sdk.CA_LOCATION})
    mocked_response.add("GET", sdk.CA_URL, json=states.after)
    code, output = sdk._invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path)
    assert code != 0 and not output.strip()
    assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1
    assert all(urlsplit(call.request.url).path in (RID, RID + "/activate") for call in mocked_response.calls)


def test_provider_resource_gets_have_bounded_timeouts_no_redirects_or_retries(
    states, fast_wait, ca_wire_cli, ca_pki, wire_client, mocked_response, tmp_path, mocker,
):
    mocked_response.add("GET", sdk.CA_URL, json=states.before)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202)
    mocked_response.add("GET", sdk.CA_URL, json=states.after)
    get = mocker.spy(wire_client.certificate_authorities, "get")
    assert sdk._invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path)[0] == 0
    assert get.call_args.kwargs == {
        "resource_group_name": "rg", "namespace_name": "namespace", "certificate_authority_name": "ca",
        "connection_timeout": 4, "read_timeout": 4, "retry_total": 0, "permit_redirects": False,
    }


def resource_tracker(factory, states):
    tracker = factory(action="activate")
    tracker.use_activation_resource(states.before, states.chain, sdk.API_VERSION)
    return tracker


@pytest.mark.parametrize("ack", [202, 204])
def test_tracker_independently_reads_exact_resource_even_after_204(states, tracker_factory, mocked_response, ack):
    tracker = resource_tracker(tracker_factory[0], states)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=ack, headers={"Location": sdk.CA_LOCATION})
    mocked_response.add("GET", sdk.CA_URL, json=states.before)
    mocked_response.add("GET", sdk.CA_URL, json=states.after)
    tracking.submit(tracker, sdk.CA_URL + "/activate")
    assert not tracker.terminal
    tracker.wait()
    assert tracker.terminal and tracker.succeeded
    count = len(mocked_response.calls)
    tracker.wait(cleanup=True)
    assert len(mocked_response.calls) == count
    assert [call.request.method for call in mocked_response.calls] == ["POST", "GET", "GET"]
    assert all(urlsplit(call.request.url).path == RID for call in mocked_response.calls[1:])
    assert all(f"api-version={sdk.API_VERSION}" in call.request.url for call in mocked_response.calls[1:])


@pytest.mark.parametrize("http,body", [
    (200, {}), (202, {"status": "Succeeded"}), (204, None),
    (403, {"error": {"message": SECRET}}), (302, None),
])
def test_invalid_resource_read_never_completes_or_releases_quarantine(
    states, tracker_factory, mocked_response, http, body, caplog,
):
    tracker = resource_tracker(tracker_factory[0], states)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202, headers={"Location": sdk.CA_LOCATION})
    mocked_response.add("GET", sdk.CA_URL, status=http, json=body)
    tracking.submit(tracker, sdk.CA_URL + "/activate")
    for cleanup in (False, True):
        with pytest.raises(AssertionError) as raised:
            tracker.wait(cleanup=cleanup)
        assert SECRET not in str(raised.value) + caplog.text
        assert not tracker.terminal and not tracker.succeeded
    assert all(call.request.url != sdk.CA_LOCATION for call in mocked_response.calls)


@pytest.mark.parametrize("kind", ["stale", "wrong-cert", "uuid", "failed"])
def test_tracker_quarantine_survives_uncertainty_until_correlated_completion(
    states, tracker_factory, mocked_response, kind,
):
    tracker = resource_tracker(tracker_factory[0], states)
    bad = deepcopy(states.after)
    if kind == "stale":
        bad = states.before
    elif kind == "wrong-cert":
        bad["properties"]["issuer"]["thumbprint"] = "foreign"
    elif kind == "uuid":
        bad["properties"]["uuid"] = "foreign"
    else:
        bad["properties"]["provisioningState"] = "Failed"
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202)
    mocked_response.add("GET", sdk.CA_URL, json=bad)
    tracking.submit(tracker, sdk.CA_URL + "/activate")
    with pytest.raises(AssertionError):
        tracker.wait()
    assert not tracker.succeeded and not tracker.terminal
    mocked_response.replace("GET", sdk.CA_URL, json=states.after)
    tracker.wait(cleanup=True)
    assert tracker.succeeded and tracker.terminal
    assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1


@pytest.mark.parametrize("kind", ["action", "version", "submitted", "observing"])
def test_tracker_resource_mode_cannot_be_selected_for_revoke_or_after_submission(
    states, tracker_factory, mocked_response, kind,
):
    tracker = tracker_factory[0](action="revokeAndRotate" if kind == "action" else "activate")
    if kind == "submitted":
        mocked_response.add("POST", sdk.CA_URL + "/activate", status=202, headers={"Location": sdk.CA_LOCATION})
        tracking.submit(tracker, sdk.CA_URL + "/activate")
    if kind == "observing":
        with tracker.observe():
            pass
    with pytest.raises(AssertionError, match="pre-submission"):
        tracker.use_activation_resource(states.before, states.chain, "bad?query" if kind == "version" else sdk.API_VERSION)


def test_wait_fetch_errors_propagate_unchanged_without_retry(states, mocker):
    error = HttpResponseError("resource read denied")
    fetch = mocker.Mock(side_effect=error)
    with pytest.raises(HttpResponseError) as raised:
        activation.wait_for_activation(
            fetch, states.evidence, initial_response=None, clock=lambda: 0, sleeper=lambda _seconds: None,
        )
    assert raised.value is error and fetch.call_count == 1


def test_tracker_resource_transport_failure_is_sanitized(states, tracker_factory, mocked_response):
    tracker = resource_tracker(tracker_factory[0], states)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202)
    mocked_response.add("GET", sdk.CA_URL, body=requests.ConnectionError(SECRET))
    tracking.submit(tracker, sdk.CA_URL + "/activate")
    with pytest.raises(AssertionError, match="transport details suppressed") as raised:
        tracker.wait()
    assert SECRET not in str(raised.value)
    assert not tracker.terminal


@pytest.mark.parametrize("ack", [202, 204])
def test_actual_no_wait_live_recipe_independently_proves_completion_before_cleanup(
    states, fast_wait, live_action_scenario, mocked_response, mocker, tmp_path, ack,
):
    scenario = live_action_scenario
    resource_id = RID.rsplit("/", 1)[0] + "/ica"
    resource_url = "https://management.azure.com" + resource_id
    for resource in (states.before, states.after):
        resource.update(id=resource_id, name="ica")
    scenario._owned_ca_ids = {resource_id}

    @contextmanager
    def owned():
        yield "--ns namespace -g rg", states.before
        scenario._ca_actions[resource_id].wait(cleanup=True)
        assert scenario._ca_actions[resource_id].succeeded

    mocker.patch.object(scenario, "_owned_target", owned)
    chain = tmp_path / "chain.pem"
    chain.write_text(states.chain, encoding="utf-8")
    mocker.patch.object(scenario, "_sign_service_csr", return_value=chain)
    mocker.patch.object(scenario, "_assert_raw_fields")
    mocked_response.add("GET", resource_url, json=states.before)
    mocked_response.add("GET", resource_url, json=states.after)
    mocked_response.add("POST", resource_url + "/activate", status=ack, headers={"Location": sdk.CA_LOCATION})
    scenario.test_external_activation_no_wait()
    assert scenario._ca_actions[resource_id].succeeded
    assert not fast_wait[1], "The --no-wait command itself must not wait."
    assert [call.request.method for call in mocked_response.calls] == ["GET", "POST", "GET", "GET"]
    assert all(urlsplit(call.request.url).path in (resource_id, resource_id + "/activate")
               for call in mocked_response.calls)


@pytest.mark.parametrize("ack", [200, 400, 403])
def test_tracker_unsupported_acknowledgement_cannot_be_repaired_by_resource(
    states, tracker_factory, mocked_response, ack,
):
    tracker = resource_tracker(tracker_factory[0], states)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=ack)
    tracking.submit(tracker, sdk.CA_URL + "/activate")
    with pytest.raises(AssertionError, match="acknowledgement HTTP"):
        tracker.wait(cleanup=True)
    assert len(mocked_response.calls) == 1 and not tracker.terminal


def test_legacy_tracker_malformed_url_is_quarantined(tracker_factory):
    assert tracker_factory[0]()._location("https://[") is None


def test_tracker_redacts_preformatted_exception_and_stack_information(mocker):
    import logging
    from azext_iot.tests.adr._certificate_action_tracker import _protect_action_logs

    original = logging.getLogRecordFactory()
    signed = sdk.CA_LOCATION + "?secret=" + SECRET

    def previous(*args, **kwargs):
        record = logging.LogRecord(*args, **kwargs)
        record.exc_text = signed
        record.stack_info = signed
        return record

    try:
        logging.setLogRecordFactory(previous)
        _protect_action_logs()
        record = logging.getLogRecordFactory()("test", logging.ERROR, "test.py", 1, "failed", (), None)
        assert SECRET not in record.exc_text + record.stack_info
    finally:
        logging.setLogRecordFactory(original)


@pytest.mark.parametrize("status", [None, "Pending", "Active", "Failed"])
@pytest.mark.parametrize("permission", [
    "Microsoft.DeviceRegistry/locations/asyncOperationStatuses/read", "Microsoft.Other/unrelated/read",
])
def test_no_pending_baseline_explicitly_retains_lro_contract_and_never_recovers_a_403(
    states, ca_wire_cli, ca_pki, wire_client, mocked_response, mocker, tmp_path, caplog, status, permission,
):
    states.before["properties"]["issuer"]["status"] = status
    mocked_response.add("GET", sdk.CA_URL, json=states.before)
    mocked_response.add("POST", sdk.CA_URL + "/activate", status=202, headers={"Location": sdk.CA_LOCATION})
    mocked_response.add(
        "GET", sdk.CA_LOCATION, status=403, json={"error": {"code": "AuthorizationFailed", "message": permission}},
    )
    begin = mocker.spy(wire_client.certificate_authorities, "begin_activate")
    code, output = sdk._invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path)
    assert code != 0 and not output.strip()
    assert permission in str(ca_wire_cli.result.error)
    assert "No PendingActivation external ICA baseline" in caplog.text
    assert "activation requires action-status polling" in caplog.text
    assert "polling" not in begin.call_args.kwargs
    with pytest.raises(HttpResponseError):
        begin.spy_return.result()
    assert sum(urlsplit(call.request.url).path == RID for call in mocked_response.calls) == 1
    assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1
