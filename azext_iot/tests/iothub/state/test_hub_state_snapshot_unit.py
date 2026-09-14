# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""State snapshots through real providers, restore operations and generated HTTP clients."""

import base64
from copy import deepcopy
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import responses
from azure.cli.core.azclierror import AzCLIError

from azext_iot.iothub.common import HubAspects, IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS
from azext_iot.iothub.providers.state import StateProvider
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
from azext_iot.tests.iothub.state._state_helpers import compare_devices
from azext_iot.tests.iothub.test_dataplane_wire_unit import RecordingTransport


def _identity(device_id, module=False):
    authentication = {"type": "certificateAuthority"} if device_id == "parent" and not module else {
        "type": "sas", "symmetricKey": {"primaryKey": "offline-primary", "secondaryKey": "offline-secondary"},
    }
    result = {
        "deviceId": device_id, "authentication": authentication,
        "connectionState": "Disconnected", "status": "enabled",
        "capabilities": {"iotEdge": True}, "deviceScope": f"ms-azure-iot-edge://{device_id}-generation",
        "parentScopes": ["ms-azure-iot-edge://parent-generation"] if device_id == "child" else [],
        "attributes": {"owner": device_id}, "adrDeviceProperties": {"uuid": f"source-{device_id}"},
        "etag": "unit-etag", "generationId": "generation", "connectionStateUpdatedTime": "time",
        "lastActivityTime": "time", "cloudToDeviceMessageCount": 0,
    }
    if module:
        result.update(moduleId="module", managedBy="offline")
        result.pop("adrDeviceProperties")
    return result


def _twin(device_id, module=False, populated=True):
    result = {key: None for key in IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS}
    result.update({
        "deviceId": device_id, "capabilities": {"iotEdge": True}, "status": "enabled",
        "connectionState": "Disconnected", "authenticationType": _identity(device_id, module)["authentication"]["type"],
        "properties": {"desired": {"$metadata": {}, "$version": 2}, "reported": {"readOnly": "value"}},
        "parentScopes": ["ms-azure-iot-edge://parent-generation"] if device_id == "child" else [],
    })
    if populated:
        result["tags"] = {"owner": device_id, "nested": {"keep": "value"}}
        result["properties"]["desired"]["setting"] = {"value": device_id, "enabled": False, "count": 0}
    if module:
        result.update(moduleId="module", modelId="unit-model")
    else:
        result.pop("moduleId")
    return result


