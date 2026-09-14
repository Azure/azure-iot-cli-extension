# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Pre-mutation snapshot validation and exclusively owned ARM staging."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shlex
import stat

import pytest
from azure.cli.core.azclierror import AzCLIError, BadRequestError, FileOperationError

from azext_iot.iothub.common import HubAspects
from azext_iot.iothub.providers import state as subject
from azext_iot.tests.iothub.state.test_hub_state_methods_unit import (
    TestUploadHubFromDict as _UploadFixtures,
    _device_identity,
    _provider,
)


@pytest.fixture
def snapshot():
    result = _UploadFixtures()._arm_state()
    result.update(_UploadFixtures()._configs_state())
    result["devices"] = {
        "device": {
            "identity": _device_identity(),
            "twin": {"tags": {"owner": "user"}, "properties": {"desired": {"nested": [False, 0, None]}}},
            "modules": {
                "module": {
                    "identity": _device_identity(),
                    "twin": {"properties": {"desired": {}}, "tags": {"module": "user"}},
                },
            },
        },
    }
    return result


@pytest.fixture
def restore(mocker):
    provider = _provider(mocker)
    provider.delete_aspects = mocker.Mock()
    provider.upload_hub_from_dict = mocker.Mock()
    return provider


@pytest.mark.parametrize("content", ["", "{", "[]", "null", "42", '{"devices": []}', "{}"])
def test_invalid_file_precedes_every_destination_mutation(restore, tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((BadRequestError, FileOperationError), match="(Hub state|state file)"):
        restore.upload_state(str(path), replace=True, hub_aspects=["devices"])
    restore.delete_aspects.assert_not_called()
    restore.upload_hub_from_dict.assert_not_called()
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("failure", ["missing", "encoding", "permission", "directory"])
def test_unreadable_file_precedes_every_destination_mutation(restore, tmp_path, mocker, failure):
    path = tmp_path / "state.json"
    if failure == "encoding":
        path.write_bytes(b"\xff")
    elif failure == "permission":
        mocker.patch("builtins.open", side_effect=PermissionError("denied"))
    elif failure == "directory":
        path.mkdir()
    with pytest.raises(FileOperationError, match=str(path)):
        restore.upload_state(str(path), replace=True, hub_aspects=["devices"])
    restore.delete_aspects.assert_not_called()
    restore.upload_hub_from_dict.assert_not_called()


@pytest.mark.parametrize("aspects", [["devices"], ["configurations"], ["arm"], HubAspects.list()])
def test_selected_snapshot_is_validated_before_delete_without_mutation(restore, snapshot, tmp_path, aspects):
    selected = {aspect: snapshot[aspect] for aspect in aspects}
    original = deepcopy(selected)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(selected), encoding="utf-8")
    order = []
    restore.delete_aspects.side_effect = lambda *_: order.append("delete")
    restore.upload_hub_from_dict.side_effect = lambda *_: order.append("upload")
    restore.upload_state(str(path), replace=True, hub_aspects=aspects)
    assert order == ["delete", "upload"]
    restore.upload_hub_from_dict.assert_called_once_with(original, aspects)
    assert selected == original
    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("aspects", [["devices"], ["configurations"], ["devices", "configurations"]])
def test_explicit_empty_selected_data_is_valid(restore, tmp_path, aspects):
    empty = {"devices": {}, "configurations": {"admConfigurations": {}, "edgeDeployments": {}}}
    path = tmp_path / "state.json"
    selected = {aspect: empty[aspect] for aspect in aspects}
    path.write_text(json.dumps(selected), encoding="utf-8")
    restore.upload_state(str(path), replace=True, hub_aspects=aspects)
    restore.delete_aspects.assert_called_once_with(True, aspects)
    restore.upload_hub_from_dict.assert_called_once_with(selected, aspects)


def test_nonselected_aspects_need_not_be_valid(restore, tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"devices": {}, "arm": null, "configurations": []}', encoding="utf-8")
    restore.upload_state(str(path), replace=True, hub_aspects=["devices"])
    restore.delete_aspects.assert_called_once_with(True, ["devices"])


def test_unknown_selected_aspect_is_rejected():
    with pytest.raises(BadRequestError, match="unsupported Hub aspect"):
        subject._validate_hub_state({"unknown": {}}, ["unknown"])


def test_absent_twin_tags_are_preserved(snapshot):
    device = snapshot["devices"]["device"]
    del device["twin"]["tags"]
    del device["modules"]["module"]["twin"]["tags"]
    original = deepcopy(snapshot)
    subject._validate_hub_state(snapshot, ["devices"])
    assert snapshot == original


