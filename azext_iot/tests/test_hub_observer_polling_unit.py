# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Portable observer proofs with real SDK/CLI calls over an in-memory transport."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests
from azure.cli.core._profile import Profile
from azure.cli.core.azclierror import RequiredArgumentMissingError, ResourceNotFoundError

from azext_iot.tests import _hub_ownership as ownership, _hub_phase_runner as runner
from azext_iot.tests.test_hub_ownership_transport_unit import Wire, Credential, HUB, create_hub


ROOT = Path(__file__).resolve().parents[2]
OPERATION = HUB + "/operations/offline"
NEGATIVE = HUB.replace(ownership.GROUP, "fakerg").rsplit("/", 1)[0] + "/fakehub"
INVALID_POLL_URLS = [
    "http://management.azure.com" + OPERATION,
    "https://unapproved.invalid" + OPERATION,
    "https://user@management.azure.com" + OPERATION,
    "https://management.azure.com:443" + OPERATION,
    ownership.ARM + OPERATION.replace(ownership.SUBSCRIPTION, "foreign-subscription"),
    ownership.ARM + OPERATION.replace(ownership.GROUP, "foreign-group"),
    ownership.ARM + OPERATION.replace("/microsoft.devices/", "/microsoft.devices//"),
    ownership.ARM + OPERATION + "/../escape",
    ownership.ARM + OPERATION + "/./escape",
    ownership.ARM + OPERATION + "/%2fescape",
    ownership.ARM + OPERATION + "/\\escape",
    ownership.ARM + OPERATION + " whitespace",
    ownership.ARM + OPERATION + "#fragment",
    "//management.azure.com" + OPERATION,
    f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups",
]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    wire = Wire()
    monkeypatch.setattr(requests.Session, "send", lambda _session, request, **kwargs: wire.send(request, **kwargs))
    monkeypatch.setattr(Profile, "get_subscription", lambda *_args, **_kwargs: {
        "id": ownership.SUBSCRIPTION, "name": "offline", "state": "Enabled", "isDefault": True,
        "tenantId": "offline", "user": {"name": "offline", "type": "user"},
    })

    def read(method, resource_id, api):
        request = requests.Request(method, ownership.ARM + resource_id, params={"api-version": api}).prepare()
        status, resource, _ = wire.handle(request)
        return status, resource

    arm = SimpleNamespace(request=Mock(side_effect=read), inventory=Mock(return_value=[]), deadline=None)
    scope = ownership.ProcessScope()
    scope.install()
    observer = ownership.Observer(tmp_path / "ownership.json", "uid", "entra", arm)
    wire.receipt = observer.path
    observer.install()
    try:
        yield observer, arm, wire
    finally:
        observer.restore()
        scope.restore()


@pytest.mark.parametrize("path", [
    NEGATIVE,
    HUB.replace("/microsoft.devices/", "/microsoft.devices//"),
    f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups",
])
def test_uncorrelated_ordinary_get_does_not_become_a_polling_violation(transport, path):
    observer, _, wire = transport
    create_hub(wire)
    before = deepcopy(observer.data)
    assert wire.submit("GET", path).status_code == 404
    assert observer.data == before


def accept(observer, method="PUT", header="azure-asyncoperation"):
    observer.prepare(method, HUB, "test", {})
    observer.complete(HUB, 202, {header: ownership.ARM + OPERATION})
    return observer.data["resources"][HUB]["mutations"][-1]


@pytest.mark.parametrize("body", [[], ["not-an-operation"], {"status": {"not": "an operation status"}}])
def test_uncorrelated_get_body_is_not_parsed_as_an_operation(transport, monkeypatch, body):
    observer, _, wire = transport
    create_hub(wire)
    accept(observer)
    before = deepcopy(observer.data)
    original = wire.handle
    ordinary = HUB + "/ordinary-read"

    def handle(request):
        if urlsplit(request.url).path.casefold() == ordinary:
            return 200, body, {}
        return original(request)

    monkeypatch.setattr(wire, "handle", handle)
    assert wire.submit("GET", ordinary).status_code == 200
    assert observer.data == before


@pytest.mark.parametrize("url", INVALID_POLL_URLS)
@pytest.mark.parametrize("header", ["Azure-AsyncOperation", "Location"])
def test_acknowledgement_url_validation_stays_strict_and_durable(transport, header, url):
    observer, _, wire = transport
    create_hub(wire)
    for validate in (ownership.arm_location, ownership.polling_key):
        with pytest.raises(ownership.OwnershipError, match="polling URL"):
            validate(url)
    observer.prepare("PUT", HUB, "test", {})
    with pytest.raises(ownership.OwnershipError, match="response Location/polling metadata"):
        observer.complete(HUB, 202, {header: url + "?sig=private-poll-query"})
    mutation = observer.data["resources"][HUB]["mutations"][-1]
    assert mutation["responseError"] and observer.data["resources"][HUB]["uncertain"]
    assert not mutation.get("pollingSucceeded") and not mutation.get("reconciled")
    assert "private-poll-query" not in observer.path.read_text(encoding="utf-8")
    before = len(wire.calls)
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        wire.submit("PUT", HUB, {})
    assert len(wire.calls) == before


