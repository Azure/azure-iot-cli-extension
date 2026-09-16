# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Real SDK, requests and LRO threads over an in-memory HTTP adapter; no live collection."""

from copy import deepcopy
import json
from pathlib import Path
import shlex
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
IDENTITY = PREFIX + "microsoft.managedidentity/userassignedidentities/aziotclitest" + "d" * 12
CERTIFICATE = HUB + "/certificates/cert1"


class Credential:
    def get_token(self, *_scopes, **_kwargs):
        return AccessToken("offline-only", int(time.time()) + 3600)


class Wire:
    def __init__(self):
        self.resources = {}
        self.calls = []
        self.accepted = {}
        self.operations = {}
        self.identity_headers = {}
        self.receipt = None

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
            if "/microsoft.resources/deployments/" in target:
                receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
                record = receipt["resources"][target]
                assert record["before"] == 404 and record["mutations"][-1]["status"] is None
                for item in body["properties"]["template"]["resources"]:
                    names = item["name"].split("/")
                    resource_id = PREFIX + "microsoft.devices/iothubs/" + names[0].casefold()
                    if len(names) == 2:
                        resource_id += "/certificates/" + names[1].casefold()
                    assert resource_id in record["deploymentTargets"]
                    mutations = [mutation for root in receipt["resources"].values() for mutation in root["mutations"]
                                 if mutation.get("deployment") == target and mutation["id"] == resource_id]
                    assert len(mutations) == 1 and mutations[0]["status"] is None
                    assert mutations[0]["before"] == (200 if resource_id in self.resources else 404)
                    resource = dict(deepcopy(item), id=resource_id)
                    if len(names) == 1:
                        resource["properties"]["provisioningState"] = "Succeeded"
                    self.resources[resource_id] = resource
                # RG deployment history is not a regional resource and does not
                # echo the submitted template or a top-level location.
                resource = {
                    "id": target, "name": target.rsplit("/", 1)[1], "type": "Microsoft.Resources/deployments",
                    "tags": body["tags"], "properties": {
                        "provisioningState": "Succeeded", "mode": "Incremental",
                        "timestamp": "2026-09-16T00:00:00Z", "duration": "PT1M",
                        "correlationId": "00000000-0000-0000-0000-000000000001",
                        "outputResources": [{"id": value} for value in record["deploymentTargets"]],
                    },
                }
                self.resources[target] = resource
                operation = target + "/operationStatuses/offline"
                self.operations[operation.casefold()] = target, "azure-asyncoperation"
                return 201, dict(resource, properties={"provisioningState": "Accepted"}), {
                    "azure-asyncoperation": ownership.ARM + operation, "retry-after": "0",
                }
            resource = dict(deepcopy(body), id=target, name=target.rsplit("/", 1)[1])
            if "/sqldatabases/" not in target:
                resource.setdefault("properties", {})["provisioningState"] = "Succeeded"
            self.resources[target] = resource
            if target == IDENTITY:
                resource["properties"] = {"principalId": "offline-principal", "clientId": "offline-client"}
                return 201, resource, self.identity_headers
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
            selected = ownership.request_body(request.body)["resources"]
            resources = [
                {k: deepcopy(v) for k, v in resource.items() if k not in ("id", "etag")}
                for key, resource in self.resources.items()
                if any(key == value.casefold() or key.startswith(value.casefold() + "/certificates/") for value in selected)
            ]
            for resource in resources:
                resource.get("properties", {}).pop("provisioningState", None)
                if resource.get("type", "").casefold() == "microsoft.devices/iothubs/certificates":
                    parent = resource["dependsOn"][0].split("'")[3]
                    resource["name"] = parent + "/" + resource["name"].rsplit("/", 1)[-1]
            return 200, {"template": {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                "contentVersion": "1.0.0.0", "parameters": {}, "variables": {}, "resources": resources,
            }}, {}
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
    wire.receipt = observer.path
    observer.install()
    try:
        yield observer, arm, wire
    finally:
        observer.restore()