@pytest.mark.parametrize("aspect,method", [
    ("devices", "delete_all_devices"), ("configurations", "delete_all_configs"), ("arm", "delete_all_certificates"),
])
def test_replace_only_deletes_selected_aspect(mocker, aspect, method):
    provider = _provider(mocker)
    operations = {name: mocker.patch.object(provider, name) for name in (
        "delete_all_devices", "delete_all_configs", "delete_all_certificates"
    )}
    provider.delete_aspects(True, [aspect])
    for name, operation in operations.items():
        assert operation.call_count == (1 if name == method else 0)


INVALID_FIELDS = [
    ("devices",), ("devices", "device"), ("devices", "device", "identity"),
    ("devices", "device", "identity", "authentication"),
    ("devices", "device", "identity", "authentication", "type"),
    ("devices", "device", "identity", "authentication", "symmetricKey"),
    ("devices", "device", "identity", "authentication", "symmetricKey", "primaryKey"),
    ("devices", "device", "identity", "authentication", "symmetricKey", "secondaryKey"),
    ("devices", "device", "identity", "capabilities"),
    ("devices", "device", "identity", "capabilities", "iotEdge"),
    ("devices", "device", "identity", "status"),
    ("devices", "device", "twin"), ("devices", "device", "twin", "properties"),
    ("devices", "device", "twin", "properties", "desired"),
    ("devices", "device", "modules", "module"),
    ("devices", "device", "modules", "module", "identity"),
    ("devices", "device", "modules", "module", "identity", "authentication"),
    ("devices", "device", "modules", "module", "twin"),
    ("devices", "device", "modules", "module", "twin", "properties", "desired"),
    ("configurations",), ("configurations", "admConfigurations"),
    ("configurations", "admConfigurations", "adm1"),
    ("configurations", "admConfigurations", "adm1", "content"),
    ("configurations", "admConfigurations", "adm1", "targetCondition"),
    ("configurations", "admConfigurations", "adm1", "priority"),
    ("configurations", "admConfigurations", "adm1", "labels"),
    ("configurations", "admConfigurations", "adm1", "metrics"),
    ("configurations", "edgeDeployments"),
    ("configurations", "edgeDeployments", "edge1", "content", "modulesContent"),
    ("configurations", "edgeDeployments", "edge1", "content", "modulesContent", "$edgeAgent"),
    ("arm",), ("arm", "resources"), ("arm", "resources", 0),
    ("arm", "resources", 0, "name"), ("arm", "resources", 0, "type"),
    ("arm", "resources", 0, "apiVersion"), ("arm", "resources", 0, "location"),
    ("arm", "resources", 0, "sku"), ("arm", "resources", 0, "properties"),
    ("arm", "resources", 0, "properties", "eventHubEndpoints"),
    ("arm", "resources", 0, "properties", "eventHubEndpoints", "events"),
    ("arm", "resources", 0, "properties", "eventHubEndpoints", "events", "partitionCount"),
    ("arm", "resources", 0, "properties", "routing"),
    ("arm", "resources", 0, "properties", "routing", "endpoints"),
]


@pytest.mark.parametrize("path,mutation", [
    (path, mutation) for path in INVALID_FIELDS for mutation in ("missing", "wrong-type")
    if mutation != "missing" or path[-1] not in ("device", "module", "adm1")
], ids=lambda value: ".".join(map(str, value)) if isinstance(value, tuple) else value)
def test_incomplete_selected_snapshot_fails_before_delete(restore, snapshot, tmp_path, path, mutation):
    container = snapshot
    for key in path[:-1]:
        container = container[key]
    if mutation == "missing":
        del container[path[-1]]
    else:
        container[path[-1]] = None
    source = tmp_path / "state.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(BadRequestError, match="Invalid Hub state"):
        restore.upload_state(str(source), replace=True)
    restore.delete_aspects.assert_not_called()
    restore.upload_hub_from_dict.assert_not_called()


@pytest.mark.parametrize("kind", ["device", "module"])
@pytest.mark.parametrize("auth_type", ["sas", "selfSigned", "certificateAuthority", "none", "unknown"])
def test_snapshot_authentication_contract(snapshot, kind, auth_type):
    identity = snapshot["devices"]["device"]["identity"]
    if kind == "module":
        identity = snapshot["devices"]["device"]["modules"]["module"]["identity"]
    identity["authentication"]["type"] = auth_type
    if auth_type == "unknown" or kind == "device" and auth_type == "none":
        with pytest.raises(BadRequestError, match="authentication.type"):
            subject._validate_hub_state(snapshot, ["devices"])
    else:
        original = deepcopy(snapshot)
        subject._validate_hub_state(snapshot, ["devices"])
        assert snapshot == original