@pytest.fixture
def snapshot_service(mocker):
    mocker.patch("azure.cli.core._profile.Profile.__init__", side_effect=AssertionError("No live Profile allowed"))
    mocker.patch("socket.socket.connect", side_effect=AssertionError("No live socket allowed"))
    stores = {
        "origin": {device_id: {
            "identity": _identity(device_id), "twin": _twin(device_id),
            "modules": {"module": {"identity": _identity(device_id, True), "twin": _twin(device_id, True)}},
        } for device_id in ("parent", "child")},
        "destination": {},
    }
    targets = {name: {
        "name": name, "entity": name + ".unit.invalid", "resourcegroup": "unit-rg", "sku_tier": "Standard",
        "policy": "iothubowner", "primarykey": base64.b64encode(b"offline-hub-policy").decode(),
    } for name in stores}
    mocker.patch(
        "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target",
        side_effect=lambda resource_name, **_: targets[resource_name],
    )
    clients, requests = [], []

    def client(**kwargs):
        transport = RecordingTransport()
        transport.requests = requests
        sdk = IotHubGatewayServiceAPIs(transport=transport, **kwargs)
        clients.append(sdk)
        return sdk

    mocker.patch("azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs", side_effect=client)
    runtime = SimpleNamespace(
        stores=stores, requests=requests, query_lag="missing-tags", twin_failure=None,
        wipe_on_parent_update=False, parent_writes=[],
    )

    def respond(request):
        url = urlsplit(request.url)
        hub = url.hostname.split(".")[0]
        parts = url.path.strip("/").split("/")
        store = stores[hub]
        if parts == ["devices", "query"]:
            assert request.method == "POST"
            rows = [deepcopy(value["twin"]) for value in store.values()]
            for row in rows:
                row.pop("tags", None)
                row["properties"]["desired"] = {"$metadata": {}, "$version": 1, "stale": True}
                if runtime.query_lag == "wrong-tags":
                    row["tags"] = {"stale": True}
                elif runtime.query_lag == "ids-only":
                    row.clear()
            if runtime.query_lag == "ids-only":
                rows = [{"deviceId": device_id} for device_id in store]
            return 200, {}, json.dumps(rows)
        device_id = parts[1]
        if parts[0] == "twins" and hub == "origin" and len(parts) == 2 and runtime.twin_failure:
            return runtime.twin_failure, {}, json.dumps({"Message": "offline twin failure"})
        if request.method == "PUT":
            body = json.loads(request.body)
            if len(parts) == 2:
                entry = store.setdefault(device_id, {
                    "identity": {}, "twin": _twin(device_id, populated=False), "modules": {},
                })
            else:
                entry = store[device_id]["modules"].setdefault("module", {
                    "identity": {}, "twin": _twin(device_id, module=True, populated=False),
                })
            # Simulate server-owned identity fields, never pre-populate writable restored values.
            entry["identity"] = dict(
                body, deviceId=device_id, etag="unit-etag", connectionState="Disconnected",
                deviceScope=f"ms-azure-iot-edge://{device_id}-generation",
            )
            entry["twin"]["authenticationType"] = body["authentication"]["type"]
            if "x509Thumbprint" in body["authentication"]:
                entry["twin"]["x509Thumbprint"] = deepcopy(body["authentication"]["x509Thumbprint"])
            if hub == "destination" and len(parts) == 2 and body.get("parentScopes") and entry["twin"].get("tags"):
                runtime.parent_writes.append((device_id, len(requests) - 1))
                if runtime.wipe_on_parent_update and device_id == "child":
                    entry["twin"].pop("tags")
            entry["twin"]["parentScopes"] = body.get("parentScopes", [])
            return 200, {}, json.dumps(entry["identity"])
        entry = store[device_id]
        if len(parts) == 3:
            assert request.method == "GET" and parts[2] == "modules"
            return 200, {}, json.dumps([item["identity"] for item in entry["modules"].values()])
        if len(parts) == 4:
            entry = entry["modules"][parts[3]]
        if parts[0] == "devices":
            assert request.method == "GET"
            return 200, {}, json.dumps(entry["identity"])
        assert parts[0] == "twins"
        if request.method == "PATCH":
            body = json.loads(request.body)
            if "tags" in body:
                entry["twin"]["tags"] = body["tags"]
            entry["twin"]["properties"]["desired"].update(body["properties"]["desired"])
        else:
            assert request.method == "GET"
        return 200, {}, json.dumps(entry["twin"])

    try:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
            for method in ("GET", "PUT", "POST", "PATCH"):
                network.add_callback(
                    method, re.compile(r"https://(?:origin|destination)\.unit\.invalid/"),
                    callback=respond, content_type="application/json",
                )
            runtime.origin = StateProvider(cmd=SimpleNamespace(), hub="origin", rg="unit-rg", export=True)
            runtime.destination = StateProvider(cmd=SimpleNamespace(), hub="destination", rg="unit-rg")
            yield runtime
    finally:
        for sdk in clients:
            sdk.close()