def create_hub(wire):
    wire.submit("PUT", HUB, {"location": ownership.REGION, "properties": {"disableLocalAuth": True}})


def create_identity(monkeypatch):
    from azure.cli.core import get_default_cli
    from azure.cli.core.aaz._command_ctx import AAZCommandCtx
    from azure.cli.command_modules.identity.aaz.latest.identity._create import Create
    monkeypatch.setattr(AAZCommandCtx, "get_login_credential", lambda _ctx: Credential())
    return Create(cli_ctx=get_default_cli())({
        "subscription": ownership.SUBSCRIPTION, "resource_group": ownership.GROUP,
        "resource_name": IDENTITY.rsplit("/", 1)[1], "location": ownership.REGION,
    })


@pytest.mark.parametrize("location", [
    None, ownership.REGION, ownership.REGION.upper(), IDENTITY, IDENTITY.lstrip("/"),
    ownership.ARM + IDENTITY, "https://management.azure.com" + IDENTITY + "?api-version=test&sig=private-response-query",
])
def test_real_synchronous_aaz_identity_location_then_reference_role_and_cleanup(transport, monkeypatch, location):
    observer, arm, wire = transport
    wire.identity_headers = {} if location is None else {"Location": location}
    identity = create_identity(monkeypatch)
    assert identity["id"].casefold() == IDENTITY
    assert identity["principalId"] == "offline-principal"
    assert [call[0] for call in wire.calls] == ["GET", "PUT"]
    assert all(call[3] is threading.main_thread() for call in wire.calls)
    record = observer.data["resources"][IDENTITY]
    assert record["resolved"] and not record["uncertain"]
    assert record["mutations"][0]["status"] == 201 and "polling" not in record["mutations"][0]
    assert "provisioningState" not in wire.resources[IDENTITY]["properties"]
    assert "private-response-query" not in observer.path.read_text(encoding="utf-8")
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data
    observer.require_owned_reference(IDENTITY, "microsoft.managedidentity/userassignedidentities")
    role = IDENTITY + "/providers/microsoft.authorization/roleassignments/offline-role"
    wire.submit("PUT", role, {"properties": {"principalId": identity["principalId"]}})
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    result = runner.cleanup_regular(arm, observer.data, "uid", "regular", time.monotonic() + 2, observer.path)
    assert result["complete"] and result["absentDescendantIds"] == [role] and not wire.resources
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data


@pytest.mark.parametrize("location", [
    "", "other-region", "//management.azure.com" + IDENTITY,
    "http://management.azure.com" + IDENTITY, "https://unapproved.example" + IDENTITY + "?sig=private-response-query",
    "https://management.azure.com:443" + IDENTITY, "https://user@management.azure.com" + IDENTITY,
    "https://[malformed", IDENTITY + "#fragment", IDENTITY + "/../other",
    IDENTITY.replace(ownership.SUBSCRIPTION, "foreign-subscription"),
    IDENTITY.replace(ownership.GROUP, "foreign-group"), IDENTITY + "%2fother", IDENTITY + "/other",
    IDENTITY.replace("d" * 12, "e" * 12),
])
def test_real_aaz_identity_bad_location_is_durable_and_never_replayed(transport, monkeypatch, location):
    observer, arm, wire = transport
    wire.identity_headers = {"Location": location}
    with pytest.raises(ownership.OwnershipError, match="response Location"):
        create_identity(monkeypatch)
    record = observer.data["resources"][IDENTITY]
    assert record["uncertain"] and not record["resolved"]
    assert record["mutations"][0]["status"] == 201 and record["mutations"][0]["responseError"]
    wire.submit("GET", IDENTITY)
    assert record["uncertain"] and not record["resolved"]
    with pytest.raises(ownership.OwnershipError, match="Reference requires"):
        observer.require_owned_reference(IDENTITY, "microsoft.managedidentity/userassignedidentities")
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        create_identity(monkeypatch)
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 1
    result = runner.cleanup_regular(arm, observer.data, "uid", "regular", time.monotonic() + 2, observer.path)
    assert not result["complete"] and not any(call[0] == "DELETE" for call in wire.calls)
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data
    assert "private-response-query" not in observer.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("header", ["Azure-AsyncOperation", "Location"])