@pytest.mark.parametrize("identity", [None, {"authentication": {"type": "sas", "symmetricKey": None}}])
def test_service_managed_edge_module_restores_desired_content_without_recreating_identity(
    snapshot, mocker, tmp_path, identity
):
    provider = _provider(mocker)
    device = snapshot["devices"]["device"]
    device["identity"]["capabilities"]["iotEdge"] = True
    module = {"twin": {"properties": {"desired": {"image": "user-image"}}}}
    if identity is not None:
        module["identity"] = identity
    device["modules"] = {"$edgeAgent": module}
    mocker.patch.object(provider, "delete_aspects")
    mocker.patch.object(provider, "upload_device_identity")
    mocker.patch.object(subject, "_iot_device_twin_update")
    upload_module = mocker.patch.object(provider, "upload_module_identity")
    edge = mocker.patch.object(subject, "_iot_edge_set_modules")
    path = tmp_path / "edge-state.json"
    path.write_text(json.dumps({"devices": snapshot["devices"]}), encoding="utf-8")
    provider.upload_state(str(path), replace=True, hub_aspects=["devices"])
    upload_module.assert_not_called()
    assert json.loads(edge.call_args.kwargs["content"]) == {
        "modulesContent": {"$edgeAgent": {"properties.desired": {"image": "user-image"}}}
    }


@pytest.mark.parametrize("field", ["primaryKey", "secondaryKey"])
def test_empty_snapshot_keys_cannot_regenerate_identity(snapshot, field):
    snapshot["devices"]["device"]["identity"]["authentication"]["symmetricKey"][field] = ""
    with pytest.raises(BadRequestError, match="key is empty"):
        subject._validate_hub_state(snapshot, ["devices"])


@pytest.mark.parametrize("field", ["primaryThumbprint", "secondaryThumbprint"])
@pytest.mark.parametrize("value", [None, "valid-thumbprint", 1, "missing"])
def test_snapshot_thumbprints_require_explicit_values(snapshot, field, value):
    auth = snapshot["devices"]["device"]["identity"]["authentication"]
    auth["type"] = "selfSigned"
    if value == "missing":
        del auth["x509Thumbprint"][field]
    else:
        auth["x509Thumbprint"][field] = value
    if value in (1, "missing"):
        with pytest.raises(BadRequestError, match="thumbprint"):
            subject._validate_hub_state(snapshot, ["devices"])
    else:
        subject._validate_hub_state(snapshot, ["devices"])


@pytest.mark.parametrize("empty", [None, ""])
def test_self_signed_snapshot_requires_authentication_material(snapshot, empty):
    auth = snapshot["devices"]["device"]["identity"]["authentication"]
    auth["type"] = "selfSigned"
    auth["x509Thumbprint"] = {"primaryThumbprint": empty, "secondaryThumbprint": empty}
    with pytest.raises(BadRequestError, match="at least one thumbprint"):
        subject._validate_hub_state(snapshot, ["devices"])


@pytest.mark.parametrize("field,value", [("parent", 1), ("modules", []), ("tags", [])])
def test_optional_snapshot_fields_are_not_silent_fallbacks(snapshot, field, value):
    device = snapshot["devices"]["device"]
    (device["twin"] if field == "tags" else device)[field] = value
    with pytest.raises(BadRequestError, match=field):
        subject._validate_hub_state(snapshot, ["devices"])


@pytest.mark.parametrize("parent", [None, "", "parent-device"])
def test_optional_parent_and_modules_preserve_values(snapshot, parent):
    device = snapshot["devices"]["device"]
    device["parent"] = parent
    del device["modules"]
    subject._validate_hub_state(snapshot, ["devices"])
    assert device["parent"] == parent and "modules" not in device


@pytest.mark.parametrize("resource_type", ["Microsoft.Devices/IotHubs", "Microsoft.Storage/storageAccounts"])
def test_arm_requires_a_hub_resource(snapshot, resource_type):
    snapshot["arm"]["resources"][0]["type"] = resource_type
    if resource_type.endswith("storageAccounts"):
        with pytest.raises(BadRequestError, match="first resource must be an IoT Hub"):
            subject._validate_hub_state(snapshot, ["arm"])
    else:
        subject._validate_hub_state(snapshot, ["arm"])


