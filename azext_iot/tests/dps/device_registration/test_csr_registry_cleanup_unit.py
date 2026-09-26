# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Real generated RegistryDevice transport, pre-submit intent and exact owned deletion."""

from copy import deepcopy
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from azure.cli.core.azclierror import ForbiddenError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError

from azext_iot import _factory
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.dps import _csr_registry as registry, _csr_issuance as csr
from azext_iot.tests.dps import _phase_receipts as receipts, _phase_runtime as runtime
from azext_iot.tests.dps.device_registration import test_iot_device_registration_int as scenario

SUB = "11111111-2222-3333-4444-555555555555"
UID = "d" * 32
ARM = "https://centraluseuap.management.azure.com"


@pytest.fixture
def wire(tmp_path, monkeypatch, mocker):
    for key, value in (
        (receipts.DIRECTORY_ENV, str(tmp_path)), (receipts.RUN_UID_ENV, UID),
        (receipts.SUBSCRIPTION_ENV, SUB), (receipts.RESOURCE_GROUP_ENV, "rg"),
        ("azext_iot_dps_test_phase", "regular"),
    ):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(registry, "RESOLVE_TIMEOUT", 0)
    monkeypatch.setattr(registry, "DELETE_TIMEOUT", 0)
    mocker.patch.object(csr.fixtures, "ENTITY_RG", "rg")
    resources = {}
    for name, kind in (("ns", "csrns"), ("dps", "csrdps"), ("hub", "csrhub")):
        receipts.before_create(name, "rg", UID, kind)
        record = receipts._owned(name)
        resources[name] = {
            "id": record["id"], "name": name, "tags": record["tags"],
            "properties": {"provisioningState": "Succeeded", "idScope": "scope",
                           "hostName": "classic", "deviceHostName": "modern"},
        }
    for section, name in (("provisioning", "dps"), ("messaging", "hub")):
        resources["ns"]["properties"][section] = {"endpoints": {name: {
            "resourceId": resources[name]["id"], "linkingState": "Succeeded",
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}}
    resource = {
        "namespace": "ns", "ca": "issuingca", "policy": "leafpolicy",
        "dps": {"name": "dps", "resourceGroup": "rg", "dps": resources["dps"]},
        "hub": {"name": "hub", "rg": "rg", "hub": resources["hub"]},
    }
    for name in ("dps", "hub"):
        mocker.patch.object(csr.fixtures, f"_find_{name}_by_name", return_value=resources[name])
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 9999999999))
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    factory = mocker.spy(registry, "adr_service_factory")
    state = SimpleNamespace(
        resource=resource, resources=resources, devices={}, calls=[], factory=factory,
        directory=tmp_path, list_body=None, get_transform=None, delete_status=202, list_status=200, get_status=200,
        collection=resources["ns"]["id"] + "/registryDevices", namespace_id=resources["ns"]["id"],
        namespace_delete_status=204, namespace_get_status=200, namespace_get_transform=None, events=[],
    )

    def respond(request):
        path = urlsplit(request.url).path
        state.calls.append((request.method, path))
        assert parse_qs(urlsplit(request.url).query)["api-version"] == ["2026-11-02-preview"]
        if path == state.namespace_id:
            if request.method == "DELETE":
                if state.namespace_delete_status == 204:
                    del state.resources["ns"]
                    state.events.append("csrns")
                    return 204, {}, ""
                return state.namespace_delete_status, {}, json.dumps({"error": {"code": "NamespaceNotEmpty"}})
            if state.namespace_get_status != 200:
                return state.namespace_get_status, {}, json.dumps({"error": {"code": "AuthorizationFailed"}})
            if "ns" not in state.resources:
                return 404, {}, json.dumps({"error": {"code": "ResourceNotFound"}})
            body = state.resources["ns"]
            if state.namespace_get_transform:
                body = state.namespace_get_transform(body)
            return 200, {}, json.dumps(body)
        if request.method == "GET" and path == state.collection:
            body = state.list_body if state.list_body is not None else {"value": list(state.devices.values())}
            return state.list_status, {"Content-Type": "application/json"}, json.dumps(body)
        name = path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            if state.delete_status == 202:
                del state.devices[name]
                return 202, {"Azure-AsyncOperation": ARM + "/must-not-poll"}, ""
            return state.delete_status, {}, json.dumps({"error": {"code": "AuthorizationFailed"}})
        if name not in state.devices:
            return 404, {}, json.dumps({"error": {"code": "ResourceNotFound"}})
        if state.get_status != 200:
            return state.get_status, {}, json.dumps({"error": {"code": "AuthorizationFailed"}})
        device = deepcopy(state.devices[name])
        if state.get_transform:
            device = state.get_transform(device)
        return 200, {}, json.dumps(device)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        for method in (responses.GET, responses.DELETE):
            network.add_callback(method, re.compile(re.escape(ARM + state.collection) + r"(?:[/?].*)?$"), respond)
            network.add_callback(method, re.compile(re.escape(ARM + state.namespace_id) + r"(?:\?.*)?$"), respond)
        with runtime.activate(SUB):
            yield state


