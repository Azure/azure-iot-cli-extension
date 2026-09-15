# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Real SDK, requests and LRO threads over an in-memory HTTP adapter; no live collection."""

from copy import deepcopy
import json
import signal
import sys
import threading
import time
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests
from azure.core.credentials import AccessToken
from azure.cli.core._profile import Profile
from azure.cli.core.aaz._poller import AAZLROPoller
from urllib3.response import HTTPResponse

from azext_iot.tests import _dps_phase_runner as bounds
from azext_iot.tests import _hub_ownership as ownership
from azext_iot.tests import _hub_phase_runner as runner

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Ownership runtime requires Linux.")
PREFIX = f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups/{ownership.GROUP}/providers/".casefold()
HUB = PREFIX + "microsoft.devices/iothubs/aziotclitest-hub-" + "a" * 18
COSMOS = PREFIX + "microsoft.documentdb/databaseaccounts/aziotclitest" + "b" * 12
DATABASE = COSMOS + "/sqldatabases/routedb"
CONTAINER = DATABASE + "/containers/routecontainer"
NAMESPACE = PREFIX + "microsoft.eventhub/namespaces/aziotclitest" + "c" * 12


class Credential:
    def get_token(self, *_scopes, **_kwargs):
        return AccessToken("offline-only", int(time.time()) + 3600)


class Wire:
    def __init__(self):
        self.resources = {}
        self.calls = []
        self.accepted = {}
        self.operations = {}

    def send(self, request, **kwargs):
        assert urlsplit(request.url).hostname == urlsplit(ownership.ARM).hostname
        self.calls.append((request.method, request.url, kwargs, threading.current_thread(), request.body))
        status, body, headers = self.handle(request)
        response = requests.Response()
        response.status_code = status
        response.headers.update({"content-type": "application/json", **headers})
        response._content = json.dumps(body).encode() if body is not None else b""
        response._content_consumed = True
        response.raw = HTTPResponse(body=response._content, status=status, headers=response.headers)
        response.request = request
        response.url = request.url
        return response

    def handle(self, request):
        target = urlsplit(request.url).path.casefold()
        if request.method == "GET":
            if target in self.operations:
                resource_id, header = self.operations[target]
                body = {"status": "Succeeded"} if header == "azure-asyncoperation" else self.resources[resource_id]
                return 200, body, {}
            if target.endswith("/providers/microsoft.devices/iothubs"):
                return 200, {"value": [r for key, r in self.resources.items() if "/iothubs/" in key]}, {}
            return (200, self.resources[target], {}) if target in self.resources else (404, None, {})
        if request.method == "PUT":
            body = ownership.request_body(request.body)
            resource = dict(deepcopy(body), id=target, name=target.rsplit("/", 1)[1])
            if "/sqldatabases/" not in target:
                resource.setdefault("properties", {})["provisioningState"] = "Succeeded"
            self.resources[target] = resource
            if target in self.accepted:
                header, status = self.accepted[target]
                operation = (
                    f"/subscriptions/{ownership.SUBSCRIPTION}/providers/microsoft.documentdb/locations/"
                    + ownership.REGION + "/operations/" + str(len(self.operations))
                )
                self.operations[operation] = target, header
                return status, None, {header: ownership.ARM + operation, "retry-after": "0"}
            return 200, resource, {}
        if request.method == "DELETE":
            for key in list(self.resources):
                if key == target or key.startswith(target + "/"):
                    del self.resources[key]
            return 204, None, {}
        assert request.method == "POST"
        if target.endswith("/exporttemplate"):
            return 200, {"template": {"resources": [self.resources[HUB]]}}, {}
        assert target in (HUB + "/routing/routes/$testall", HUB + "/routing/routes/$testnew")
        return 200, {"routes": []}, {}

    @staticmethod
    def submit(method, target, body=None):
        return requests.Session().request(method, ownership.ARM + target, params={"api-version": "test"}, json=body)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    wire = Wire()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send",
                        lambda _adapter, request, **kwargs: wire.send(request, **kwargs))
    monkeypatch.setattr(Profile, "get_raw_token", lambda *_args, **_kwargs: (("Bearer", "offline-only", {}), None, None))
    arm = ownership.Arm()
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "regular", arm)
    observer.install()
    try:
        yield observer, arm, wire
    finally:
        observer.restore()


def create_hub(wire):
    wire.submit("PUT", HUB, {"location": ownership.REGION, "properties": {"disableLocalAuth": True}})