@pytest.mark.parametrize("url", INVALID_POLL_URLS)
def test_correlated_continuation_cannot_escape_strict_url_validation(transport, monkeypatch, url):
    observer, _, wire = transport
    create_hub(wire)
    mutation = accept(observer, header="location")
    before = deepcopy(mutation)
    original = wire.handle

    def handle(request):
        if urlsplit(request.url).path.casefold() == OPERATION:
            return 202, None, {"location": url}
        return original(request)

    monkeypatch.setattr(wire, "handle", handle)
    with pytest.raises(ownership.OwnershipError):
        wire.submit("GET", OPERATION)
    assert mutation == before
    assert observer.data["violations"]
    assert wire.calls[-1][0] == "GET" and urlsplit(wire.calls[-1][1]).path.casefold() == OPERATION


@pytest.mark.parametrize("url", [
    ownership.ARM + NEGATIVE,
    ownership.ARM + HUB.replace("/microsoft.devices/", "/microsoft.devices//"),
    f"{ownership.ARM}/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups",
])
def test_even_a_forged_correlated_digest_must_pass_strict_poll_path_validation(transport, url):
    observer, _, wire = transport
    create_hub(wire)
    mutation = accept(observer)
    mutation["polling"]["azure-asyncoperation"] = ownership._polling_fingerprint(urlsplit(url))
    with pytest.raises(ownership.OwnershipError, match="polling URL"):
        ownership.observe_poll(observer.data, url, 200, {"status": "Succeeded"})
    assert not mutation.get("pollingSucceeded") and not mutation.get("reconciled")


@pytest.mark.parametrize("url", INVALID_POLL_URLS[:5])
def test_uncorrelated_poll_observation_cannot_cross_origin_or_subscription(transport, url):
    observer, _, _ = transport
    with pytest.raises(ownership.OwnershipError, match="polling URL"):
        ownership.observe_poll(observer.data, url, 200, {"status": "Succeeded"})
    assert not observer.data["resources"]


def test_foreign_arm_host_is_blocked_before_transport(transport):
    _, _, wire = transport
    with pytest.raises(ownership.OwnershipError, match="Unapproved ARM endpoint"):
        requests.Session().get("https://unapproved.invalid" + HUB)
    assert not wire.calls


@pytest.mark.parametrize("change", ["retag", "remove-tag", "wrong-id"])
def test_genuine_owned_root_changes_still_fail_with_details(transport, change):
    observer, _, wire = transport
    create_hub(wire)
    if change == "retag":
        wire.resources[HUB]["tags"][ownership.OWNER_TAG] = "foreign"
    elif change == "remove-tag":
        del wire.resources[HUB]["tags"][ownership.OWNER_TAG]
    else:
        wire.resources[HUB]["id"] = NEGATIVE
    with pytest.raises(ownership.OwnershipError, match="no longer belongs"):
        wire.submit("GET", HUB)
    details = observer.data["violationDetails"][-1]
    assert details["reason"] == "Observed root ownership changed"
    assert details["resourcePath"] == HUB and observer.data["violations"]
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 1


@pytest.mark.parametrize("header,status,state,succeeded", [
    ("azure-asyncoperation", 200, "Succeeded", True),
    ("azure-asyncoperation", 202, "Succeeded", False),
    ("azure-asyncoperation", 204, "", False),
    ("azure-asyncoperation", 404, "", False),
    ("location", 200, "Succeeded", True),
    ("location", 204, "", True),
    ("location", 202, "Succeeded", False),
    ("location", 404, "", False),
])
def test_terminal_delete_poll_never_substitutes_for_exact_absence(transport, header, status, state, succeeded):
    observer, _, wire = transport
    create_hub(wire)
    mutation = accept(observer, method="DELETE", header=header)
    ownership.observe_poll(observer.data, ownership.ARM + OPERATION, status, {"status": state})
    assert bool(mutation.get("pollingSucceeded")) == succeeded
    assert ownership.pending_mutation(mutation) and "absenceConfirmed" not in mutation
    ownership.observe_get(observer.data, NEGATIVE, 404, None)
    assert ownership.pending_mutation(mutation) and "absenceConfirmed" not in mutation
    ownership.observe_get(observer.data, HUB, 404, None)
    assert mutation["absenceConfirmed"] and mutation["reconciled"]
    assert not observer.data["resources"][HUB]["uncertain"]


@pytest.mark.parametrize("status", [None, 408, 429, 500])
def test_root_absence_never_resolves_unacknowledged_or_ambiguous_delete(transport, status):
    observer, _, wire = transport
    create_hub(wire)
    observer.prepare("DELETE", HUB, "test", {})
    if status is not None:
        observer.complete(HUB, status)
    mutation = observer.data["resources"][HUB]["mutations"][-1]
    ownership.observe_get(observer.data, HUB, 404, None)
    assert not mutation.get("absenceConfirmed") and not mutation.get("reconciled")
    assert observer.data["resources"][HUB]["uncertain"]
    before = len(wire.calls)
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        wire.submit("DELETE", HUB)
    assert len(wire.calls) == before