def device(wire, name="arm-generated-name", external_id="backend-generated-external-id"):
    return {
        "id": wire.collection + "/" + name, "name": name, "etag": '"etag1"',
        "properties": {"externalDeviceId": external_id, "uuid": "uuid-" + name, "provisioningState": "Succeeded"},
    }


def result(registration_id="unique-enrollment", external_id="backend-generated-external-id"):
    return {
        "operationId": "operation", "status": "assigned",
        "registrationState": {"registrationId": registration_id, "deviceId": registration_id, "assignedHub": "modern",
                              "registryDeviceExternalId": external_id, "connectionProfile": "MqttV5",
                              "issuedCertificateChain": ["unspecified-encoding"]},
    }


def start(wire):
    owner = registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    owner.before_submit()
    return owner


def controller(wire, mocker):
    fixtures = csr.fixtures
    mocker.patch.object(fixtures, "_state_paths", side_effect=lambda uid, kind: (
        str(wire.directory / f"state-{uid}-{kind}.lock"), str(wire.directory / f"state-{uid}-{kind}.json"),
    ))
    for kind, name in (("csrhub", "hub"), ("csrdps", "dps"), ("csrns", "ns")):
        fixtures._shared_acquire(
            UID, kind, lambda _uid, _kind, name=name: (name, wire.resources[name]),
            lambda name: wire.resources.get(name),
        )
        fixtures._shared_release(UID, kind, lambda _name: pytest.fail("Worker must retain the controller reference"))

    def delete_target(name):
        assert "ns" not in wire.resources
        wire.events.append("csr" + name)
        del wire.resources[name]
        receipts.after_delete(name)

    mocker.patch.object(fixtures, "_delete_dps", side_effect=delete_target)
    mocker.patch.object(fixtures, "_delete_hub", side_effect=delete_target)
    client = registry.adr_service_factory(fixtures.cli.az_cli, subscription_id=SUB)

    def invoke(command):
        if "ns delete " in command:
            client.namespaces.begin_delete(resource_group_name="rg", namespace_name="ns", polling=False)
            body = None
        else:
            raise AssertionError(command)
        return SimpleNamespace(as_json=lambda: body)

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    return SimpleNamespace(config=SimpleNamespace())


def assert_retained(wire, kinds=("csrns", "csrdps", "csrhub")):
    for kind in kinds:
        state = csr.fixtures._read_state(csr.fixtures._state_paths(UID, kind)[1])
        assert state["refcount"] == 1
        assert state["name"] in wire.resources