@pytest.mark.parametrize("operation", ["migrate", "file"])
@pytest.mark.parametrize("query_lag", ["missing-tags", "wrong-tags", "ids-only"])
def test_migration_and_file_restore_use_authoritative_twins(snapshot_service, tmp_path, operation, query_lag):
    runtime = snapshot_service
    runtime.query_lag = query_lag
    original = deepcopy(runtime.stores["origin"])
    if operation == "migrate":
        runtime.destination.migrate_state(orig_hub="origin", hub_aspects=[HubAspects.Devices.value])
    else:
        filename = str(tmp_path / "state.json")
        runtime.origin.save_state(filename, hub_aspects=[HubAspects.Devices.value])
        with open(filename, encoding="utf-8") as snapshot_file:
            snapshot = json.load(snapshot_file)
        for device_id, source in original.items():
            assert snapshot["devices"][device_id]["identity"]["adrDeviceProperties"] == source["identity"]["adrDeviceProperties"]
        runtime.destination.upload_state(filename, hub_aspects=[HubAspects.Devices.value])
    assert set(runtime.stores["destination"]) == set(original)
    for device_id, source in original.items():
        destination = runtime.stores["destination"][device_id]
        for first, second in ((source, destination), (source["modules"]["module"], destination["modules"]["module"])):
            assert second["twin"]["tags"] == first["twin"]["tags"]
            assert second["twin"]["properties"]["desired"]["setting"] == first["twin"]["properties"]["desired"]["setting"]
            assert "stale" not in second["twin"]["properties"]["desired"]
            assert second["identity"]["authentication"] == first["identity"]["authentication"]
            assert second["identity"]["attributes"] == first["identity"]["attributes"]
        assert destination["identity"].get("parentScopes", []) == source["identity"]["parentScopes"]
    assert runtime.stores["origin"] == original
    reads = [urlsplit(item.url).path for item in runtime.requests if item.method == "GET"
             and urlsplit(item.url).hostname == "origin.unit.invalid"]
    assert reads.count("/twins/parent") == reads.count("/twins/child") == 1
    for request in runtime.requests:
        if request.method in ("PUT", "PATCH"):
            body = json.loads(request.body)
            assert "adrDeviceProperties" not in body
            if request.method == "PATCH":
                assert set(body["properties"]["desired"]) == {"setting"}


@pytest.mark.parametrize("status", [403, 404, 500])
@pytest.mark.parametrize("operation", ["migrate", "file"])
def test_authoritative_twin_failure_precedes_destination_changes(snapshot_service, tmp_path, status, operation):
    runtime = snapshot_service
    runtime.twin_failure = status
    filename = tmp_path / "state.json"
    filename.write_text("existing snapshot", encoding="utf-8")
    with pytest.raises(AzCLIError, match="offline twin failure"):
        if operation == "migrate":
            runtime.destination.migrate_state(orig_hub="origin", replace=True, hub_aspects=[HubAspects.Devices.value])
        else:
            runtime.origin.save_state(str(filename), replace=True, hub_aspects=[HubAspects.Devices.value])
    assert filename.read_text(encoding="utf-8") == "existing snapshot"
    assert not runtime.stores["destination"]
    assert all(urlsplit(request.url).hostname == "origin.unit.invalid" for request in runtime.requests)
    assert sum(urlsplit(request.url).path == "/twins/parent" for request in runtime.requests) == 1


@pytest.mark.parametrize("tags", [None, {}], ids=["absent", "explicit-empty"])
def test_snapshot_keeps_tag_presence_and_does_not_require_query_identity_fields(snapshot_service, tags):
    runtime = snapshot_service
    runtime.query_lag = "ids-only"
    runtime.origin.target.pop("sku_tier")  # Connection-string targets need not contain ARM SKU metadata.
    for entry in runtime.stores["origin"].values():
        entry["twin"].pop("authenticationType")
        entry["twin"].pop("x509Thumbprint")
        if tags is None:
            entry["twin"].pop("tags")
        else:
            entry["twin"]["tags"] = tags
    snapshot = runtime.origin.download_devices(runtime.origin.target)
    for device_id, entry in snapshot.items():
        assert ("tags" in entry["twin"]) == (tags is not None)
        assert "tags" not in entry["identity"]
        assert entry["identity"]["authentication"] == runtime.stores["origin"][device_id]["identity"]["authentication"]


def test_malformed_authoritative_twin_does_not_fall_back_to_query(snapshot_service):
    runtime = snapshot_service
    # Query still supplies a complete stale properties object; direct GET is malformed.
    runtime.stores["origin"]["parent"]["twin"]["properties"] = {}
    with pytest.raises(KeyError, match="reported"):
        runtime.destination.migrate_state(orig_hub="origin", replace=True, hub_aspects=[HubAspects.Devices.value])
    assert not runtime.stores["destination"]
    assert all(urlsplit(request.url).hostname == "origin.unit.invalid" for request in runtime.requests)