@pytest.mark.parametrize("status", [200, 201, 202])
def test_relative_arm_operation_headers_remain_lros(transport, header, status):
    observer, _, wire = transport
    create_hub(wire)
    operation = f"/subscriptions/{ownership.SUBSCRIPTION}/providers/Microsoft.Devices/operations/offline"
    observer.prepare("PUT", HUB, "test", {})
    observer.complete(HUB, status, {header: operation.lstrip("/")}, wire.resources[HUB])
    record = observer.data["resources"][HUB]
    assert record["uncertain"] and ownership.pending_mutation(record["mutations"][-1])
    ownership.observe_poll(observer.data, ownership.ARM + operation, 200, {"status": "Succeeded"})
    ownership.observe_get(observer.data, HUB, 200, wire.resources[HUB])
    assert not record["uncertain"]
    assert ownership.polling_key(operation) == ownership.polling_key(ownership.ARM + operation)


@pytest.mark.parametrize("header", ["Azure-AsyncOperation", "Location"])
def test_real_aaz_identity_actual_operation_header_is_not_synchronous_metadata(transport, monkeypatch, header):
    observer, arm, wire = transport
    operation = (
        f"/subscriptions/{ownership.SUBSCRIPTION}/providers/Microsoft.ManagedIdentity/"
        f"locations/{ownership.REGION}/operations/offline"
    )
    wire.identity_headers = {header: operation}
    if header == "Azure-AsyncOperation":
        wire.identity_headers["Location"] = IDENTITY
    create_identity(monkeypatch)
    record = observer.data["resources"][IDENTITY]
    mutation = record["mutations"][0]
    assert record["uncertain"] and mutation["awaitingProvisioning"]
    assert mutation["polling"][header.casefold()] == ownership.polling_key(operation)
    arm.deadline = time.monotonic()
    with pytest.raises(ownership.OwnershipError, match="Reference requires"):
        observer.require_owned_reference(IDENTITY, "microsoft.managedidentity/userassignedidentities")


@pytest.mark.parametrize("damage", ["foreign-id", "foreign-tag", "foreign-region", "provisioning", "async-header"])
def test_identity_regional_location_exception_requires_exact_synchronous_owned_response(transport, monkeypatch, damage):
    observer, _, wire = transport
    wire.identity_headers = {"Location": ownership.REGION}
    original = wire.handle

    def handle(request):
        status, body, headers = original(request)
        if request.method == "PUT":
            if damage == "foreign-id":
                body["id"] = IDENTITY.replace(ownership.GROUP, "foreign-group")
            elif damage == "foreign-tag":
                body["tags"][ownership.OWNER_TAG] = "foreign"
            elif damage == "foreign-region":
                body["location"] = "other-region"
            elif damage == "provisioning":
                body["properties"]["provisioningState"] = "Creating"
            else:
                headers["Azure-AsyncOperation"] = ownership.ARM + IDENTITY + "/operations/offline"
        return status, body, headers

    monkeypatch.setattr(wire, "handle", handle)
    with pytest.raises(ownership.OwnershipError, match="response Location"):
        create_identity(monkeypatch)
    assert observer.data["resources"][IDENTITY]["uncertain"]
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data