def test_real_sdk_resolves_external_id_to_distinct_arm_name_and_deletes_only_owned_device(wire):
    wire.devices["preexisting"] = device(wire, "preexisting", "unowned-external")
    owner = start(wire)
    intent = json.loads((wire.directory / owner._name("intent")).read_text())
    assert intent["registration_id"] == intent["device_id"] == "unique-enrollment"
    assert intent["dps_id"] == wire.resources["dps"]["id"] and intent["hub_id"] == wire.resources["hub"]["id"]
    assert [value["name"] for value in intent["baseline"]] == ["preexisting"]
    wire.devices["arm-generated-name"] = device(wire)
    wire.devices["unrelated-new"] = device(wire, "unrelated-new", "another-external")
    owner.record_result(result())
    owner.cleanup()
    assert set(wire.devices) == {"preexisting", "unrelated-new"}
    assert [path for method, path in wire.calls if method == "DELETE"] == [wire.collection + "/arm-generated-name"]
    assert all(
        (method == "GET" and path == wire.namespace_id)
        or path == wire.collection or path.startswith(wire.collection + "/")
        for method, path in wire.calls
    )
    assert wire.factory.call_args.kwargs["subscription_id"] == SUB
    registry.require_registry_cleanup_resolved()


def test_arm_casing_variation_does_not_change_identity_or_external_id_matching(wire):
    wire.resource["dps"]["dps"]["id"] = wire.resource["dps"]["dps"]["id"].swapcase()
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    wire.get_transform = lambda body: dict(body, id=body["id"].swapcase(), name=body["name"].swapcase())
    owner.record_result(result())
    owner.cleanup()
    assert not wire.devices


@pytest.mark.parametrize("defect", [
    "preexisting", "ambiguous", "different-external", "wrong-scope", "changed-uuid", "changed-etag",
])
def test_unowned_ambiguous_and_changed_registry_devices_are_not_deleted(wire, defect):
    if defect == "preexisting":
        wire.devices["arm-generated-name"] = device(wire)
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    if defect == "ambiguous":
        wire.devices["second"] = device(wire, "second")
    elif defect == "different-external":
        wire.devices["arm-generated-name"]["properties"]["externalDeviceId"] = "not-the-issued-device"
    elif defect == "wrong-scope":
        wire.devices["arm-generated-name"]["id"] = wire.collection.replace("/ns/", "/foreign/") + "/arm-generated-name"
    elif defect == "changed-uuid":
        wire.get_transform = lambda body: dict(body, properties=dict(body["properties"], uuid="replacement"))
    elif defect == "changed-etag":
        wire.get_transform = lambda body: dict(body, etag='"concurrent-update"')
    owner.record_result(result())
    with pytest.raises(AssertionError):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)
    assert (wire.directory / owner._name("quarantine")).is_file()
    with pytest.raises(AssertionError, match="quarantined"):
        registry.require_registry_cleanup_resolved()


def test_ambiguity_is_sticky_when_issued_device_disappears_before_real_controller_reconciliation(wire, mocker):
    session = controller(wire, mocker)
    owner = start(wire)
    wire.devices["issued"] = device(wire, "issued")
    wire.devices["foreign"] = device(wire, "foreign")
    owner.record_result(result())
    with pytest.raises(AssertionError, match="Ambiguous"):
        owner.cleanup()
    conflict_path = wire.directory / owner._name("conflict")
    conflict = conflict_path.read_bytes()
    assert {value["name"] for value in json.loads(conflict)["devices"]} == {"issued", "foreign"}
    del wire.devices["issued"]
    # A repeated external-ID correlation is not additional authoritative ARM identity proof.
    owner.record_result(result())
    for _ in range(2):
        with pytest.raises(AssertionError, match="Conflicting"):
            registry.cleanup_registry_devices(receipts._owned("ns"))
        with pytest.raises(AssertionError, match="quarantined"):
            csr.fixtures.pytest_sessionfinish(session)
        assert conflict_path.read_bytes() == conflict
        assert set(wire.devices) == {"foreign"}
        assert not any(method == "DELETE" for method, _ in wire.calls)
        assert not wire.events
        assert_retained(wire)


