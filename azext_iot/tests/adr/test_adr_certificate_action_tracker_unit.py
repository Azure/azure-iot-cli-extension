# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline HTTP and real live-command-wrapper coverage for CA action tracking."""

import json
import logging
import shlex
import weakref
from contextlib import contextmanager
from threading import Event, current_thread, main_thread
from time import monotonic
from urllib.parse import urlsplit

import pytest
import requests
from knack.util import CLIError

from azext_iot.tests.adr._certificate_action_tracker import CertificateActionTracker
from azext_iot.tests.adr import test_adr_certificate_authority_int as live
from azext_iot.tests.adr import test_adr_sdk_unit as sdk
from azext_iot.tests.adr.test_adr_sdk_unit import CA_LOCATION, CA_URL, SUBSCRIPTION

ca_wire_cli = sdk.ca_wire_cli
wire_client = sdk.wire_client


RID = urlsplit(CA_URL).path
ACTION_URL = CA_URL + "/revokeAndRotate"
SECRET = "not-a-real-secret-do-not-render"


@pytest.fixture
def tracker_factory(mocker):
    ticks = [0.0]
    token = mocker.patch(
        "azext_iot.tests.adr._certificate_action_tracker.Profile.get_raw_token",
        return_value=(("Bearer", SECRET, {}), SUBSCRIPTION, "tenant"),
    )

    def create(**kwargs):
        options = {
            "resource_id": RID, "owned": {RID}, "subscription": SUBSCRIPTION,
            "endpoint": "https://management.azure.com", "audience": "https://management.azure.com",
            "location": "centraluseuap", "cli_ctx": None, "timeout": 5, "clock": lambda: ticks[0],
            "sleeper": lambda seconds: ticks.__setitem__(0, ticks[0] + seconds),
        }
        options.update(kwargs)
        return CertificateActionTracker(**options)

    return create, ticks, token


def submit(tracker, url=ACTION_URL):
    with tracker.observe():
        return requests.post(url, timeout=1)


@pytest.mark.parametrize("initial,final,body", [
    (204, None, None), (202, 204, None), (202, 200, {}), (202, 200, {"status": "Succeeded"}),
    (202, 200, {"properties": {"provisioningState": "Succeeded"}}),
])
@pytest.mark.parametrize("action", ["activate", "revokeAndRotate"])
def test_real_cmd_wrapper_tracks_ack_without_changing_no_wait(
    initial, final, body, action, tracker_factory, ca_wire_cli, mocked_response, mocker, ca_pki, tmp_path,
):
    mocker.patch("azure.cli.testsdk.base.get_dummy_cli", return_value=ca_wire_cli)
    scenario = live.TestADRCAActions("test_microsoft_revocation_no_wait")
    scenario.setUp()
    tracker = tracker_factory[0](cli_ctx=ca_wire_cli, action=action)
    issuer = ca_pki["resource"]["properties"]["issuer"] if action == "activate" else {"issuerType": "Microsoft"}
    mocked_response.add("GET", CA_URL, json={
        "id": RID, "properties": {
            "certificateAuthorityType": "ICA", "issuer": issuer,
            "provisioningState": "Succeeded",
        },
    })
    mocked_response.add(
        "POST", CA_URL + "/" + action, status=initial,
        headers={} if initial == 204 else {"Location": CA_LOCATION, "Retry-After": "1"},
    )
    background = Event()
    if final:
        foreground = []

        def respond(_request):
            if current_thread().name != "adr-ca-status-read":
                background.set()
                return 204, {}, ""
            foreground.append(True)
            if len(foreground) == 1:
                return 202, {"Retry-After": "1"}, '{"status":"Running"}'
            return final, {}, "" if body is None else json.dumps(body)

        mocked_response.add_callback("GET", CA_LOCATION, callback=respond)
    try:
        if action == "activate":
            chain = tmp_path / "chain.pem"
            chain.write_text(ca_pki["chain"], encoding="utf-8")
            command = f"iot adr ns ca activate -n ca --ns namespace -g rg --ccf {shlex.quote(str(chain))} --no-wait"
        else:
            command = "iot adr ns ca revoke -n ca --ns namespace -g rg -y --no-wait"
        with tracker.observe():
            result = scenario.cmd(command)
        assert result.output.strip() in ("", "null")
        tracker.wait()
        assert tracker.terminal and tracker.succeeded
        assert tracker.acknowledgement_status == initial
        if final:
            assert foreground == [True, True]
            assert background.wait(timeout=5), "SDK background GET was not observed"
        calls = list(mocked_response.calls)
        assert sum(call.request.method == "POST" for call in calls) == 1
        assert sum(urlsplit(call.request.url).path == RID for call in calls) == 1
    finally:
        scenario.doCleanups()