def namespace_poller():
    from azure.mgmt.eventhub import EventHubManagementClient
    client = EventHubManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)

    def operations():
        # AAZ submits even the initial PUT inside its poller thread.
        poller = client.namespaces.begin_create_or_update(
            ownership.GROUP, NAMESPACE.rsplit("/", 1)[1], {"location": ownership.REGION}, polling=False,
        )
        yield poller.polling_method()

    return AAZLROPoller(operations(), None)


def test_aaz_initial_put_uses_bounded_worker_preflight_without_reentering_observer(transport):
    observer, arm, wire = transport
    poller = namespace_poller()
    result = poller.result(timeout=3)
    assert poller.done() and result.id.casefold() == NAMESPACE
    assert not arm.read_failed
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    assert [call[0] for call in wire.calls] == ["GET", "PUT"]
    assert wire.calls[0][3].name == "hub-ownership-read"
    assert wire.calls[1][3].name.startswith("AAZLROPoller")
    assert len(observer.data["resources"][NAMESPACE]["mutations"]) == 1


@pytest.mark.parametrize("stage", ["authentication", "request", "decoding", "pagination"])
def test_worker_deadline_bounds_entire_read_and_discards_late_results(transport, monkeypatch, stage):
    observer, arm, wire = transport
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    monkeypatch.setattr(bounds, "READ_SECONDS", .08)

    def stall():
        entered.set()
        assert release.wait(3)

    if stage == "authentication":
        original = arm.profile.get_raw_token

        def token(**kwargs):
            stall()
            return original(**kwargs)
        monkeypatch.setattr(arm.profile, "get_raw_token", token)
    elif stage == "decoding":
        original = requests.Response.json

        def decode(response, **kwargs):
            stall()
            return original(response, **kwargs)
        monkeypatch.setattr(requests.Response, "json", decode)
    else:
        original = wire.handle

        def handle(request):
            stall()
            if stage == "pagination":
                return 200, {"value": [], "nextLink": ownership.ARM + "/subscriptions/" + ownership.SUBSCRIPTION
                             + "/providers/Microsoft.Devices/IotHubs?next=2"}, {}
            return original(request)
        monkeypatch.setattr(wire, "handle", handle)

    def call():
        try:
            if stage == "pagination":
                observer._verify(arm.inventory)
            elif stage == "decoding":
                observer._read(HUB, "test")
            else:
                wire.submit("PUT", NAMESPACE, {"location": ownership.REGION})
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    if stage == "decoding":
        wire.resources[HUB] = {"id": HUB}
    thread = threading.Thread(target=call)
    started = time.monotonic()
    try:
        thread.start()
        assert entered.wait(1) and finished.wait(1)
        assert time.monotonic() - started < .8
        assert len(errors) == 1 and isinstance(errors[0], bounds.PhaseError)
        assert arm.read_failed and not observer.data["resources"]
        assert observer.data["violations"] == ["Ownership verification deadline exhausted"]
        receipt = observer.path.read_bytes()
        calls = len(wire.calls)
        with pytest.raises(ownership.OwnershipError, match="previous ownership read"):
            wire.submit("PUT", NAMESPACE, {"location": ownership.REGION})
        release.set()
        for reader in threading.enumerate():
            if reader.name == "hub-ownership-read":
                reader.join(1)
                assert not reader.is_alive()
        assert len(wire.calls) == calls
        assert observer.path.read_bytes() == receipt
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()


def test_worker_read_preserves_real_main_thread_interval_timer(transport, monkeypatch):
    _, arm, _ = transport
    release = threading.Event()
    monkeypatch.setattr(bounds, "READ_SECONDS", .08)
    monkeypatch.setattr(arm.profile, "get_raw_token", lambda **_kwargs: release.wait(3))
    alarm, timer = getattr(signal, "SIGALRM"), getattr(signal, "ITIMER_REAL")
    set_timer, get_timer = getattr(signal, "setitimer"), getattr(signal, "getitimer")
    previous = signal.getsignal(alarm)
    remaining, interval = get_timer(timer)
    started, fired = time.monotonic(), []
    try:
        signal.signal(alarm, lambda *_args: fired.append(time.monotonic()))
        set_timer(timer, .02, .02)
        poller = namespace_poller()
        with pytest.raises(bounds.PhaseError, match="bound"):
            poller.result(timeout=1)
        assert poller.done() and len(fired) >= 2
        assert get_timer(timer)[1] == .02
    finally:
        release.set()
        set_timer(timer, 0)
        signal.signal(alarm, previous)
        if remaining:
            set_timer(timer, max(.000001, remaining - (time.monotonic() - started)), interval)
        for reader in threading.enumerate():
            if reader.name == "hub-ownership-read":
                reader.join(1)