@pytest.mark.parametrize("contents", ["{}", "null", "invalid-json"])
def test_damaged_conflict_receipt_cannot_authorize_a_survivor(wire, contents):
    owner = start(wire)
    wire.devices["foreign"] = device(wire, "foreign")
    owner.record_result(result())
    (wire.directory / owner._name("conflict")).write_text(contents)
    with pytest.raises(AssertionError, match="Conflicting"):
        owner.cleanup()
    with pytest.raises(AssertionError, match="quarantined"):
        registry.require_registry_cleanup_resolved()
    assert not any(method == "DELETE" for method, _ in wire.calls)
    assert "foreign" in wire.devices


@pytest.mark.parametrize("failure", [None, "namespace-409", "ca", "namespace-role"])
def test_registry_completion_does_not_release_controller_targets_until_namespace_absence(wire, mocker, failure):
    session = controller(wire, mocker)
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    owner.cleanup()
    registry.require_registry_cleanup_resolved()
    if failure == "namespace-409":
        wire.namespace_delete_status = 409
    elif failure == "namespace-role":
        mocker.patch.object(csr, "_remove_namespace_self_role", side_effect=HttpResponseError(
            message="Exact owned namespace role cleanup denied",
            response=SimpleNamespace(status_code=403, reason="Forbidden", headers={}),
        ))
    elif failure == "ca":
        namespace = receipts._owned("ns")
        child = {
            "id": namespace["id"] + "/certificateAuthorities/rootca", "tags": namespace["tags"],
            "properties": {"provisioningState": "Succeeded"},
        }
        receipts.write("csr-child-root.json", {"id": child["id"], "tags": child["tags"]})
        mocker.patch.object(csr, "find_child", return_value=child)
        original = csr.invoke

        def ca_failure(command):
            if "ns ca delete " in command:
                raise HttpResponseError(
                    message="CA cleanup rejected",
                    response=SimpleNamespace(status_code=409, reason="Conflict", headers={}),
                )
            return original(command)
        mocker.patch.object(csr, "invoke", side_effect=ca_failure)
    if failure:
        with pytest.raises(HttpResponseError) as raised:
            csr.fixtures.pytest_sessionfinish(session)
        assert raised.value.status_code == (403 if failure == "namespace-role" else 409)
        assert not wire.events
        assert_retained(wire)
        assert not (wire.directory / "deleted-csrns.json").exists()
    else:
        csr.fixtures.pytest_sessionfinish(session)
        assert wire.events == ["csrns", "csrdps", "csrhub"]
        assert not wire.resources
        assert (wire.directory / "deleted-csrns.json").is_file()
        for kind in ("csrns", "csrdps", "csrhub"):
            assert csr.fixtures._read_state(csr.fixtures._state_paths(UID, kind)[1]) is None


@pytest.mark.parametrize("defect", [
    "missing-proof", "wrong-id", "false-proof", "null-claim", "empty-claim", "present", "malformed", "403", "absent",
])
def test_namespace_absence_requires_exact_completion_and_current_scoped_404(wire, defect):
    if defect != "missing-proof":
        receipts.after_delete("ns")
    if defect in ("wrong-id", "false-proof"):
        path = wire.directory / "deleted-csrns.json"
        value = json.loads(path.read_text())
        value["id" if defect == "wrong-id" else "delete_completed"] = "foreign" if defect == "wrong-id" else False
        path.write_text(json.dumps(value))
    if defect in ("null-claim", "empty-claim"):
        (wire.directory / "owned-csrns.json").write_text("null" if defect == "null-claim" else "{}")
    if defect == "malformed":
        wire.namespace_get_transform = lambda _body: None
    elif defect == "403":
        wire.namespace_get_status = 403
    elif defect == "absent":
        del wire.resources["ns"]
    if defect == "absent":
        registry.require_namespace_cleanup_resolved()
    else:
        with pytest.raises(HttpResponseError if defect == "403" else AssertionError):
            registry.require_namespace_cleanup_resolved()
    if defect in ("missing-proof", "wrong-id", "false-proof", "null-claim", "empty-claim"):
        assert not wire.calls
    else:
        assert wire.calls == [("GET", wire.namespace_id)]