@pytest.mark.parametrize("endpoint,valid", [
    (None, False),
    ({}, False),
    ({"name": "ep"}, True),
    ({"name": "ep", "authenticationType": "keyBased"}, True),
    ({"name": "ep", "authenticationType": None}, False),
    ({"name": "ep", "authenticationType": 1}, False),
])
def test_arm_endpoint_structure(snapshot, endpoint, valid):
    snapshot["arm"]["resources"][0]["properties"]["routing"]["endpoints"]["eventHubs"] = [endpoint]
    if valid:
        subject._validate_hub_state(snapshot, ["arm"])
    else:
        with pytest.raises(BadRequestError, match="routing.endpoints"):
            subject._validate_hub_state(snapshot, ["arm"])


@pytest.mark.parametrize("name", ["oldhub/cert", "missing-child", "oldhub/"])
@pytest.mark.parametrize("dependency", [
    [], [None], ["not-an-exported-dependency"],
    ["[resourceId('Microsoft.Devices/IotHubs', 'oldhub')]"],
])
def test_certificate_fields_are_validated_before_restore(snapshot, name, dependency):
    snapshot["arm"]["resources"].append({
        "type": "Microsoft.Devices/IotHubs/certificates", "name": name, "dependsOn": dependency,
    })
    if name == "oldhub/cert" and dependency and isinstance(dependency[0], str) and dependency[0].startswith("["):
        subject._validate_hub_state(snapshot, ["arm"])
    else:
        with pytest.raises(BadRequestError, match=r"resources\[1\]"):
            subject._validate_hub_state(snapshot, ["arm"])


def test_ignored_private_endpoint_does_not_require_certificate_fields(snapshot):
    snapshot["arm"]["resources"].append({"type": "Microsoft.Devices/IotHubs/privateEndpointConnections"})
    subject._validate_hub_state(snapshot, ["arm"])


@pytest.mark.parametrize("operation", ["import", "migrate"])
def test_basic_destination_devices_fail_before_mutation(restore, snapshot, tmp_path, operation, mocker):
    restore.target["sku_tier"] = "Basic"
    capture = mocker.patch.object(restore, "process_hub_to_dict")
    path = tmp_path / "state.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(BadRequestError, match="Basic-tier.*1000"):
        if operation == "import":
            restore.upload_state(str(path), replace=True, hub_aspects=["devices"])
        else:
            restore.migrate_state(orig_hub="origin", replace=True, hub_aspects=["devices"])
    capture.assert_not_called()
    restore.delete_aspects.assert_not_called()
    restore.upload_hub_from_dict.assert_not_called()


def test_basic_arm_only_capture_remains_usable(snapshot, mocker, tmp_path):
    provider = _provider(mocker)
    provider.target["sku_tier"] = "Basic"
    provider.discovery.find_resource.return_value = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub",
    }
    mocker.patch.object(provider, "check_controlplane")
    mocker.patch.object(subject.cli, "invoke").return_value.as_json.return_value = snapshot["arm"]
    devices = mocker.patch.object(provider, "download_devices")
    path = tmp_path / "arm.json"
    provider.save_state(str(path), hub_aspects=["arm"])
    assert json.loads(path.read_text(encoding="utf-8")) == {"arm": snapshot["arm"]}
    devices.assert_not_called()


@pytest.mark.parametrize("error_type", [None, AzCLIError, RuntimeError, SystemExit])
def test_arm_staging_is_private_exclusive_quoted_and_always_removed(snapshot, mocker, monkeypatch, tmp_path, error_type):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "private staging (quoted)"
    directory.mkdir()
    monkeypatch.setattr(subject.tempfile, "tempdir", str(directory))
    provider = _provider(mocker)
    provider.rg = "group with (spaces) and 'quotes'"
    provider.discovery.find_resource.return_value = deepcopy(snapshot["arm"]["resources"][0])
    preexisting = tmp_path / "arm_deployment-hub.json"
    preexisting.write_text("preexisting user content", encoding="utf-8")
    seen = []

    def deploy(command):
        arguments = shlex.split(command)
        assert arguments[:3] == ["deployment", "group", "create"]
        assert arguments[arguments.index("-g") + 1] == provider.rg
        template = Path(arguments[arguments.index("--template-file") + 1])
        assert template.parent == directory
        assert template != preexisting
        if os.name == "posix":
            assert stat.S_IMODE(template.stat().st_mode) == 0o600
        assert json.loads(template.read_text(encoding="utf-8")) == snapshot["arm"]
        seen.append(template)
        if error_type:
            raise error_type("deployment failed")
        return mocker.Mock(success=lambda: True)

    mocker.patch.object(subject.cli, "invoke", side_effect=deploy)
    if error_type:
        with pytest.raises(error_type, match="deployment failed"):
            provider.upload_hub_from_dict(snapshot, ["arm"])
    else:
        provider.upload_hub_from_dict(snapshot, ["arm"])
    assert len(seen) == 1 and not seen[0].exists()
    assert preexisting.read_text(encoding="utf-8") == "preexisting user content"
    assert not list(directory.iterdir())