@pytest.mark.parametrize("by_id", [False, True])
def test_real_generic_resource_update_path(transport, monkeypatch, by_id):
    from azure.cli.command_modules.resource import custom
    from azure.mgmt.resource.resources import ResourceManagementClient
    observer, _, wire = transport
    create_hub(wire)
    client = ResourceManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)
    monkeypatch.setattr(custom, "_resource_client_factory", lambda _ctx: client)
    monkeypatch.setattr(custom, "get_subscription_id", lambda _ctx: ownership.SUBSCRIPTION)
    args = {"resource_ids": [HUB]} if by_id else {
        "resource_group_name": ownership.GROUP, "resource_type": "Microsoft.Devices/IotHubs",
        "resource_name": HUB.rsplit("/", 1)[1],
    }
    if not by_id:
        with pytest.raises(ownership.OwnershipError, match="Mutation outside explicit resource scope"):
            custom.update_resource(Mock(), deepcopy(wire.resources[HUB]), api_version="test", **args)
        details = observer.data["violationDetails"][0]
        assert details["resourcePath"] == HUB.replace("/microsoft.devices/", "/microsoft.devices//")
        assert details["apiVersionPresent"] and details["method"] == "PUT"
        assert len([call for call in wire.calls if call[0] == "PUT"]) == 1
        return
    result = custom.update_resource(Mock(), deepcopy(wire.resources[HUB]), api_version="test", **args).result(timeout=3)
    assert result.id.casefold() == HUB
    assert len(observer.data["resources"][HUB]["mutations"]) == 2
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    wire.resources[HUB]["tags"][ownership.OWNER_TAG] = "foreign"
    with pytest.raises(ownership.OwnershipError, match="ownership tag"):
        custom.update_resource(Mock(), deepcopy(wire.resources[HUB]), api_version="test", **args)
    assert len([call for call in wire.calls if call[0] == "PUT"]) == 2