@pytest.mark.parametrize("field,value", [
    ("registrationId", "another-enrollment"), ("deviceId", "another-device"), ("assignedHub", "foreign-hub"),
])
def test_conflicting_registration_results_quarantine_without_delete(wire, field, value):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    response = result()
    response["registrationState"][field] = value
    with pytest.raises(AssertionError, match="quarantined"):
        owner.record_result(response)
    with pytest.raises(AssertionError, match="Conflicting"):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("body", [{}, {"value": None}, {"value": [], "nextLink": ARM + "/foreign"}])
def test_malformed_or_cross_scope_paging_fails_before_registration_intent(wire, body):
    wire.list_body = body
    with pytest.raises(AssertionError, match="Malformed|pagination"):
        start(wire)
    assert wire.calls == [("GET", wire.namespace_id), ("GET", wire.collection)]
    assert not list(wire.directory.glob("csr-registry-intent-*.json"))


@pytest.mark.parametrize("region,endpoint", [
    ("centraluseuap", ARM),
    ("australiaeast", "https://management.azure.com"),
    ("centraluseuap", "https://management.azure.com"),
])
@pytest.mark.parametrize("continuation", ["same", "other", "foreign", "http", "fragment"])
def test_registry_pagination_stays_on_selected_target(monkeypatch, region, endpoint, continuation):
    monkeypatch.setenv("azext_iot_dps_test_location", region)
    monkeypatch.setenv("azext_iot_test_arm_endpoint", endpoint)
    namespace_id = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
    collection = namespace_id + "/registryDevices"
    next_endpoint = endpoint
    if continuation == "other":
        next_endpoint = "https://management.azure.com" if endpoint == ARM else ARM
    elif continuation == "http":
        next_endpoint = endpoint.replace("https:", "http:")
    next_path = collection + ("/foreign" if continuation == "foreign" else "")
    query = {"api-version": "2026-11-02-preview", "$skiptoken": "next"}
    next_link = f"{next_endpoint}{next_path}?api-version={query['api-version']}&$skiptoken=next"
    if continuation == "fragment":
        next_link += "#foreign"
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 9999999999))
    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        network.add(
            responses.GET, endpoint + collection,
            match=[responses.matchers.query_param_matcher({"api-version": query["api-version"]})],
            json={"value": [], "nextLink": next_link},
        )
        network.add(
            responses.GET, endpoint + collection,
            match=[responses.matchers.query_param_matcher(query)],
            json={"value": []},
        )
        with DeviceRegistryMgmtClient(credential, SUB, base_url=endpoint, retry_total=0) as client:
            owner = registry.RegistryDeviceOwnership.__new__(registry.RegistryDeviceOwnership)
            owner.namespace = {"id": namespace_id, "name": "ns", "resource_group": "rg"}
            owner._client = client
            if continuation == "same":
                assert owner._list() == []
                assert len(network.calls) == 2
                assert all(call.request.url.startswith(endpoint + collection) for call in network.calls)
            else:
                with pytest.raises(AssertionError, match="pagination escaped"):
                    owner._list()
                assert len(network.calls) == 1


@pytest.mark.parametrize("status", [400, 403, 500])
def test_registry_lookup_failure_never_triggers_mutation(wire, status):
    owner = start(wire)
    owner.record_result(result())
    wire.list_status = status
    with pytest.raises(HttpResponseError):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("status", [400, 403, 500])
