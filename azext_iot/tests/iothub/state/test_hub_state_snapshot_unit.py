# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Authoritative snapshots and restores through ADR's retained msrest HTTP clients."""

import base64
from copy import deepcopy
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import responses
from azure.cli.core.azclierror import AzCLIError
from msrest.exceptions import ClientRequestError

from azext_iot.iothub.common import HubAspects, IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS
from azext_iot.iothub.providers.state import StateProvider


def _identity(device_id, module=False):
    authentication = {
        "parent": {"type": "sas", "symmetricKey": {"primaryKey": "offline-primary", "secondaryKey": "offline-secondary"}},
        "child": {"type": "certificateAuthority"},
        "grandchild": {
            "type": "selfSigned", "x509Thumbprint": {"primaryThumbprint": "A" * 40, "secondaryThumbprint": "B" * 40},
        },
    }[device_id]
    authentication.setdefault("x509Thumbprint", {"primaryThumbprint": None, "secondaryThumbprint": None})
    parent = {"parent": None, "child": "parent", "grandchild": "child"}[device_id]
    result = {
        "deviceId": device_id, "authentication": deepcopy(authentication),
        "connectionState": "Disconnected", "status": "enabled", "capabilities": {"iotEdge": True},
        "deviceScope": f"ms-azure-iot-edge://{device_id}-generation",
        "parentScopes": [f"ms-azure-iot-edge://{parent}-generation"] if parent else [],
        "etag": "unit-etag", "generationId": "generation", "cloudToDeviceMessageCount": 0,
        "connectionStateUpdatedTime": "2026-01-01T00:00:00Z", "lastActivityTime": "2026-01-01T00:00:00Z",
    }
    if module:
        result.update(moduleId="module", managedBy="offline")
    return result


def _twin(device_id, module=False, populated=True):
    result = {key: None for key in IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS}
    result.update({
        "deviceId": device_id, "capabilities": {"iotEdge": True}, "status": "enabled",
        "connectionState": "Disconnected",
        "properties": {"desired": {"$metadata": {}, "$version": 2}, "reported": {"readOnly": "value"}},
        "parentScopes": _identity(device_id)["parentScopes"],
    })
    # Direct twin GET need not carry the identity fields exposed by query.
    result.pop("authenticationType")
    result.pop("x509Thumbprint")
    if populated:
        result["tags"] = {"owner": device_id, "nested": {"keep": "value"}}
        result["properties"]["desired"]["setting"] = {"value": device_id, "enabled": False, "count": 0}
    if module:
        result.update(moduleId="module", modelId="unit-model", authenticationType="sas", x509Thumbprint=None)
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
        } for device_id in ("parent", "child", "grandchild")},
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
    runtime = SimpleNamespace(stores=stores, requests=[], query_lag="missing-tags", read_failure=None, fail_kind="twins")

    def respond(request):
        runtime.requests.append(request)
        url = urlsplit(request.url)
        hub = url.hostname.split(".")[0]
        parts = url.path.strip("/").split("/")
        store = stores[hub]
        if parts == ["devices", "query"]:
            assert request.method == "POST"
            rows = []
            for device_id, value in store.items():
                row = deepcopy(value["twin"])
                row["authenticationType"] = value["identity"]["authentication"]["type"]
                row["x509Thumbprint"] = value["identity"]["authentication"].get("x509Thumbprint")
                row.pop("tags", None)
                row["properties"]["desired"] = {"$metadata": {}, "$version": 1, "stale": True}
                if runtime.query_lag == "wrong-tags":
                    row["tags"] = {"stale": True}
                elif runtime.query_lag == "ids-only":
                    row = {"deviceId": device_id}
                rows.append(row)
            return 200, {}, json.dumps(rows)
        device_id = parts[1]
        if hub == "origin" and len(parts) == 2 and parts[0] == runtime.fail_kind and runtime.read_failure:
            return runtime.read_failure, {}, json.dumps({"Message": "offline authoritative read failure"})
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
            entry["identity"] = dict(
                body, deviceId=device_id, etag="unit-etag", connectionState="Disconnected",
                deviceScope=f"ms-azure-iot-edge://{device_id}-generation",
            )
            # Retained service responses include empty thumbprints for SAS/CA identities.
            thumbprints = entry["identity"]["authentication"].setdefault("x509Thumbprint", {})
            for key in ("primaryThumbprint", "secondaryThumbprint"):
                thumbprints.setdefault(key, None)
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

    with responses.RequestsMock(assert_all_requests_are_fired=False) as network:
        for method in ("GET", "PUT", "POST", "PATCH", "DELETE"):
            network.add_callback(
                method, re.compile(r"https://(?:origin|destination)\.unit\.invalid/"),
                callback=respond, content_type="application/json",
            )
        runtime.origin = StateProvider(cmd=SimpleNamespace(), hub="origin", rg="unit-rg", export=True)
        runtime.destination = StateProvider(cmd=SimpleNamespace(), hub="destination", rg="unit-rg")
        yield runtime


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
        runtime.destination.upload_state(filename, hub_aspects=[HubAspects.Devices.value])
    assert set(runtime.stores["destination"]) == set(original)
    for device_id, source in original.items():
        destination = runtime.stores["destination"][device_id]
        for first, second in ((source, destination), (source["modules"]["module"], destination["modules"]["module"])):
            assert second["twin"]["tags"] == first["twin"]["tags"]
            assert second["twin"]["properties"]["desired"]["setting"] == first["twin"]["properties"]["desired"]["setting"]
            assert "stale" not in second["twin"]["properties"]["desired"]
            assert second["identity"]["authentication"] == first["identity"]["authentication"]
        assert destination["identity"].get("parentScopes", []) == source["identity"]["parentScopes"]
    assert runtime.stores["origin"] == original
    reads = [urlsplit(item.url).path for item in runtime.requests if item.method == "GET"
             and urlsplit(item.url).hostname == "origin.unit.invalid"]
    for device_id in original:
        assert reads.count(f"/twins/{device_id}") == 1
    for request in runtime.requests:
        if request.method == "PATCH":
            assert set(json.loads(request.body)["properties"]["desired"]) == {"setting"}