@pytest.mark.parametrize("target,api", [
    (HUB.replace(ownership.GROUP, "foreign-group"), "test"),
    (HUB.replace(ownership.SUBSCRIPTION, "foreign-subscription"), "test"),
    (HUB, None), (HUB + "/%2fescape", "test"),
])
def test_scope_gate_persists_safe_context_before_blocking_transport(transport, target, api):
    observer, _, wire = transport
    observer.current_node = "offline-node"
    params = {"sig": "private-query"}
    if api:
        params["api-version"] = api
    with pytest.raises(ownership.OwnershipError, match="Mutation outside explicit resource scope"):
        requests.put(ownership.ARM + target, params=params, json={"secret": "private-body"},
                     headers={"Authorization": "Bearer private-token"})
    assert not wire.calls
    receipt = observer.path.read_text(encoding="utf-8")
    assert not any(value in receipt for value in ("private-query", "private-body", "private-token"))
    details = json.loads(receipt)["violationDetails"][0]
    assert details["method"] == "PUT" and details["apiVersionPresent"] == bool(api)
    assert details["node"] == "offline-node"
    assert details["resourcePath"] == (target if "%" not in target else "<invalid resource path>")


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
    assert result["resources"][0]["name"] == HUB.rsplit("/", 1)[1]
    assert len(observer.data["resources"][HUB]["mutations"]) == 1
    posts = [call for call in wire.calls if call[0] == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0][4]) == {
        "resources": [HUB], "options": "SkipAllParameterization", "outputFormat": "Json",
    }


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("explicit_children", [False, True])
def test_real_state_export_deployment_comparison_and_cleanup(transport, monkeypatch, tmp_path, create, explicit_children):
    from azure.cli.command_modules.resource import custom
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.resource.resources.v2024_11_01.models import ExportTemplateRequest
    from azure.mgmt.resource.deployments import DeploymentsMgmtClient
    from azure.mgmt.resource.deployments.models import Deployment, DeploymentProperties
    from azext_iot.iothub.providers import state
    from azext_iot.sdk.iothub.mgmt import IotHubClient
    from azext_iot.tests.iothub.state import _state_helpers
    from azext_iot.tests.test_hub_phase_runner_unit import fixture_template

    observer, arm, wire = transport
    monkeypatch.chdir(tmp_path)
    template = fixture_template()
    hub = template["resources"][0]
    cert = {
        "type": "Microsoft.Devices/IotHubs/certificates", "apiVersion": hub["apiVersion"],
        "name": hub["name"] + "/cert1", "properties": {"certificate": "offline-public-certificate", "isVerified": True},
        "dependsOn": [f"[resourceId('Microsoft.Devices/IotHubs', '{hub['name']}')]"],
    }
    wire.submit("PUT", HUB, hub)
    wire.submit("PUT", CERTIFICATE, cert)
    destination = HUB.replace("a" * 18, "e" * 18)
    if not create:
        wire.submit("PUT", destination, dict(hub, name=destination.rsplit("/", 1)[1]))
    client = ResourceManagementClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)
    deployments = DeploymentsMgmtClient(
        Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM,
        per_call_policies=[custom.JsonCTemplatePolicy()], polling_interval=0,
    )
    hubs = IotHubClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM)
    monkeypatch.setattr(custom, "_resource_client_factory", lambda _ctx: client)
    cmd = Mock()
    cmd.get_models.return_value = ExportTemplateRequest
    cmd.supported_api_version.return_value = True
    exported_ids = []

    def invoke(command, **_kwargs):
        args = shlex.split(command)
        if args[:2] == ["group", "export"]:
            selected = args[args.index("--resource-ids") + 1:args.index("--skip-all-params")]
            exported_ids.append(selected)
            result = custom.export_group_as_template(cmd, ownership.GROUP, resource_ids=selected, skip_all_params=True)
        elif args[:3] == ["deployment", "group", "create"]:
            path = Path(args[args.index("--template-file") + 1])
            model = Deployment(properties=DeploymentProperties(mode="Incremental", template=path.read_text(encoding="utf-8")))
            result = deployments.deployments.begin_create_or_update(
                ownership.GROUP, path.stem, model,
            ).result(timeout=3).as_dict()
            result["resourceGroup"] = ownership.GROUP
        else:
            assert args[:3] == ["iot", "hub", "show"]
            name = args[args.index("-n") + 1]
            result = hubs.iot_hub_resource.get(ownership.GROUP, name)
        return Mock(as_json=lambda: result, success=lambda: True, output=json.dumps(result), get_error=lambda: None)

    bridge = Mock(invoke=invoke)
    monkeypatch.setattr(state, "cli", bridge)
    monkeypatch.setattr(_state_helpers, "cli", bridge)
    discovery = Mock()
    discovery.find_resource.side_effect = lambda name, group: dict(
        hubs.iot_hub_resource.get(group, name), resourcegroup=group,
    )
    discovery.get_target.side_effect = lambda name, **_kwargs: {
        "entity": name + ".azure-devices.net", "resourcegroup": ownership.GROUP, "name": name,
    }
    provider = state.StateProvider.__new__(state.StateProvider)
    provider.discovery, provider.rg, provider.login, provider.auth_type = discovery, ownership.GROUP, None, "login"
    provider.hub_name = hub["name"]
    provider.target = discovery.get_target(provider.hub_name)
    path = str(tmp_path / "state.json")
    provider.save_state(path, hub_aspects=["arm"])
    provider.hub_name = destination.rsplit("/", 1)[1]
    provider.target = None if create else discovery.get_target(provider.hub_name)
    provider.upload_state(path, hub_aspects=["arm"])
    record = observer.data["resources"][destination]
    assert record["uncertain"]  # SDK has polled the deployment, not its certificate target.
    checkpoint = len(wire.calls)
    _state_helpers.compare_hubs_controlplane(hub["name"], provider.hub_name, ownership.GROUP)
    assert not record["uncertain"]
    assert all(call[0] in ("GET", "POST") for call in wire.calls[checkpoint:])
    selected = [destination, destination + "/certificates/cert1"] if explicit_children else [destination]
    exported = custom.export_group_as_template(cmd, ownership.GROUP, resource_ids=selected, skip_all_params=True)
    assert len(exported["resources"]) == 2
    assert exported_ids == [[HUB], [HUB], [destination]]
    deployment = PREFIX + "microsoft.resources/deployments/arm_deployment-" + provider.hub_name
    assert "location" not in wire.resources[deployment]
    assert wire.resources[deployment]["tags"][ownership.OWNER_TAG] == "uid"
    puts = [urlsplit(call[1]).path.casefold() for call in wire.calls if call[0] == "PUT"]
    assert puts.count(deployment) == 1 and puts.count(destination) == (0 if create else 1)
    assert record["mutations"][-1]["reconciled"]
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    cleanup = runner.cleanup_regular(arm, observer.data, "uid", "regular", time.monotonic() + 3, observer.path)
    assert cleanup["complete"] and set(cleanup["absentIds"]) == {HUB, destination, deployment}
    assert set(cleanup["absentDescendantIds"]) == {CERTIFICATE, destination + "/certificates/cert1"}
    assert not wire.resources
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data