@pytest.mark.parametrize("location", [
    CA_LOCATION, urlsplit(CA_LOCATION).path, "../../operationResults/ca",
    f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.DeviceRegistry/locations/centraluseuap/operationResults/op",
])
def test_supported_relative_and_scoped_locations(location, tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": location})
    submit(tracker)
    mocked_response.add("GET", tracker._url, status=204)
    tracker.wait()
    tracker_factory[2].assert_called_once_with(resource="https://management.azure.com", subscription=SUBSCRIPTION)
    assert tracker.succeeded


@pytest.mark.parametrize("location", [
    None, "https://foreign.invalid/operationResults/op?sig=" + SECRET,
    CA_LOCATION.replace(SUBSCRIPTION, "11111111-1111-1111-1111-111111111111"),
    CA_LOCATION.replace("/namespace/", "/other/"),
    "http://" + CA_LOCATION.removeprefix("https://"),
    "//user:password@management.azure.com" + urlsplit(CA_LOCATION).path,
    CA_URL, ACTION_URL, CA_LOCATION + "#fragment",
    CA_LOCATION.replace("/ca", "/%2e%2e"),
    "https://control-plane.prod.centraluseuap.iotadr.net/operationResults/op",
])
def test_untrackable_location_never_follows_or_uses_stale_resource(
    location, tracker_factory, mocked_response, caplog,
):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={} if location is None else {"Location": location})
    submit(tracker)
    for cleanup in (False, True):
        with pytest.raises(AssertionError, match="quarantine") as error:
            tracker.wait(cleanup=cleanup)
        assert SECRET not in str(error.value)
    assert len(mocked_response.calls) == 1
    assert SECRET not in repr(tracker) + caplog.text
    tracker_factory[2].assert_not_called()