def test_registry_predelete_get_error_is_preserved_without_delete(wire, status):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    wire.get_status = status
    with pytest.raises(HttpResponseError) as raised:
        owner.cleanup()
    assert raised.value.status_code == status
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("field,value", [("namespace_id", "foreign"), ("subscription", "foreign"), ("dps_id", "foreign")])
def test_controller_refuses_untrusted_persisted_intent_without_sdk_mutation(wire, field, value):
    owner = start(wire)
    path = wire.directory / owner._name("intent")
    intent = json.loads(path.read_text())
    intent[field] = value
    path.write_text(json.dumps(intent))
    before = list(wire.calls)
    with pytest.raises(AssertionError, match="intent"):
        registry.cleanup_registry_devices(receipts._owned("ns"))
    assert wire.calls == before


@pytest.mark.parametrize("target", ["dps", "hub", "namespace"])
def test_concurrent_target_change_refuses_registration_intent(wire, target):
    owner = registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    if target == "dps":
        wire.resources[target]["properties"]["idScope"] = "replacement"
    elif target == "hub":
        wire.resources[target]["properties"]["deviceHostName"] = "foreign"
    else:
        wire.resources["ns"]["properties"]["provisioning"]["endpoints"]["dps"]["resourceId"] += "-other"
    with pytest.raises(AssertionError):
        owner.before_submit()
    assert wire.calls == [("GET", wire.namespace_id)]
    assert not list(wire.directory.glob("csr-registry-intent-*.json"))


def test_failed_delete_is_not_replayed_by_controller_reconciliation(wire):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    wire.delete_status = 403
    with pytest.raises(HttpResponseError):
        owner.cleanup()
    with pytest.raises(AssertionError, match="Timed out"):
        registry.cleanup_registry_devices(receipts._owned("ns"))
    assert sum(method == "DELETE" for method, _ in wire.calls) == 1
    # An independently confirmed deletion can resolve the quarantine without another DELETE.
    del wire.devices["arm-generated-name"]
    registry.cleanup_registry_devices(receipts._owned("ns"))
    registry.require_registry_cleanup_resolved()


def test_controller_reconciles_persisted_intent_and_deletes_device_before_namespace(wire, mocker):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    commands = []

    def invoke(command):
        commands.append(command)
        if "ns delete " in command:
            assert not wire.devices
            del wire.resources["ns"]
        elif "ns show " in command:
            raise ResourceNotFoundError("ResourceNotFound") from None
        return SimpleNamespace(as_json=lambda: None)

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    csr.delete_namespace("ns")
    assert not wire.devices and "ns" not in wire.resources
    assert any("ns delete " in command for command in commands)
    assert (wire.directory / owner._name("completed")).is_file()


