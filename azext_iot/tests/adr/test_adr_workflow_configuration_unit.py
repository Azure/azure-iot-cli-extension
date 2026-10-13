# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import copy
import json

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.workflows.configuration import load_config, request_config, validate_identity
from azext_iot.adr.workflows.input import (
    _config_pairs, _required_config_pairs, build_setup_request, parse_endpoint,
)
from azext_iot.adr.workflows.models import CmsSpec, EndpointSpec


SUB = "00000000-0000-0000-0000-000000000000"
OTHER_SUB = "11111111-1111-1111-1111-111111111111"
PREFIX = f"/subscriptions/{SUB}/resourceGroups/rg/providers/"
UAMI = PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
DPS = PREFIX + "Microsoft.Devices/provisioningServices/my-dps"
HUB = PREFIX + "Microsoft.Devices/IotHubs/my-hub"
SU = PREFIX + "Microsoft.DeviceUpdate/updateInstances/my-su"


def config():
    return {
        "schemaVersion": 1, "subscriptionId": SUB,
        "namespace": {"name": "ns", "resourceGroup": "rg", "location": "eastus",
                      "outboundIdentity": {"type": "SystemAssigned"}, "tags": {"owner": "team"}},
        "links": {
            "dps": {"resourceName": "my-dps", "identity": "system-assigned", "createIfMissing": True, "sku": "S1", "unit": 1},
            "hubs": [{"resourceId": HUB, "identity": {"type": "UserAssigned", "userAssignedResourceId": UAMI},
                      "endpointName": "hub", "availability": "Available", "allocationWeight": 100}],
            "softwareUpdates": {"resourceId": SU, "identity": {"type": "SystemAssigned"}, "createIfMissing": True},
        },
        "cms": {"enabled": True}, "checkStatus": True,
    }


def test_full_configuration_roundtrip_and_detached_copy(tmp_path):
    source = config()
    loaded = load_config(source)
    assert loaded["cms"] == {
        "enabled": True, "rootName": "root", "intermediateName": "intermediate",
        "policyName": "default", "validityDays": 30,
    }
    loaded["namespace"]["tags"]["owner"] = "changed"
    assert source["namespace"]["tags"] == {"owner": "team"}
    text = json.dumps(source)
    assert load_config(text) == load_config(source)
    path = tmp_path / "setup.json"
    path.write_text(text, encoding="utf-8")
    assert load_config(str(path)) == load_config("@" + str(path))
    assert load_config(path) == load_config(source)
    yaml_path = tmp_path / "setup.yaml"
    yaml_path.write_text("namespace: {name: ns, resourceGroup: rg}\ncms: false\n", encoding="utf-8")
    assert load_config(str(yaml_path)) == {
        "schemaVersion": 1, "namespace": {"name": "ns", "resourceGroup": "rg"}, "cms": {"enabled": False},
    }
    request = build_setup_request(None, None, SUB, config=source)
    assert request.cms == CmsSpec()
    assert request.check_status
    assert request.dps.create_if_missing and request.dps.sku == "S1" and request.dps.unit == 1
    assert request.software_updates.create_if_missing and request.create_update_instance
    assert request.hubs[0].user_assigned_identity == UAMI
    assert request.tags == {"owner": "team"}


def test_namespace_only_and_missing_scope():
    request = build_setup_request(None, None, SUB, config={"namespace": {"name": "ns", "resourceGroup": "rg"}})
    assert not request.requests_links
    assert request.outbound_identity_type is None and request.cms is None
    assert load_config({}) == {"schemaVersion": 1}
    with pytest.raises(ArgumentUsageError, match="resource-group"):
        build_setup_request(None, None, SUB, config={})
    with pytest.raises(ArgumentUsageError, match="--name"):
        build_setup_request(None, "rg", SUB, config={})
    request = build_setup_request("ns", "rg", SUB, config={"cms": False})
    assert request.cms is None