def test_arm_staging_is_removed_on_serialization_failure(snapshot, mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(subject.tempfile, "tempdir", str(tmp_path))
    provider = _provider(mocker)
    provider.discovery.find_resource.return_value = deepcopy(snapshot["arm"]["resources"][0])
    mocker.patch.object(subject.json, "dump", side_effect=ValueError("cannot serialize"))
    invoke = mocker.patch.object(subject.cli, "invoke")
    with pytest.raises(ValueError, match="cannot serialize"):
        provider.upload_hub_from_dict(snapshot, ["arm"])
    invoke.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("endpoint", [
    {"name": "legacy-key-endpoint"},
    {"name": "key-endpoint", "authenticationType": "keyBased"},
    {"name": "user-identity-endpoint", "authenticationType": "identityBased", "identity": {"userAssignedIdentity": "id"}},
])
def test_new_hub_supported_endpoints_use_owned_staging(snapshot, mocker, monkeypatch, tmp_path, endpoint):
    monkeypatch.setattr(subject.tempfile, "tempdir", str(tmp_path))
    snapshot["arm"]["resources"][0]["properties"]["routing"]["endpoints"]["eventHubs"] = [endpoint]
    subject._validate_hub_state(snapshot, ["arm"])
    provider = _provider(mocker, target=None)
    result = mocker.Mock()
    result.success.return_value = True
    result.as_json.return_value = {"resourceGroup": "rg"}
    mocker.patch.object(subject.cli, "invoke", return_value=result)
    provider.upload_hub_from_dict(snapshot, ["arm"])
    provider.discovery.get_target.assert_called_once_with("hub", resource_group_name="rg", auth_type=None)
    assert not list(tmp_path.iterdir())


def test_group_export_quotes_resource_group_and_resource_id(snapshot, mocker):
    provider = _provider(mocker)
    provider.rg = "resource group (staging) with 'quotes'"
    resource_id = f"/subscriptions/sub/resourceGroups/{provider.rg}/providers/Microsoft.Devices/IotHubs/hub"
    provider.discovery.find_resource.return_value = {"id": resource_id}
    invoke = mocker.patch.object(subject.cli, "invoke")
    invoke.return_value.as_json.return_value = deepcopy(snapshot["arm"])
    mocker.patch.object(provider, "check_controlplane")
    provider.process_hub_to_dict(provider.target, ["arm"])
    arguments = shlex.split(invoke.call_args.args[0])
    assert arguments == ["group", "export", "-n", provider.rg, "--resource-ids", resource_id, "--skip-all-params"]
    assert invoke.call_args.kwargs == {"capture_stderr": True}


@pytest.mark.parametrize("operation", ["export", "migrate"])
@pytest.mark.parametrize("boundary", ["configurations", "arm-resource", "arm-export"])
@pytest.mark.parametrize("status", [403, 500])
def test_controlplane_and_configuration_read_errors_leave_state_unchanged(
    mocker, tmp_path, operation, boundary, status
):
    provider = _provider(mocker)
    provider.discovery.get_target.return_value = provider.target
    provider.discovery.find_resource.return_value = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub",
    }
    original = AzCLIError(f"authoritative {boundary} read failed: HTTP {status}")
    if boundary == "configurations":
        mocker.patch.object(subject, "_iot_hub_configuration_list", side_effect=original)
        aspects = ["configurations"]
    else:
        aspects = ["arm"]
        if boundary == "arm-resource":
            provider.discovery.find_resource.side_effect = original
        else:
            mocker.patch.object(subject.cli, "invoke", side_effect=original)
    delete = mocker.patch.object(provider, "delete_aspects")
    upload = mocker.patch.object(provider, "upload_hub_from_dict")
    path = tmp_path / "existing.json"
    path.write_text("existing snapshot", encoding="utf-8")
    with pytest.raises(AzCLIError) as raised:
        if operation == "export":
            provider.save_state(str(path), replace=True, hub_aspects=aspects)
        else:
            provider.migrate_state(orig_hub="origin", replace=True, hub_aspects=aspects)
    assert raised.value is original
    assert path.read_text(encoding="utf-8") == "existing snapshot"
    delete.assert_not_called()
    upload.assert_not_called()