@pytest.mark.parametrize("failure", [None, "assertion", "operation-known", "response-lost"])
def test_actual_scenario_cleans_after_assertion_or_partial_result_and_quarantines_unknown_external_id(
    wire, tmp_path, mocker, failure,
):
    commands = []
    enrollment_exists = False
    issued = result()
    mocker.patch.object(scenario, "generate_names", return_value="unique-enrollment")
    registry_assertions = mocker.patch.object(scenario, "assert_registry_registration")

    def invoke(command):
        nonlocal enrollment_exists
        commands.append(command)
        if "enrollment show " in command:
            body = "unique-enrollment" if enrollment_exists else None
        elif "enrollment create " in command:
            enrollment_exists = True
            body = {"registrationId": "unique-enrollment", "namespaceName": "ns",
                    "certificateAuthorityName": "issuingca", "certificatePolicyName": "leafpolicy"}
        elif "enrollment registration show " in command:
            body = {"registrationId": "unique-enrollment", "deviceId": "unique-enrollment",
                    "assignedHub": "modern", "status": "assigned"}
        elif "enrollment delete " in command:
            enrollment_exists = False
            body = None
        elif "enrollment registration delete " in command:
            assert not wire.devices
            body = None
        elif "device registration create " in command:
            assert list(wire.directory.glob("csr-registry-intent-*.json"))
            wire.devices["arm-generated-name"] = device(wire)
            if failure == "response-lost":
                raise ForbiddenError("Registration response lost")
            body = deepcopy(issued)
            if failure == "assertion":
                body["registrationState"]["issuedCertificateChain"] = []
            elif failure == "operation-known":
                body = {"operationId": "operation", "status": "assigning",
                        "registrationState": {"registrationId": "unique-enrollment"}}
        elif "operation-status " in command:
            body = issued
        else:
            raise AssertionError(command)
        return SimpleNamespace(as_json=lambda: body)

    mocker.patch.object(csr, "invoke", side_effect=invoke)
    mocker.patch.object(scenario, "invoke", side_effect=invoke)
    material = tmp_path / "material"
    material.mkdir()
    if failure:
        with pytest.raises(AssertionError) as raised:
            scenario.test_register_and_issue_certificate_contract(wire.resource, material, None)
        if failure == "response-lost":
            assert "quarantined" in str(raised.value)
            assert isinstance(raised.value.__context__, ForbiddenError)
    else:
        scenario.test_register_and_issue_certificate_contract(wire.resource, material, None)
    assert not list(material.iterdir())
    if failure == "response-lost":
        assert wire.devices and enrollment_exists
        assert not any(method == "DELETE" for method, _ in wire.calls)
        assert not any("registration delete " in command for command in commands)
        with pytest.raises(AssertionError, match="quarantined"):
            csr.delete_namespace("ns")
        assert "ns" in wire.resources
    else:
        assert not wire.devices and not enrollment_exists
        assert sum(method == "DELETE" for method, _ in wire.calls) == 1
    assert registry_assertions.call_count == (0 if failure else 1)


def test_read_resolution_does_not_persist_etag_before_later_profile_mutation(wire):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    assert owner.read_device()["etag"] == '"etag1"'
    assert not (wire.directory / owner._name("resolved")).exists()
    assert "etag" not in json.loads((wire.directory / owner._name("observed")).read_text())["device"]
    wire.devices["arm-generated-name"]["etag"] = '"after-profile-action"'
    owner.cleanup()
    assert not wire.devices
    assert json.loads((wire.directory / owner._name("resolved")).read_text())["device"]["etag"] == '"after-profile-action"'


def test_read_resolution_requires_prior_registration_intent(wire):
    owner = registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    with pytest.raises(AssertionError, match="pre-submission"):
        owner.read_device()
    assert not wire.calls


@pytest.mark.parametrize("started,resolved", [(False, False), (True, True)])
def test_profile_mutation_cannot_start_without_active_unfrozen_ownership(wire, started, resolved):
    owner = start(wire) if started else registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    if resolved:
        owner._write("resolved", {"device": device(wire)})
    with pytest.raises(AssertionError, match="active ownership"):
        with owner.certificate_revocation("profile"):
            pytest.fail("Mutation must not start.")
    assert not (wire.directory / owner._name("profile-action")).exists()


@pytest.mark.parametrize("replacement", ["name", "uuid"])
def test_read_resolution_identity_cannot_change_while_etag_is_unfrozen(wire, replacement):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    owner.read_device()
    if replacement == "name":
        wire.devices.clear()
        wire.devices["replacement"] = device(wire, name="replacement")
    else:
        wire.devices["arm-generated-name"]["properties"]["uuid"] = "replacement-uuid"
    with pytest.raises(AssertionError, match="identity changed"):
        owner.read_device()
    with pytest.raises(AssertionError, match="Conflicting"):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("kind", ["observed", "profile-action"])