@pytest.mark.parametrize("operation", ["test_all_routes", "test_route"])
def test_real_route_sdk_path_requires_current_exact_owned_hub(transport, operation):
    from azext_iot.sdk.iothub.mgmt import IotHubClient
    observer, _, wire = transport
    create_hub(wire)
    client = IotHubClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)
    test_route = getattr(client.iot_hub_resource, operation)
    assert test_route(HUB.rsplit("/", 1)[1], ownership.GROUP, input={"message": {"body": "{}"}}) == {"routes": []}
    assert len(observer.data["resources"][HUB]["mutations"]) == 1
    wire.resources[HUB]["tags"][ownership.OWNER_TAG] = "foreign"
    with pytest.raises(ownership.OwnershipError, match="ownership tag"):
        test_route(HUB.rsplit("/", 1)[1], ownership.GROUP, input={})
    assert len([call for call in wire.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("suffix", ["/$testall", "/routing/$testall", "/routing/routes/$delete", "/testAllRoutes"])
def test_route_action_allowlist_does_not_authorize_arbitrary_resource_actions(transport, suffix):
    _, _, wire = transport
    create_hub(wire)
    with pytest.raises(ownership.OwnershipError):
        wire.submit("POST", HUB + suffix, {})
    assert not any(call[0] == "POST" for call in wire.calls)


def test_real_cli_export_serialization_keeps_exact_resource_subset(transport, monkeypatch):
    from azure.cli.command_modules.resource import custom
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.resource.resources.v2024_11_01.models import ExportTemplateRequest
    observer, _, wire = transport
    create_hub(wire)
    client = ResourceManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)
    monkeypatch.setattr(custom, "_resource_client_factory", lambda _ctx: client)
    cmd = Mock()
    cmd.get_models.return_value = ExportTemplateRequest
    cmd.supported_api_version.return_value = True
    result = custom.export_group_as_template(cmd, ownership.GROUP, resource_ids=[HUB], skip_all_params=True)
    assert result["resources"][0]["id"] == HUB
    assert len(observer.data["resources"][HUB]["mutations"]) == 1
    posts = [call for call in wire.calls if call[0] == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0][4]) == {
        "resources": [HUB], "options": "SkipAllParameterization", "outputFormat": "Json",
    }


@pytest.mark.parametrize("damage", [
    "wildcard", "foreign", "descendant", "duplicate", "format", "option", "tag", "uncertain",
])
def test_export_remains_fail_closed(transport, damage):
    observer, _, wire = transport
    create_hub(wire)
    body = {"resources": [HUB], "options": "SkipAllParameterization", "outputFormat": "Json"}
    if damage == "wildcard":
        body["resources"] = ["*"]
    elif damage == "foreign":
        body["resources"].append(HUB.replace("cli-int-test-rg", "foreign-group"))
    elif damage == "descendant":
        body["resources"] = [HUB + "/certificates/not-owned"]
    elif damage == "duplicate":
        body["resources"] *= 2
    elif damage == "format":
        body["outputFormat"] = "Bicep"
    elif damage == "option":
        body["options"] = "IncludeComments"
    elif damage == "tag":
        wire.resources[HUB]["tags"][ownership.OWNER_TAG] = "foreign"
    else:
        observer.data["resources"][HUB]["uncertain"] = True
    with pytest.raises(ownership.OwnershipError):
        wire.submit("POST", HUB.split("/providers/")[0] + "/exportTemplate", body)
    assert not any(call[0] == "POST" for call in wire.calls)


@pytest.mark.parametrize("header", ["azure-asyncoperation", "location"])
@pytest.mark.parametrize("initial_status", [200, 202])
def test_real_cosmos_lro_without_provisioning_state_then_container_and_cleanup(transport, header, initial_status):
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
    observer, arm, wire = transport
    wire.submit("PUT", COSMOS, {"location": ownership.REGION})
    wire.accepted[DATABASE] = header, initial_status
    wire.accepted[CONTAINER] = header, initial_status
    client = CosmosDBManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM, polling_interval=0)
    database = client.sql_resources.begin_create_update_sql_database(
        ownership.GROUP, COSMOS.rsplit("/", 1)[1], "routedb",
        {"location": ownership.REGION, "properties": {"resource": {"id": "routedb"}, "options": {}}},
    ).result(timeout=3)
    assert database.id.casefold() == DATABASE
    assert "provisioningState" not in wire.resources[DATABASE]["properties"]
    container = client.sql_resources.begin_create_update_sql_container(
        ownership.GROUP, COSMOS.rsplit("/", 1)[1], "routedb", "routecontainer",
        {"location": ownership.REGION, "properties": {
            "resource": {"id": "routecontainer", "partitionKey": {"paths": ["/deviceid"], "kind": "Hash"}}, "options": {},
        }},
    ).result(timeout=3)
    assert container.id.casefold() == CONTAINER
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    mutations = observer.data["resources"][COSMOS]["mutations"]
    assert len(mutations) == 3
    assert all(m["reconciled"] and m["pollingSucceeded"] for m in mutations[1:])
    assert [urlsplit(call[1]).path.casefold() for call in wire.calls if call[0] == "PUT"] == [COSMOS, DATABASE, CONTAINER]
    result = runner.cleanup_regular(arm, observer.data, "uid", "regular", time.monotonic() + 2, observer.path)
    assert result["complete"] and result["absentDescendantIds"] == [DATABASE, CONTAINER]
    assert not wire.resources