@pytest.mark.parametrize("damage", ["unknown", "timeout", "throttled", "server", "failed", "cancelled", "response"])
def test_export_reconciliation_never_replays_unknown_or_terminal_failed_operations(transport, damage):
    observer, arm, wire = transport
    create_hub(wire)
    observer.prepare("PUT", HUB, "test", {"properties": {"disableLocalAuth": True}})
    status = {"unknown": None, "timeout": 408, "throttled": 429, "server": 503}.get(damage, 202)
    record = observer.data["resources"][HUB]
    mutation = record["mutations"][-1]
    mutation["status"] = status
    if damage in ("failed", "cancelled"):
        failed = deepcopy(wire.resources[HUB])
        failed["properties"]["provisioningState"] = damage
        ownership.observe_get(observer.data, HUB, 200, failed)
    elif damage == "response":
        mutation["responseError"] = True
    # A later successful-looking GET cannot reverse failed/ambiguous evidence.
    ownership.observe_get(observer.data, HUB, 200, wire.resources[HUB])
    observer.save()
    checkpoint = len(wire.calls)
    with pytest.raises(ownership.OwnershipError, match="Reference requires"):
        wire.submit("POST", HUB.split("/providers/")[0] + "/exportTemplate", {"resources": [HUB]})
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        wire.submit("PUT", HUB, {"properties": {"disableLocalAuth": True}})
    result = runner.cleanup_regular(arm, observer.data, "uid", "regular", time.monotonic() + 1, observer.path)
    assert not result["complete"] and record["uncertain"]
    assert not any(call[0] != "GET" for call in wire.calls[checkpoint:])
    assert json.loads(observer.path.read_text(encoding="utf-8")) == observer.data


@pytest.mark.parametrize("damage", ["unobserved", "deleted", "wrong-id", "foreign-root", "foreign-group", "unknown"])
def test_explicit_export_child_needs_exact_receipt_and_current_root_and_child(transport, damage):
    observer, _, wire = transport
    create_hub(wire)
    if damage != "unobserved":
        wire.submit("PUT", CERTIFICATE, {"properties": {"certificate": "public"}})
    target = CERTIFICATE
    if damage == "deleted":
        wire.submit("DELETE", CERTIFICATE)
    elif damage == "wrong-id":
        wire.resources[CERTIFICATE]["id"] = CERTIFICATE + "-other"
    elif damage == "foreign-root":
        wire.resources[HUB]["tags"][ownership.OWNER_TAG] = "foreign"
    elif damage == "foreign-group":
        target = target.replace(ownership.GROUP, "foreign-group")
    elif damage == "unknown":
        record = observer.data["resources"][HUB]
        record["mutations"][-1]["status"], record["uncertain"] = None, True
    with pytest.raises(ownership.OwnershipError):
        wire.submit("POST", HUB.split("/providers/")[0] + "/exportTemplate", {"resources": [target]})
    assert not any(call[0] == "POST" for call in wire.calls)