@pytest.mark.parametrize("value,path", [
    ([], r"\$"), (None, r"\$"), (True, r"\$"), ("", r"\$"), ("null", r"\$"), ("[]", r"\$"),
    ({"unknown": True}, "unknown"), ({"assignRoles": False}, "assignRoles"),
    ({"schemaVersion": True}, "schemaVersion"), ({"schemaVersion": 2}, "schemaVersion"),
    ({"subscriptionId": "other"}, "subscriptionId"), ({"subscriptionId": 42}, "subscriptionId"),
    ({"namespace": None}, "namespace"), ({"namespace": {"name": ""}}, "namespace.name"),
    ({"namespace": {"name": " ns "}}, "namespace.name"), ({"namespace": {"name": 3}}, "namespace.name"),
    ({"namespace": {"name": "/bad"}}, "namespace.name"),
    ({"namespace": {"tags": []}}, "namespace.tags"),
    ({"namespace": {"tags": {"a": 5}}}, "namespace.tags.a"),
    ({"namespace": {"tags": {1: "a"}}}, "namespace.tags"),
    ({"namespace": {"outboundIdentity": "user-assigned"}}, "namespace.outboundIdentity"),
    ({"namespace": {"outboundIdentity": {"type": "SystemAssigned", "userAssignedResourceId": UAMI}}},
     "namespace.outboundIdentity"),
    ({"namespace": {"outboundIdentity": {"type": "UserAssigned"}}}, "namespace.outboundIdentity"),
    ({"namespace": {"outboundIdentity": {"type": "bad", "userAssignedResourceId": UAMI}}}, "namespace.outboundIdentity"),
    ({"namespace": {"outboundIdentity": {"userAssignedResourceId": "/bad"}}}, "userAssignedResourceId"),
    ({"namespace": {"outboundIdentity": {"type": "SystemAssigned", "extra": True}}}, "extra"),
    ({"links": []}, "links"), ({"links": {"hubs": {}}}, "links.hubs"), ({"links": {"dps": {}}}, "links.dps"),
    ({"checkStatus": "false"}, "checkStatus"), ({"cms": True}, "cms"), ({"cms": {}}, "cms.enabled"),
    ({"cms": {"enabled": False, "rootName": "root"}}, "cms"),
    ({"cms": {"enabled": False, "validityDays": 30}}, "cms"),
    ({"cms": {"enabled": True, "issuerType": "External"}}, "cms.issuerType"),
    ({"cms": {"enabled": True, "validityDays": 0}}, "cms.validityDays"),
    ({"cms": {"enabled": True, "validityDays": 91}}, "cms.validityDays"),
    ({"cms": {"enabled": True, "validityDays": True}}, "cms.validityDays"),
    ({"cms": {"enabled": True, "validityDays": "30"}}, "cms.validityDays"),
    ({"cms": {"enabled": True, "intermediateName": "ROOT"}}, "cms.intermediateName"),
    ({"cms": {"enabled": True, "rootName": "/bad"}}, "cms.rootName"),
    ({"cms": {"enabled": True, "policyName": []}}, "cms.policyName"),
])
def test_invalid_top_level_and_namespace(value, path):
    with pytest.raises(InvalidArgumentValueError, match=path):
        load_config(value)