@pytest.mark.parametrize("status", [403, 404, 500])
@pytest.mark.parametrize("kind", ["twins", "devices"])
@pytest.mark.parametrize("operation", ["migrate", "file"])
def test_authoritative_read_failure_precedes_destination_changes(snapshot_service, tmp_path, status, kind, operation):
    runtime = snapshot_service
    runtime.read_failure, runtime.fail_kind = status, kind
    filename = tmp_path / "state.json"
    filename.write_text("existing snapshot", encoding="utf-8")
    # Retain the old SDK's retry/error contract rather than changing it for the backport.
    error_type = ClientRequestError if status == 500 else AzCLIError
    message = "too many 500 error responses" if status == 500 else "offline authoritative read failure"
    with pytest.raises(error_type, match=message):
        if operation == "migrate":
            runtime.destination.migrate_state(orig_hub="origin", replace=True, hub_aspects=[HubAspects.Devices.value])
        else:
            runtime.origin.save_state(str(filename), replace=True, hub_aspects=[HubAspects.Devices.value])
    assert filename.read_text(encoding="utf-8") == "existing snapshot"
    assert not runtime.stores["destination"]
    assert all(urlsplit(request.url).hostname == "origin.unit.invalid" for request in runtime.requests)
    assert all(request.method in ("GET", "POST") for request in runtime.requests)


@pytest.mark.parametrize("tags", [None, {}], ids=["absent", "explicit-empty"])
def test_snapshot_preserves_tag_presence_without_query_identity_fields(snapshot_service, tags):
    runtime = snapshot_service
    runtime.query_lag = "ids-only"
    runtime.origin.target.pop("sku_tier")
    for entry in runtime.stores["origin"].values():
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
    runtime.stores["origin"]["parent"]["twin"]["properties"] = {}
    with pytest.raises(KeyError, match="reported"):
        runtime.destination.migrate_state(orig_hub="origin", replace=True, hub_aspects=[HubAspects.Devices.value])
    assert not runtime.stores["destination"]
    assert all(urlsplit(request.url).hostname == "origin.unit.invalid" for request in runtime.requests)