def test_export_reconciliation_is_bounded_to_the_requested_owned_tree(transport):
    observer, arm, wire = transport
    wire.submit("PUT", NAMESPACE, {"location": ownership.REGION})
    observer.prepare("PUT", NAMESPACE, "test", {})
    wire.resources[NAMESPACE]["tags"][ownership.OWNER_TAG] = "foreign"
    wire.accepted[HUB] = "azure-asyncoperation", 202
    create_hub(wire)
    assert observer.data["resources"][HUB]["uncertain"]
    checkpoint = len(wire.calls)
    deadline = time.monotonic() + 2
    arm.deadline = deadline
    wire.submit("POST", HUB.split("/providers/")[0] + "/exportTemplate", {"resources": [HUB]})
    assert arm.deadline == deadline and not observer.data["resources"][HUB]["uncertain"]
    assert observer.data["resources"][NAMESPACE]["uncertain"]
    assert all(NAMESPACE not in call[1] for call in wire.calls[checkpoint:])
    assert all(call[0] in ("GET", "POST") for call in wire.calls[checkpoint:])


@pytest.mark.parametrize("damage", ["owner", "group", "id"])
def test_no_location_deployment_get_still_requires_current_exact_ownership(transport, damage):
    from azext_iot.tests.test_hub_phase_runner_unit import fixture_template
    observer, _, wire = transport
    deployment = PREFIX + "microsoft.resources/deployments/arm_deployment-" + HUB.rsplit("/", 1)[1]
    wire.submit("PUT", deployment, {"properties": {"mode": "Incremental", "template": fixture_template()}})
    resource = wire.resources[deployment]
    assert "location" not in resource
    if damage == "owner":
        resource["tags"][ownership.OWNER_TAG] = "foreign"
    else:
        resource["id"] = resource["id"].replace(ownership.GROUP, "foreign-group") if damage == "group" else HUB
    checkpoint = len(wire.calls)
    with pytest.raises(ownership.OwnershipError, match="no longer belongs"):
        wire.submit("GET", deployment)
    detail = json.loads(observer.path.read_text(encoding="utf-8"))["violationDetails"][-1]
    assert detail == {
        "reason": "Observed root ownership changed", "method": "GET", "resourcePath": deployment,
        "idMatches": damage == "owner", "ownerMatches": damage != "owner",
    }
    with pytest.raises(ownership.OwnershipError):
        observer.require_owned_reference(HUB, "microsoft.devices/iothubs")
    assert all(call[0] == "GET" for call in wire.calls[checkpoint:])
    assert "foreign" not in observer.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("damage", [
    "missing-region", "foreign-region", "foreign-group", "arbitrary-deployment", "other-resource",
])
def test_no_location_history_does_not_relax_literal_deployment_target_authorization(transport, damage):
    from azext_iot.tests.test_hub_phase_runner_unit import fixture_template
    observer, _, wire = transport
    template = fixture_template()
    deployment = PREFIX + "microsoft.resources/deployments/arm_deployment-" + HUB.rsplit("/", 1)[1]
    if damage == "missing-region":
        del template["resources"][0]["location"]
    elif damage == "foreign-region":
        template["resources"][0]["location"] = "westus"
    elif damage == "foreign-group":
        deployment = deployment.replace(ownership.GROUP, "foreign-group")
    elif damage == "arbitrary-deployment":
        deployment = PREFIX + "microsoft.resources/deployments/unplanned"
    else:
        template["resources"][0]["type"] = "Microsoft.Resources/deploymentScripts"
    with pytest.raises(ownership.OwnershipError):
        wire.submit("PUT", deployment, {"properties": {"mode": "Incremental", "template": template}})
    assert not wire.calls and not observer.data["resources"]


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