@pytest.mark.parametrize("kind,patch,path", [
    ("dps", {"resourceId": DPS}, "links.dps"),
    ("dps", {"resourceName": None}, "resourceName"),
    ("dps", {"resourceName": "bad/name"}, "resourceName"),
    ("dps", {"subscription": "bad"}, "subscription"),
    ("dps", {"availability": "Available"}, "availability"),
    ("dps", {"allocationWeight": 1}, "allocationWeight"),
    ("dps", {"identity": "/bad"}, "identity"),
    ("dps", {"identity": {"type": "External"}}, "identity"),
    ("dps", {"identity": False}, "identity"),
    ("dps", {"identity": []}, "identity"),
    ("dps", {"sku": "S2", "createIfMissing": True}, "sku"),
    ("dps", {"sku": "S1"}, "sku/unit"),
    ("dps", {"createIfMissing": "false"}, "createIfMissing"),
    ("dps", {"unit": 0}, "unit"),
    ("hub", {"availability": "bad"}, "availability"),
    ("hub", {"allocationWeight": 0}, "allocationWeight"),
    ("hub", {"allocationWeight": 1001}, "allocationWeight"),
    ("hub", {"unit": True}, "unit"),
    ("hub", {"sku": "F1", "createIfMissing": True}, "sku"),
    ("softwareUpdates", {"sku": "S1"}, "sku"),
    ("softwareUpdates", {"unit": 1}, "unit"),
    ("softwareUpdates", {"assignRoles": False}, "assignRoles"),
])
def test_invalid_endpoints(kind, patch, path):
    endpoint = {"resourceName": "target", "identity": "system-assigned", **patch}
    links = {"hubs": [endpoint]} if kind == "hub" else {kind: endpoint}
    with pytest.raises(InvalidArgumentValueError, match=path):
        load_config({"links": links})


@pytest.mark.parametrize("endpoint,path", [
    ({"identity": "system-assigned"}, "exactly one"),
    ({"resourceId": HUB, "identity": "system-assigned"}, "resourceId"),
    ({"resourceId": DPS, "resourceGroup": "rg", "identity": "system-assigned"}, "resourceId"),
    ({"resourceId": DPS + "/child/name", "identity": "system-assigned"}, "resourceId"),
    ({"resourceId": DPS.replace(SUB, "sub"), "identity": "system-assigned"}, "resourceId"),
])
def test_resource_id_validation(endpoint, path):
    with pytest.raises(InvalidArgumentValueError, match=path):
        load_config({"links": {"dps": endpoint}})


@pytest.mark.parametrize("text,path", [
    ('{"namespace":{"name":"ns","name":"other"}}', "namespace.name"),
    ('{"links":{"hubs":[{"resourceName":"a","resourceName":"b"}]}}', r"links.hubs\[0\].resourceName"),
    ('{"namespace":\n}', "line 2 column 1"),
])
def test_json_syntax_and_duplicate_paths(text, path):
    with pytest.raises(InvalidArgumentValueError, match=path):
        load_config(text)


@pytest.mark.parametrize("text,path", [
    ("namespace:\n  name: ns\n  name: other", "namespace.name"),
    ("1: value", "keys must be strings"), ("namespace: [", "not valid"),
])
def test_yaml_errors(tmp_path, text, path):
    file = tmp_path / "config.yaml"
    file.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidArgumentValueError, match=path):
        load_config(str(file))


def test_missing_path_and_non_utf8(tmp_path):
    with pytest.raises(InvalidArgumentValueError, match="Unable to read"):
        load_config("@" + str(tmp_path / "absent"))
    file = tmp_path / "binary.json"
    file.write_bytes(b"\xff\xff")
    with pytest.raises(InvalidArgumentValueError, match="Unable to read"):
        load_config(str(file))


@pytest.mark.parametrize("field,cli", [
    ("name", {"namespace_name": "other"}), ("resourceGroup", {"resource_group_name": "other"}),
    ("location", {"location": "westus"}), ("tags", {"tags": {"owner": "other"}}),
])
def test_cli_config_conflicts(field, cli):
    kwargs = {"namespace_name": None, "resource_group_name": None, **cli}
    with pytest.raises(InvalidArgumentValueError, match=f"namespace.{field} conflicts"):
        build_setup_request(**kwargs, subscription_id=SUB, config=config())