@pytest.mark.parametrize("damage", ["uncorrelated", "nonterminal", "failed", "wrong-id", "transport", "foreign-root"])
def test_polling_never_resolves_unknown_or_unrelated_mutations(transport, damage):
    observer, arm, wire = transport
    wire.submit("PUT", COSMOS, {"location": ownership.REGION})
    wire.accepted[DATABASE] = "azure-asyncoperation", 202
    response = wire.submit("PUT", DATABASE, {"properties": {"resource": {"id": "routedb"}}})
    operation_url = response.headers["azure-asyncoperation"]
    mutation = observer.data["resources"][COSMOS]["mutations"][-1]
    if damage == "uncorrelated":
        operation_url += "/another"
    elif damage == "transport":
        mutation["status"] = None
    elif damage == "foreign-root":
        wire.resources[COSMOS]["tags"][ownership.OWNER_TAG] = "foreign"
    state = {"nonterminal": "Running", "failed": "Failed"}.get(damage, "Succeeded")
    ownership.observe_poll(observer.data, operation_url, 200, {"status": state})
    resource = deepcopy(wire.resources[DATABASE])
    if damage == "wrong-id":
        resource["id"] = CONTAINER
    ownership.observe_get(observer.data, DATABASE, 200, resource)
    if damage == "foreign-root":
        with pytest.raises(ownership.OwnershipError, match="ownership tag"):
            wire.submit("PUT", CONTAINER, {"properties": {"resource": {"id": "routecontainer"}}})
    else:
        assert observer.data["resources"][COSMOS]["uncertain"]
        # No mutation replay, even after a successful-looking resource GET.
        arm.deadline = time.monotonic()
        with pytest.raises((ownership.OwnershipError, bounds.PhaseError)):
            wire.submit("PUT", DATABASE, {"properties": {"resource": {"id": "routedb"}}})
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 2


def test_real_location_poller_tracks_only_correlated_continuations(transport, monkeypatch):
    from azure.mgmt.cosmosdb import CosmosDBManagementClient
    observer, _, wire = transport
    wire.submit("PUT", COSMOS, {"location": ownership.REGION})
    wire.accepted[DATABASE] = "location", 202
    original = wire.handle
    continued = []

    def handle(request):
        target = urlsplit(request.url).path.casefold()
        if request.method == "GET" and target in wire.operations and not continued:
            continuation = target + "/result"
            continued.append(continuation)
            wire.operations[continuation] = wire.operations[target]
            return 202, None, {"location": ownership.ARM + continuation, "retry-after": "0"}
        return original(request)

    monkeypatch.setattr(wire, "handle", handle)
    client = CosmosDBManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM, polling_interval=0)
    result = client.sql_resources.begin_create_update_sql_database(
        ownership.GROUP, COSMOS.rsplit("/", 1)[1], "routedb",
        {"properties": {"resource": {"id": "routedb"}, "options": {}}},
    ).result(timeout=3)
    assert result.id.casefold() == DATABASE and len(continued) == 1
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 2


@pytest.mark.parametrize("header", ["azure-asyncoperation", "location"])
def test_polling_urls_are_scoped_and_receipts_store_only_digests(transport, header):
    observer, _, wire = transport
    wire.submit("PUT", COSMOS, {"location": ownership.REGION})
    wire.accepted[DATABASE] = header, 202
    response = wire.submit("PUT", DATABASE, {"properties": {"resource": {"id": "routedb"}}})
    url = response.headers[header]
    key = ownership.polling_key(url + "?api-version=one&sig=private-poll-query")
    assert key == ownership.polling_key(url.replace(ownership.ARM, "https://management.azure.com")
                                        + "?sig=private-poll-query&api-version=two")
    assert "private-poll-query" not in key
    receipt = observer.path.read_text(encoding="utf-8")
    assert url not in receipt and ownership.polling_key(url) in receipt
    with pytest.raises(ownership.OwnershipError, match="polling URL"):
        ownership.polling_key(url.replace(ownership.SUBSCRIPTION, "foreign-subscription"))