def test_wrong_target_is_ignored_and_duplicate_post_is_diagnosed(tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    wrong = ACTION_URL.replace("/ca/", "/other/")
    mocked_response.add("POST", wrong, status=204)
    mocked_response.add("POST", ACTION_URL, status=204)
    with tracker.observe():
        requests.post(wrong, timeout=1)
    with pytest.raises(AssertionError, match="No exact"):
        tracker.wait()
    with tracker.observe():
        requests.post(ACTION_URL, timeout=1)
        requests.post(ACTION_URL, timeout=1)
    with pytest.raises(AssertionError, match="Duplicate"):
        tracker.wait(cleanup=True)
    assert not tracker.terminal


def test_lost_post_acknowledgement_requires_quarantine(tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, body=requests.ConnectionError("POST acknowledgement lost"))
    with pytest.raises(requests.ConnectionError, match="acknowledgement lost"):
        submit(tracker)
    with pytest.raises(AssertionError, match="no tracking URL; quarantine"):
        tracker.wait(cleanup=True)
    assert not tracker.terminal and tracker.acknowledgement_status is None
    assert len(mocked_response.calls) == 1
    tracker_factory[2].assert_not_called()


def test_live_fixture_refuses_operation_replay(tracker_factory, mocker):
    scenario = live.TestADRCAActions("test_microsoft_revocation_no_wait")
    tracker = tracker_factory[0]()
    scenario._ca_actions = {RID: tracker}
    command = mocker.patch.object(scenario, "cmd")
    with pytest.raises(AssertionError, match="Refusing to replay"):
        scenario._tracked_ca_action({"id": RID}, "must not execute", "revokeAndRotate")
    assert scenario._ca_actions[RID] is tracker
    command.assert_not_called()


@pytest.mark.parametrize("status", ["Failed", "Canceled"])
def test_failed_operation_is_not_success_but_is_safe_to_cleanup(status, tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    mocked_response.add("GET", CA_LOCATION, json={"status": status, "error": {"message": SECRET}})
    submit(tracker)
    with pytest.raises(AssertionError, match="terminal Failed/Canceled") as error:
        tracker.wait()
    assert SECRET not in str(error.value)
    tracker.wait(cleanup=True)
    assert tracker.terminal and not tracker.succeeded


@pytest.mark.parametrize("body", [{"status": "Running"}, {"properties": {"provisioningState": "Updating"}}])
def test_nonterminal_deadline_and_read_only_cleanup_reconciliation(body, tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    pending = mocked_response.add("GET", CA_LOCATION, json=body)
    submit(tracker)
    with pytest.raises(AssertionError, match="Timed out"):
        tracker.wait()
    assert tracker_factory[1][0] == 5
    mocked_response.remove(pending)
    mocked_response.add("GET", CA_LOCATION, status=204)
    tracker.wait(cleanup=True)
    assert tracker.succeeded
    assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1


@pytest.mark.parametrize("slow", ["auth", "request"])
def test_deadline_includes_authentication_and_request_time(slow, tracker_factory, mocked_response):
    factory, ticks, token = tracker_factory
    tracker = factory()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    submit(tracker)

    def expire(*_args, **_kwargs):
        ticks[0] = 6
        return (("Bearer", SECRET, {}), SUBSCRIPTION, "tenant") if slow == "auth" else (204, {}, "")

    if slow == "auth":
        token.side_effect = expire
    else:
        mocked_response.add_callback("GET", CA_LOCATION, callback=expire)
    with pytest.raises(AssertionError, match="Timed out"):
        tracker.wait()
    assert not tracker.terminal
    assert len(mocked_response.calls) == (1 if slow == "auth" else 2)


@pytest.mark.parametrize("failure", ["auth", "transport", "redirect", "subscription", "json", "shape"])
def test_errors_do_not_disclose_credentials_or_signed_urls(
    failure, tracker_factory, mocked_response, caplog, capsys,
):
    factory, _, token = tracker_factory
    tracker = factory()
    signed = CA_LOCATION + "?sig=" + SECRET
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": signed, "X-Credential": SECRET})
    submit(tracker)
    if failure == "auth":
        token.side_effect = CLIError(SECRET)
    elif failure == "subscription":
        token.return_value = (("Bearer", SECRET, {}), "foreign", "tenant")
    elif failure == "transport":
        mocked_response.add("GET", signed, body=requests.ConnectionError(SECRET))
    elif failure == "redirect":
        mocked_response.add("GET", signed, status=302, headers={"Location": "https://foreign.invalid/" + SECRET})
    elif failure == "json":
        mocked_response.add("GET", signed, body=SECRET)
    else:
        mocked_response.add("GET", signed, json=[SECRET])
    with pytest.raises(AssertionError) as error:
        tracker.wait()
    output = capsys.readouterr()
    assert SECRET not in str(error.value) + repr(tracker) + caplog.text + output.out + output.err
    assert error.value.__context__ is None or error.value.__suppress_context__
    assert not tracker.terminal


@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize("completion", ["pending", "missing", "success", "failed"])
@pytest.mark.parametrize("action", ["activate", "revokeAndRotate"])
def test_owned_cleanup_quarantines_dependencies_or_reconciles_terminal_action(
    primary, completion, action, tracker_factory, mocked_response, mocker, caplog,
):
    scenario = live.TestADRCAActions("test_microsoft_revocation_no_wait")
    mocker.patch.object(live, "TEST_SUBSCRIPTION", SUBSCRIPTION)
    mocker.patch.object(live, "TEST_RG", "rg")
    mocker.patch.object(live, "generate_adr_namespace_name", return_value="namespace")
    mocker.patch.object(scenario, "_ready")
    mocker.patch.object(live, "resource_is_absent", side_effect=[True, True, True, False, False, False])
    mocker.patch.object(live, "wait_for_resource_absent")
    commands = mocker.patch.object(scenario, "cmd", return_value=mocker.Mock(
        get_output_in_json=mocker.Mock(return_value={"id": RID}),
    ))
    owned_ica = RID.rsplit("/", 1)[0] + "/ica"
    action_url = "https://management.azure.com" + owned_ica + "/" + action
    tracker = tracker_factory[0](resource_id=owned_ica, owned={owned_ica}, action=action)
    mocked_response.add(
        "POST", action_url, status=202,
        headers={} if completion == "missing" else {"Location": CA_LOCATION},
    )
    if completion != "missing":
        mocked_response.add("GET", CA_LOCATION, json={"status": {
            "pending": "Running", "success": "Succeeded", "failed": "Failed",
        }[completion]})

    def run():
        with scenario._owned_target(microsoft=True):
            scenario._ca_actions[owned_ica] = tracker
            submit(tracker, action_url)
            if primary:
                raise CLIError("primary scenario failure")

    if primary:
        with pytest.raises(CLIError, match="primary scenario failure"):
            run()
    elif completion in ("pending", "missing"):
        with pytest.raises(AssertionError, match="ADR cleanup failed"):
            run()
    else:
        run()
    deletes = [call.args[0] for call in commands.call_args_list if " delete " in call.args[0]]
    if completion in ("pending", "missing"):
        assert not deletes
        for suffix in ("", "/certificateAuthorities/root", "/certificateAuthorities/ica"):
            assert RID.split("/certificateAuthorities/")[0] + suffix in caplog.text
        assert "Dependent cleanup has not completed" in caplog.text
    else:
        assert len(deletes) == 3
        assert "-n ica " in deletes[0] and "-n root " in deletes[1] and "iot adr ns delete " in deletes[2]


@pytest.mark.parametrize("options", [
    {"owned": set()}, {"subscription": "foreign"}, {"endpoint": "https://foreign.invalid"},
    {"endpoint": "http://management.azure.com"}, {"audience": "https://graph.microsoft.com"},
    {"resource_id": RID + "?secret=" + SECRET}, {"action": "delete"},
])
def test_tracker_rejects_unowned_or_unapproved_scope_before_submission(options, tracker_factory):
    with pytest.raises(AssertionError, match="owned target and approved ARM scope"):
        tracker_factory[0](**options)


def test_transport_debug_logging_cannot_render_signed_query(tracker_factory, mocked_response, caplog):
    tracker = tracker_factory[0]()
    signed = CA_LOCATION + "?sig=" + SECRET
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": signed})
    submit(tracker)
    logger = logging.getLogger("urllib3.connectionpool")
    filters = list(logger.filters)
    caplog.set_level(logging.DEBUG, logger="urllib3.connectionpool")

    def respond(_request):
        logger.debug("GET %s", signed)
        return 204, {}, ""

    mocked_response.add_callback("GET", signed, callback=respond)
    tracker.wait()
    assert SECRET not in caplog.text
    assert logger.filters == filters


def test_command_duration_counts_toward_deadline_even_for_inline_completion(tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=204)
    submit(tracker)
    tracker_factory[1][0] = 6
    with pytest.raises(AssertionError, match="Timed out"):
        tracker.wait()
    tracker.wait(cleanup=True)
    assert len(mocked_response.calls) == 1


def test_canary_endpoint_and_profile_auth_are_preserved(tracker_factory, mocked_response, mocker):
    endpoint = "https://centraluseuap.management.azure.com"
    tracker = tracker_factory[0](endpoint=endpoint)
    action = endpoint + RID + "/revokeAndRotate"
    location = endpoint + urlsplit(CA_LOCATION).path
    mocked_response.add("POST", action, status=202, headers={"Location": location, "X-Unknown": "unchanged"})
    response = submit(tracker, action)
    assert response.status_code == 202
    assert response.headers["Location"] == location and response.headers["X-Unknown"] == "unchanged"
    netrc = mocker.patch("requests.sessions.get_netrc_auth", side_effect=AssertionError("Unexpected netrc authentication"))
    mocked_response.add("GET", location, status=204)
    tracker.wait()
    netrc.assert_not_called()
    tracker_factory[2].assert_called_once_with(resource="https://management.azure.com", subscription=SUBSCRIPTION)
    assert mocked_response.calls[-1].request.headers["Authorization"] == "Bearer " + SECRET
    assert all(urlsplit(call.request.url).netloc == urlsplit(endpoint).netloc for call in mocked_response.calls)


@pytest.mark.parametrize("body", [
    {"error": {"message": SECRET}}, {"properties": {}},
    {"status": "Succeeded", "properties": {"provisioningState": "Failed"}},
])
def test_ambiguous_or_conflicting_body_cannot_fake_success(body, tracker_factory, mocked_response):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    mocked_response.add("GET", CA_LOCATION, json=body)
    submit(tracker)
    with pytest.raises(AssertionError):
        tracker.wait()
    assert not tracker.succeeded


@pytest.mark.parametrize("acknowledgement", [204, 202])
def test_opted_in_live_scenario_uses_real_wrapper_and_operation_evidence(
    acknowledgement, tracker_factory, ca_wire_cli, mocked_response, mocker, monkeypatch,
):
    monkeypatch.setenv("azext_iot_adr_revoke_certificates", "true")
    mocker.patch("azure.cli.testsdk.base.get_dummy_cli", return_value=ca_wire_cli)
    scenario = live.TestADRCAActions("test_microsoft_revocation_no_wait")
    scenario.setUp()
    resource_id = RID.rsplit("/", 1)[0] + "/ica"
    resource_url = "https://management.azure.com" + resource_id
    before = {"id": resource_id, "properties": {
        "certificateAuthorityType": "ICA", "issuer": {"issuerType": "Microsoft"}, "provisioningState": "Succeeded",
    }}
    admitted = []

    @contextmanager
    def owned(microsoft=False):
        assert microsoft
        admitted.append(True)
        scenario._owned_ca_ids = {resource_id, resource_id.rsplit("/", 1)[0] + "/root"}
        scenario._ca_actions = {}
        yield "--ns namespace -g rg", before
        scenario._ca_actions[resource_id].wait(cleanup=True)

    mocker.patch.object(scenario, "_owned_target", owned)
    mocker.patch.object(scenario, "_ready", return_value=before)
    mocker.patch.object(scenario, "_assert_raw_fields")
    mocker.patch.object(live, "TEST_SUBSCRIPTION", SUBSCRIPTION)
    mocker.patch.object(live, "TEST_ARM_ENDPOINT", "https://management.azure.com")
    mocker.patch.object(live, "TEST_ARM_RESOURCE", "https://management.azure.com")
    mocker.patch.object(live, "TEST_LOCATION", "centraluseuap")
    factory = tracker_factory[0]
    mocker.patch.object(live, "CertificateActionTracker", side_effect=lambda **kwargs: factory(**kwargs))
    mocked_response.add("GET", resource_url.rsplit("/", 1)[0] + "/root", json={
        "properties": {"certificateAuthorityType": "Root", "issuer": {"issuerType": "Microsoft"}},
    })
    mocked_response.add("GET", resource_url, json=before)
    mocked_response.add(
        "POST", resource_url + "/revokeAndRotate", status=acknowledgement,
        headers={} if acknowledgement == 204 else {"Location": CA_LOCATION},
    )
    background = Event()
    if acknowledgement == 202:
        def respond(_request):
            if current_thread() is not main_thread() and current_thread().name != "adr-ca-status-read":
                background.set()
            return 204, {}, ""

        mocked_response.add_callback("GET", CA_LOCATION, callback=respond)
    try:
        scenario._microsoft_revocation(no_wait=True)
        assert admitted == [True]
        assert scenario._ca_actions[resource_id].succeeded
        assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1
        if acknowledgement == 202:
            assert background.wait(timeout=5)
    finally:
        scenario.doCleanups()


@pytest.mark.parametrize("failure", ["invalid-chain", "wrong-revoke", "wrong-root", "wrong-ica", "missing"])
@pytest.mark.parametrize("completion", ["Succeeded", "Failed", "Running"])
def test_negative_live_commands_track_unexpected_post_before_cleanup(
    failure, completion, tracker_factory, mocked_response, mocker, monkeypatch, caplog,
):
    scenario = live.TestADRCAActions("test_external_activation_recipe")
    mocker.patch.object(live, "TEST_SUBSCRIPTION", SUBSCRIPTION)
    mocker.patch.object(live, "TEST_RG", "rg")
    mocker.patch.object(live, "TEST_ARM_ENDPOINT", "https://management.azure.com")
    mocker.patch.object(live, "TEST_ARM_RESOURCE", "https://management.azure.com")
    mocker.patch.object(live, "TEST_LOCATION", "centraluseuap")
    mocker.patch.object(live, "generate_adr_namespace_name", return_value="namespace")
    mocker.patch.object(scenario, "_ready")
    mocker.patch.object(scenario, "_sign_service_csr", return_value="unused.pem")
    mocker.patch.object(live, "negative_certificate_chains", return_value=(
        [("malformed", "invalid PEM", ("malformed",))] if failure == "invalid-chain" else []
    ))
    microsoft = failure in ("wrong-root", "wrong-ica")
    monkeypatch.setenv("azext_iot_adr_revoke_certificates", "true")
    count = 3 if microsoft else 2
    mocker.patch.object(live, "resource_is_absent", side_effect=[True] * count + [False] * count)
    mocker.patch.object(live, "wait_for_resource_absent")
    owned_id = RID.rsplit("/", 1)[0] + "/ica"
    target = owned_id.rsplit("/", 1)[0] + "/" + (
        "root" if failure == "wrong-root" else "nonexistent-owned-ca" if failure == "missing" else "ica"
    )
    action = "revokeAndRotate" if failure == "wrong-revoke" else "activate"
    action_url = "https://management.azure.com" + target + "/" + action
    events = []
    mocked_response.add("POST", action_url, status=202, headers={"Location": CA_LOCATION})

    def status(_request):
        events.append("GET")
        return 200, {}, json.dumps({"status": completion})

    mocked_response.add_callback("GET", CA_LOCATION, callback=status)
    trackers = []

    def factory(**kwargs):
        tracker = tracker_factory[0](**kwargs)
        trackers.append(tracker)
        return tracker

    mocker.patch.object(live, "CertificateActionTracker", side_effect=factory)

    def command(text):
        if " delete " in text:
            events.append("DELETE")
        if " activate " in text or " revoke " in text:
            should_post = (
                (" revoke " in text and failure == "wrong-revoke")
                or (" activate " in text and (
                    failure == "invalid-chain" or (failure == "missing" and "nonexistent-owned-ca" in text)
                    or (failure == "wrong-root" and "-n root " in text)
                    or (failure == "wrong-ica" and "-n ica " in text)
                ))
            )
            if should_post:
                events.append("POST")
                requests.post(action_url, timeout=1)
            if " revoke " in text:
                raise CLIError("requires an ICA with issuerType 'Microsoft'")
            if microsoft:
                raise CLIError("requires an ICA with issuerType 'External'")
            if "nonexistent-owned-ca" in text:
                raise CLIError("(ResourceNotFound) missing")
            raise CLIError("malformed")
        return mocker.Mock(get_output_in_json=lambda: {"id": owned_id, "properties": {}})

    mocker.patch.object(scenario, "cmd", side_effect=command)
    with pytest.raises(AssertionError, match="Unexpected owned action POST"):
        if microsoft:
            scenario._microsoft_revocation()
        else:
            scenario._external_activation()
    assert target in scenario._ca_actions
    assert events[0:2] == ["POST", "GET"]
    assert sum(event == "POST" for event in events) == 1
    if completion == "Running":
        assert "DELETE" not in events
        assert "Dependent cleanup has not completed" in caplog.text
        assert RID.split("/certificateAuthorities/")[0] in caplog.text
    else:
        assert events == ["POST", "GET"] + ["DELETE"] * count
    with pytest.raises(AssertionError, match="Refusing to replay"):
        scenario._tracked_ca_action({"id": target}, "must not run", action)


@pytest.mark.parametrize("stage", ["auth", "request", "decode"])
@pytest.mark.parametrize("cleanup", [False, True])
def test_real_wall_clock_deadline_discards_late_reads(
    stage, cleanup, tracker_factory, mocked_response, mocker,
):
    factory, _, token = tracker_factory
    tracker = factory(timeout=0.5, clock=monotonic, sleeper=lambda _seconds: None)
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    submit(tracker)
    entered, finished, release = Event(), Event(), Event()

    def delayed(value):
        entered.set()
        try:
            # Leave startup margin on Windows, but hold the stage beyond the
            # asserted caller budget: a synchronous read would take 3 seconds.
            release.wait(3)
            return value
        finally:
            finished.set()

    if stage == "auth":
        token.side_effect = lambda **_kwargs: delayed((("Bearer", SECRET, {}), SUBSCRIPTION, "tenant"))
    elif stage == "request":
        mocked_response.add_callback("GET", CA_LOCATION, callback=lambda _request: delayed((204, {}, "")))
    else:
        mocked_response.add("GET", CA_LOCATION, json={"status": "Succeeded"})
        mocker.patch.object(requests.Response, "json", side_effect=lambda: delayed({"status": "Succeeded"}))
    try:
        start = monotonic()
        with pytest.raises(AssertionError, match="Timed out"):
            tracker.wait(cleanup=cleanup)
        elapsed = monotonic() - start
        assert entered.is_set() and elapsed < 1
        assert not finished.is_set()
        reader = tracker._reader
        with pytest.raises(AssertionError, match="in flight|Timed out"):
            tracker.wait(cleanup=True)
        assert tracker._reader is reader
        assert not tracker.terminal and not tracker.succeeded
    finally:
        release.set()
        if tracker._reader is not None:
            tracker._reader.join(3)
    assert finished.is_set()
    assert not reader.is_alive()
    assert not tracker.terminal and not tracker.succeeded
    assert sum(call.request.method == "GET" for call in mocked_response.calls) == (0 if stage == "auth" else 1)


def test_real_sdk_ack_and_background_debug_logs_are_redacted_after_observe(
    tracker_factory, wire_client, mocked_response, caplog, mocker,
):
    signed = CA_LOCATION + "?review-query=" + SECRET
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": signed, "Retry-After": "0"})
    mocked_response.add("GET", signed, status=204)
    caplog.set_level(logging.DEBUG)
    # Earlier real CLI invocations may have reconfigured SDK logging.
    sdk_loggers = {
        logging.getLogger("azure.core.pipeline.policies._universal"),
        wire_client._config.http_logging_policy.logger,
        logging.getLogger("azure.core.pipeline.transport"),
    }
    for sdk_logger in sdk_loggers:
        caplog.set_level(logging.DEBUG, logger=sdk_logger.name)
        mocker.patch.object(sdk_logger, "disabled", False)
        mocker.patch.object(sdk_logger, "handlers", [caplog.handler])
        mocker.patch.object(sdk_logger, "propagate", False)
    released, started = Event(), Event()
    from azure.core.polling.base_polling import LROBasePolling

    original = LROBasePolling.run

    def deferred(polling):
        started.set()
        assert released.wait(5)
        return original(polling)

    mocker.patch.object(LROBasePolling, "run", deferred)
    try:
        with tracker.observe():
            poller = wire_client.certificate_authorities.begin_revoke_and_rotate("rg", "namespace", "ca")
        assert started.wait(5)
        assert not poller.done()
        tracker_repr = repr(tracker)
        reference = weakref.ref(tracker)
        del tracker
        assert reference() is None
    finally:
        released.set()
    poller.result(timeout=5)
    assert poller.done()
    assert mocked_response.calls[0].response.headers["Location"] == signed
    assert any(call.request.url == signed for call in mocked_response.calls if call.request.method == "GET")
    assert any("Location" in record.getMessage() for record in caplog.records)
    assert any("Request URL" in record.getMessage() and "operationResults" in record.getMessage()
               for record in caplog.records)
    try:
        raise requests.ConnectionError("HTTP 500 failed GET " + signed)
    except requests.ConnectionError:
        logging.getLogger("azure.core.pipeline.transport").exception("Poll failed %s", signed)
    assert "HTTP 500 failed GET" in caplog.text
    for record in caplog.records:
        assert SECRET not in str(record.msg) + repr(record.args) + str(record.exc_text) + str(record.exc_info)
    assert SECRET not in caplog.text + tracker_repr


def test_reader_does_not_change_outer_process_timer(tracker_factory, mocked_response):
    import signal

    alarm = getattr(signal, "SIGALRM", None)
    timer = getattr(signal, "ITIMER_REAL", None)
    get_timer = getattr(signal, "getitimer", None)
    set_timer = getattr(signal, "setitimer", None)
    if alarm is None or timer is None or not callable(get_timer) or not callable(set_timer):
        pytest.skip("POSIX timer assertion; bounded-read tests also run natively on Windows.")
    previous_handler = signal.getsignal(alarm)
    previous_timer = get_timer(timer)
    if previous_timer[0]:
        # Never replace the runner's actual item timeout.
        tracker = tracker_factory[0]()
        mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
        mocked_response.add("GET", CA_LOCATION, status=204)
        submit(tracker)
        tracker.wait()
        assert signal.getsignal(alarm) == previous_handler
        remaining, interval = get_timer(timer)
        assert 0 < remaining <= previous_timer[0] and interval == previous_timer[1]
        return
    try:
        set_timer(timer, 10, 2)
        tracker = tracker_factory[0]()
        mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
        mocked_response.add("GET", CA_LOCATION, status=204)
        submit(tracker)
        tracker.wait()
        remaining, interval = get_timer(timer)
        assert 9 < remaining < 10 and interval == 2
        assert signal.getsignal(alarm) == previous_handler
    finally:
        set_timer(timer, 0)


@pytest.mark.parametrize("actual", ["activate", "revokeAndRotate"])
def test_negative_observer_rejects_either_action_on_target(actual, tracker_factory, mocked_response):
    tracker = tracker_factory[0](action="activate")
    mocked_response.add("POST", CA_URL + "/" + actual, status=202, headers={"Location": CA_LOCATION})
    mocked_response.add("GET", CA_LOCATION, status=204)
    with tracker.observe(negative=True):
        requests.post(CA_URL + "/" + actual, timeout=1)
    with pytest.raises(AssertionError, match="Unexpected owned action POST"):
        tracker.assert_no_submission()
    assert tracker.submitted and not tracker.terminal
    tracker.wait(cleanup=True)
    assert tracker.terminal


def test_cleanup_keeps_original_absolute_budget(tracker_factory, mocked_response):
    factory, ticks, _ = tracker_factory
    tracker = factory()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    mocked_response.add("GET", CA_LOCATION, json={"status": "Running"})
    submit(tracker)
    with pytest.raises(AssertionError, match="Timed out"):
        tracker.wait(cleanup=True)
    deadline = tracker._cleanup_deadline
    count = len(mocked_response.calls)
    ticks[0] += 1
    with pytest.raises(AssertionError, match="Timed out"):
        tracker.wait(cleanup=True)
    assert tracker._cleanup_deadline == deadline
    assert len(mocked_response.calls) == count


def test_reader_works_without_posix_signal_capabilities(tracker_factory, mocked_response, monkeypatch):
    import sys
    from types import SimpleNamespace

    # Isolate the Windows capability surface without changing pytest's real
    # signal module or operating-system identity.
    monkeypatch.setitem(sys.modules, "signal", SimpleNamespace())
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=202, headers={"Location": CA_LOCATION})
    mocked_response.add("GET", CA_LOCATION, status=204)
    submit(tracker)
    tracker.wait()
    assert tracker.succeeded


@pytest.mark.parametrize("location", [
    CA_LOCATION, CA_LOCATION.replace("https:", "HTTPS:"), "../../operationResults/ca",
])
def test_log_redaction_is_idempotent_and_preserves_record_severity(location, tracker_factory, mocked_response, caplog):
    tracker = tracker_factory[0]()
    mocked_response.add("POST", ACTION_URL, status=204)
    submit(tracker)
    factory = logging.getLogRecordFactory()
    with tracker.observe():
        pass
    assert logging.getLogRecordFactory() is factory
    logging.getLogger("azure.core.pipeline.transport").error(
        "HTTP 500 failed polling %(url)s for %(resource)s", {"url": location + "?opaque=" + SECRET, "resource": RID},
    )
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert RID in record.getMessage() and "HTTP 500 failed polling" in record.getMessage()
    assert SECRET not in record.msg + repr(record.args)