def test_subscription_conflicts_and_identity_forms():
    source = config()
    source["subscriptionId"] = OTHER_SUB
    with pytest.raises(InvalidArgumentValueError, match="--subscription"):
        build_setup_request(None, None, SUB, config=source)
    for identity in (UAMI, {"userAssignedResourceId": UAMI}, {"type": "UserAssigned", "userAssignedResourceId": UAMI}):
        assert validate_identity(identity, "identity") == UAMI
    assert validate_identity("SystemAssigned", "identity") == "system-assigned"
    for validity in (1, 90):
        source = {"cms": {"enabled": True, "validityDays": validity},
                  "namespace": {"outboundIdentity": UAMI}}
        request = build_setup_request("ns", "rg", SUB, config=source)
        assert request.cms.validity_days == validity and request.outbound_user_assigned_identity == UAMI


@pytest.mark.parametrize("option,match", [
    ("create-if-missing=maybe", "create-if-missing"),
    ("unit=abc", "unit"), ("name=second", "more than once"),
    ("sku=F1", "sku"),
])
def test_strict_legacy_flags(option, match):
    with pytest.raises(InvalidArgumentValueError, match=match):
        parse_endpoint(["endpoint=hub", "resource-name=hub", "identity=system-assigned", option], "hub", "rg", SUB)


def test_endpoint_creation_roundtrip_and_input_callbacks(mocker):
    endpoint = EndpointSpec("hub", "hub", HUB, "system-assigned", create_if_missing=True, sku="S2", unit=2)
    exported = {"endpointName": "hub", "resourceId": HUB, "identity": {"type": "SystemAssigned"},
                "createIfMissing": True, "sku": "S2", "unit": 2}
    assert parse_endpoint(_config_pairs(exported), "hub", "rg", SUB) == endpoint
    source = config()
    source["links"]["hubs"][0].update(createIfMissing=True, sku="S1", unit=1)
    validate = mocker.Mock()
    build_setup_request(None, None, SUB, config=source, validate_endpoint_resource=validate)
    assert all(call.args[1] for call in validate.call_args_list)
    with pytest.raises(InvalidArgumentValueError, match="non-empty object"):
        _required_config_pairs([], "links.dps")
    assert load_config(copy.deepcopy(source))["links"]["dps"]["resourceName"] == "my-dps"


def test_numeric_relative_config_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "2026.json"
    path.write_text('{"namespace": {}}', encoding="utf-8")
    assert load_config("2026.json") == {"schemaVersion": 1, "namespace": {}}


def test_request_config_export_is_valid_detached_and_deterministic():
    request = build_setup_request(None, None, SUB, config=config())
    exported = request_config(request)
    assert exported == request_config(request)
    rebuilt = build_setup_request(None, None, SUB, config=exported)
    assert rebuilt == request
    exported["namespace"]["tags"]["owner"] = "changed"
    assert request.tags["owner"] == "team"
    basic = build_setup_request("ns", "rg", SUB, config={})
    assert "cms" not in request_config(basic)
    source = {"namespace": {"outboundIdentity": {"type": "UserAssigned", "userAssignedResourceId": UAMI}}}
    request = build_setup_request("ns", "rg", SUB, config=source)
    assert request_config(request)["namespace"]["outboundIdentity"] == source["namespace"]["outboundIdentity"]


@pytest.mark.parametrize("kind,create,error,allowed", [
    ("dps", True, ResourceNotFoundError("missing"), True),
    ("hub", True, ResourceNotFoundError("missing"), True),
    ("dps", False, ResourceNotFoundError("missing"), False),
    ("hub", True, HttpResponseError("forbidden"), False),
])
def test_read_callback_accepts_missing_hub_dps_only_when_requested(mocker, kind, create, error, allowed):
    callback_name = "validate_endpoint_resource"
    source = {"links": {}}
    endpoint = {"resourceName": "target", "identity": "system-assigned", "createIfMissing": create}
    source["links"].update({"hubs": [endpoint]} if kind == "hub" else {"dps": endpoint})
    callback = mocker.Mock(side_effect=error)
    if allowed:
        request = build_setup_request("ns", "rg", SUB, config=source, **{callback_name: callback})
        assert (request.dps or request.hubs[0]).create_if_missing
    else:
        with pytest.raises(type(error)):
            build_setup_request("ns", "rg", SUB, config=source, **{callback_name: callback})