@pytest.mark.parametrize("state", ["Failed", "Canceled", "Cancelled"])
def test_failed_delete_poll_cannot_be_rehabilitated_by_absence_or_replayed(transport, state):
    observer, _, wire = transport
    create_hub(wire)
    mutation = accept(observer, method="DELETE")
    ownership.observe_poll(observer.data, ownership.ARM + OPERATION, 200, {"status": state})
    ownership.observe_get(observer.data, HUB, 404, None)
    assert mutation["pollingFailed"] and not mutation.get("reconciled")
    before = len(wire.calls)
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        wire.submit("DELETE", HUB)
    assert len(wire.calls) == before


@pytest.mark.parametrize("test_name,negative_reads", [
    ("test_mirgate_hub_dataplane_error", 1),
    ("test_export_import_migrate_missing_hubs_error", 4),
])
def test_actual_negative_state_body_retains_assertions_without_poisoning_ownership(
    transport, monkeypatch, mocker, test_name, negative_reads,
):
    from azure.cli.core import get_default_cli
    from azext_iot.iothub.providers import discovery
    from azext_iot.sdk.iothub.mgmt import IotHubClient
    from azext_iot.tests.dps.core.test_dps_phase_runtime_unit import _real_cli
    from azext_iot.tests.iothub.state import _state_helpers

    observer, _, wire = transport
    create_hub(wire)
    wire.resources[HUB].update(sku={"tier": "Standard"}, resourcegroup=ownership.GROUP)
    wire.resources[HUB]["properties"]["hostName"] = "offline.azure-devices.net"
    client = IotHubClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM, polling_interval=0)
    monkeypatch.setattr(discovery, "iot_hub_service_factory", lambda _ctx: client)
    monkeypatch.setattr(discovery, "get_subscription_id", lambda _ctx: ownership.SUBSCRIPTION)
    monkeypatch.setenv("AZURE_DEFAULTS_IOTHUB-DATA-AUTH-TYPE", "login")
    mocker.patch.object(get_default_cli(), "commands_loader_cls")
    cli = _real_cli(mocker)
    cli.capture_stderr = False
    cli.user_subscription = ownership.SUBSCRIPTION
    source = ROOT / "azext_iot/tests/iothub/state/test_hub_state_int.py"
    definition = next(
        node for node in ast.parse(source.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == test_name
    )
    definition.decorator_list = []
    namespace = {
        "ResourceNotFoundError": ResourceNotFoundError,
        "RequiredArgumentMissingError": RequiredArgumentMissingError,
        "state": SimpleNamespace(cli=cli, DATAPLANE=_state_helpers.DATAPLANE),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), str(source), "exec"), namespace)
    arguments = [[{"name": HUB.rsplit("/", 1)[1], "rg": ownership.GROUP}]] if definition.args.args else []
    namespace[definition.name](*arguments)
    assert isinstance(cli.get_error(), ResourceNotFoundError)
    assert sum(
        method == "GET" and urlsplit(url).path.casefold() == NEGATIVE for method, url, *_ in wire.calls
    ) == negative_reads
    assert observer.data["violations"] == []
    assert observer.data.get("violationDetails", []) == []
    assert set(observer.data["resources"]) == {HUB}
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 1


def test_real_hub_delete_poll_success_still_requires_exact_root_absence(transport, monkeypatch):
    from azext_iot.sdk.iothub.mgmt import IotHubClient

    observer, arm, wire = transport
    create_hub(wire)
    original = wire.handle
    operation, result = OPERATION, HUB + "/operationresults/offline"

    def handle(request):
        target = urlsplit(request.url).path.casefold()
        if request.method == "DELETE":
            original(request)
            return 202, None, {
                "Azure-AsyncOperation": ownership.ARM + operation,
                "Location": ownership.ARM + result, "Retry-After": "0",
            }
        if target == operation:
            return 200, {"status": "Succeeded"}, {}
        if target == result:
            return 204, None, {}
        return original(request)

    monkeypatch.setattr(wire, "handle", handle)
    client = IotHubClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM, polling_interval=0)
    client.iot_hub_resource.begin_delete(ownership.GROUP, HUB.rsplit("/", 1)[1]).result(timeout=3)
    mutation = observer.data["resources"][HUB]["mutations"][-1]
    assert mutation["status"] == 202 and mutation["pollingSucceeded"]
    assert ownership.pending_mutation(mutation) and "absenceConfirmed" not in mutation
    assert not observer.data["violations"]
    before = len(wire.calls)
    cleanup = runner.cleanup_regular(arm, observer.data, "uid", "entra", time.monotonic() + 2, observer.path)
    assert cleanup["complete"] and cleanup["absentIds"] == [HUB]
    assert mutation["reconciled"] and mutation["absenceConfirmed"]
    assert len(wire.calls) == before
    assert all(call.args[0] == "GET" for call in arm.request.call_args_list)
    assert len([call for call in wire.calls if call[0] == "DELETE"]) == 1
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_poll_observation_needs_no_native_process_or_signal_apis(transport, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    observer, _, wire = transport
    assert wire.submit("GET", NEGATIVE).status_code == 404
    assert not observer.data["violations"]