@pytest.mark.parametrize("operation", ["migrate", "file"])
@pytest.mark.parametrize("late_wipe", [False, True], ids=["preserved", "late-loss-detected"])
def test_three_authentication_edge_chain_preserves_twins_and_detects_late_loss(
    snapshot_service, tmp_path, operation, late_wipe
):
    runtime = snapshot_service
    runtime.wipe_on_parent_update = late_wipe
    authentications = {
        "parent": {"type": "sas", "symmetricKey": {"primaryKey": "root-primary", "secondaryKey": "root-secondary"}},
        "child": {"type": "certificateAuthority"},
        "grandchild": {
            "type": "selfSigned", "x509Thumbprint": {"primaryThumbprint": "A" * 40, "secondaryThumbprint": "B" * 40},
        },
    }
    parents = {"parent": None, "child": "parent", "grandchild": "child"}
    runtime.stores["origin"].clear()
    for device_id, authentication in authentications.items():
        identity = _identity(device_id)
        twin = _twin(device_id)
        identity["authentication"] = deepcopy(authentication)
        identity["parentScopes"] = (
            [f"ms-azure-iot-edge://{parents[device_id]}-generation"] if parents[device_id] else []
        )
        twin.update(authenticationType=authentication["type"], parentScopes=identity["parentScopes"])
        if "x509Thumbprint" in authentication:
            twin["x509Thumbprint"] = deepcopy(authentication["x509Thumbprint"])
        module_identity = _identity(device_id, module=True)
        module_identity["authentication"] = deepcopy(authentication)
        runtime.stores["origin"][device_id] = {
            "identity": identity, "twin": twin,
            "modules": {"module": {"identity": module_identity, "twin": _twin(device_id, module=True)}},
        }
    original = deepcopy(runtime.stores["origin"])
    if operation == "migrate":
        runtime.destination.migrate_state(orig_hub="origin", hub_aspects=[HubAspects.Devices.value])
    else:
        filename = str(tmp_path / "chain.json")
        runtime.origin.save_state(filename, hub_aspects=[HubAspects.Devices.value])
        runtime.destination.upload_state(filename, hub_aspects=[HubAspects.Devices.value])

    assert {device_id for device_id, _ in runtime.parent_writes} == {"child", "grandchild"}
    for device_id, write_index in runtime.parent_writes:
        request = runtime.requests[write_index]
        body = json.loads(request.body)
        assert "tags" not in body and "properties" not in body
        previous_twin_patches = [
            index for index, candidate in enumerate(runtime.requests[:write_index])
            if candidate.method == "PATCH" and urlsplit(candidate.url).hostname == "destination.unit.invalid"
            and urlsplit(candidate.url).path == f"/twins/{device_id}"
        ]
        assert previous_twin_patches, "Parent restoration must follow the actual device-twin restoration."
    assert runtime.stores["origin"] == original
    for device_id, source in original.items():
        destination = runtime.stores["destination"][device_id]
        assert destination["identity"]["authentication"] == source["identity"]["authentication"]
        assert destination["identity"].get("parentScopes", []) == source["identity"]["parentScopes"]
        assert destination["twin"]["properties"]["desired"]["setting"] == source["twin"]["properties"]["desired"]["setting"]
        assert destination["modules"]["module"]["twin"]["tags"] == source["modules"]["module"]["twin"]["tags"]
        twins = [deepcopy(entry["twin"]) for entry in (source, destination)]
        if source["identity"]["authentication"]["type"] == "sas":
            for twin, entry in zip(twins, (source, destination)):
                twin["symmetricKey"] = entry["identity"]["authentication"]["symmetricKey"]
        if late_wipe and device_id == "child":
            assert "tags" not in destination["twin"]
            with pytest.raises(AssertionError):
                compare_devices(*twins)
        else:
            assert destination["twin"]["tags"] == source["twin"]["tags"]
            compare_devices(*twins)