@pytest.mark.parametrize("contents", ["null", "{}", '{"completed":true,"namespace_id":"foreign"}'])
def test_damaged_new_receipts_cannot_authorize_cleanup(wire, kind, contents):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    (wire.directory / owner._name(kind)).write_text(contents)
    with pytest.raises(AssertionError):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("change", [
    lambda value: value["properties"].update(externalDeviceId=""),
    lambda value: value["properties"].update(uuid=[]),
    lambda value: value.update(etag=42),
])
def test_malformed_identity_never_establishes_registry_ownership(wire, change):
    owner = start(wire)
    current = device(wire)
    change(current)
    wire.devices[current["name"]] = current
    owner.record_result(result())
    with pytest.raises(AssertionError, match="externalDeviceId|malformed"):
        owner.read_device()
    assert not any(method == "DELETE" for method, _ in wire.calls)


@pytest.mark.parametrize("value", [None, [], {"registrationState": []}, {"operationId": 123}])
def test_invalid_registration_result_never_authorizes_cleanup(wire, value):
    owner = start(wire)
    with pytest.raises(AssertionError, match="correlation|operation changed|Malformed registration state"):
        owner.record_result(value)
    assert not (wire.directory / owner._name("completed")).exists()


def test_changed_operation_or_external_identity_is_not_reconciled_by_metadata(wire):
    owner = start(wire)
    owner.record_result(result())
    changed = result()
    changed["operationId"] = "replacement"
    with pytest.raises(AssertionError, match="operation changed"):
        owner.record_result(changed)
    with pytest.raises(AssertionError, match="external ID changed"):
        owner.record_result(result(external_id="foreign"))
    with pytest.raises(AssertionError, match="Conflicting"):
        owner._external_id()
    assert not any(method == "DELETE" for method, _ in wire.calls)


def test_baseline_duplicate_devices_cannot_claim_ownership(wire):
    wire.list_body = {"value": [device(wire), device(wire)]}
    with pytest.raises(AssertionError, match="Duplicate"):
        start(wire)
    assert not list(wire.directory.glob("csr-registry-intent-*.json"))


def test_current_owned_target_id_must_still_match_intent(wire):
    owner = registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    owner.intent["hub_id"] += "-foreign"
    with pytest.raises(AssertionError, match="target changed"):
        owner.before_submit()
    assert not owner.started


def test_idle_cleanup_and_no_namespace_receipt_do_not_mutate(wire):
    owner = registry.RegistryDeviceOwnership(wire.resource, "unique-enrollment")
    owner.cleanup()
    (wire.directory / "owned-csrns.json").unlink()
    registry.require_namespace_cleanup_resolved()
    assert not wire.calls


@pytest.mark.parametrize("change", [
    lambda value: value.update(kind="foreign"),
    lambda value: value.update(phase="foreign"),
    lambda value: value.update(subscription="foreign"),
])
def test_namespace_receipt_mismatch_cannot_release_targets(wire, change):
    path = wire.directory / "owned-csrns.json"
    record = json.loads(path.read_text())
    change(record)
    path.write_text(json.dumps(record))
    with pytest.raises(AssertionError, match="inconsistent"):
        registry.require_namespace_cleanup_resolved()
    assert not wire.calls


def test_resolved_receipt_external_id_cannot_change_before_delete(wire):
    owner = start(wire)
    wire.devices["arm-generated-name"] = device(wire)
    owner.record_result(result())
    snapshot = owner._snapshot(device(wire))
    snapshot["external_id"] = "foreign"
    owner._write("resolved", {"device": snapshot})
    with pytest.raises(AssertionError, match="external ID disagree"):
        owner.cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)


def test_completion_receipt_without_resolved_identity_cannot_release_quarantine(wire):
    owner = start(wire)
    owner._write("completed", {"device_id": wire.collection + "/foreign", "absent": True})
    for cleanup in (owner.cleanup, registry.require_registry_cleanup_resolved):
        with pytest.raises(AssertionError, match="Malformed RegistryDevice completion"):
            cleanup()
    assert not any(method == "DELETE" for method, _ in wire.calls)
