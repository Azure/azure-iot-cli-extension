# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import ANY, Mock

import pytest
import responses
from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ServiceRequestError

from azext_iot.adr import commands_link
from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE, SU_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.topology import writable_namespace_properties
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient


KINDS = [
    ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
    ("dps", "provisioning", DPS_ENDPOINT_TYPE),
    ("su", "updating", SU_ENDPOINT_TYPE),
]
URL = "https://management.azure.com/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
UAMI = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi"
TARGET_RG = "/subscriptions/target-sub/resourceGroups/target-rg"
ETAG = '"namespace-version-1"'


@pytest.fixture(autouse=True)
def unlink_rbac(mocker):
    return mocker.patch.object(LinkProvider, "_rbac_manager").return_value


def namespace():
    return {
        "id": "/namespace", "name": "ns", "type": "Microsoft.DeviceRegistry/namespaces",
        "location": "centraluseuap", "tags": {"preserve": "value"},
        "systemData": {"createdBy": "read-only"},
        "identity": {
            "type": "SystemAssigned, UserAssigned", "principalId": "ns-system", "tenantId": "read-only",
            "userAssignedIdentities": {UAMI: {"principalId": "ns-user", "clientId": "read-only"}},
        },
        "properties": {
            "uuid": "read-only", "provisioningState": "Failed",
            "outboundIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI},
            "observability": {
                "enabled": True, "endpoints": {
                    "logs": {"endpointType": "Microsoft.OperationalInsights", "address": "keep-address"},
                },
            },
            **{
                section: {"endpoints": {
                    name: {
                        "endpointType": endpoint_type, "resourceId": f"{TARGET_RG}/providers/{endpoint_type}/{name}",
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                        "provisioning": {"availability": "Available", "allocationWeight": 3},
                        "linkingState": "Succeeded", "linkingError": {"code": "read-only"},
                        "address": "read-only", "serviceAddress": "read-only", "deviceAddress": "read-only",
                    }
                    for name in (("primary", "secondary") if kind == "hub" else ("primary",))
                }}
                for kind, section, endpoint_type in KINDS
            },
        },
    }


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("identity", ["mixed", "system", "user"])
def test_delete_preserves_namespace_without_target_reads_or_waits(
    mocker, fixture_cmd, unlink_rbac, kind, section, _endpoint_type, identity,
):
    source = namespace()
    if identity == "system":
        source["identity"] = {"type": "SystemAssigned", "principalId": "ns-system"}
        source["properties"].pop("outboundIdentity")
        source.pop("tags")
    elif identity == "user":
        source["identity"].pop("principalId")
        source["identity"]["type"] = "UserAssigned"
    original = deepcopy(source)
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    initial = {"properties": {"provisioningState": "Accepted"}}
    client.namespaces.begin_create_or_replace.return_value.result.return_value = initial
    provider = LinkProvider(fixture_cmd, client=client)
    for name in ("_get_target", "_preflight_link", "_wait", "_await_terminal"):
        mocker.patch.object(provider, name, side_effect=AssertionError(f"Unexpected {name}"))
    unlink_rbac.ensure_unlink_reader.side_effect = lambda *_: client.namespaces.begin_create_or_replace.assert_not_called()

    assert getattr(provider, kind + "_remove")("primary", "ns", "rg") is initial
    unlink_rbac.ensure_unlink_reader.assert_called_once_with("ns-system" if identity == "system" else "ns-user", TARGET_RG)

    client.namespaces.get.assert_called_once_with(resource_group_name="rg", namespace_name="ns", retry_total=0, cls=ANY)
    arguments = client.namespaces.begin_create_or_replace.call_args.kwargs
    assert set(arguments) == {"resource_group_name", "namespace_name", "resource", "headers", "polling", "retry_total"}
    assert arguments["headers"] == {"If-Match": ETAG}
    assert arguments["namespace_name"] == "ns" and arguments["resource_group_name"] == "rg"
    assert arguments["polling"] is False and arguments["retry_total"] == 0
    body = arguments["resource"]
    expected = writable_namespace_properties(original["properties"])
    del expected[section]["endpoints"]["primary"]
    assert body["properties"] == expected
    assert body["location"] == original["location"]
    if identity == "system":
        assert set(body) == {"location", "properties", "identity"}
    else:
        assert body["tags"] == original["tags"]
    assert body["identity"] == {
        "type": original["identity"]["type"],
        **({"userAssignedIdentities": {UAMI: {}}} if identity in ("mixed", "user") else {}),
    }
    assert source == original
    assert [call[0] for call in client.mock_calls] == [
        "namespaces.get", "namespaces.begin_create_or_replace", "namespaces.begin_create_or_replace().result",
    ]


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("defect", ["missing", "null", "wrong-type", "missing-section"])
def test_delete_requires_the_named_endpoint_of_the_correct_kind(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, defect):
    source = namespace()
    if defect == "missing-section":
        source["properties"].pop(section)
    elif defect == "missing":
        source["properties"][section]["endpoints"].pop("primary")
    elif defect == "null":
        source["properties"][section]["endpoints"]["primary"] = None
    else:
        source["properties"][section]["endpoints"]["primary"]["endpointType"] = "Other.Type"
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    with pytest.raises(ResourceNotFoundError, match="primary"):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    client.namespaces.begin_create_or_replace.assert_not_called()
    unlink_rbac.ensure_unlink_reader.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("defect", ["missing-id", "invalid-id", "wrong-target-type", "identity", "principal", "rbac"])
def test_delete_preflight_failure_prevents_put(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, defect):
    source = namespace()
    endpoint = source["properties"][section]["endpoints"]["primary"]
    error_type = InvalidArgumentValueError
    if defect == "missing-id":
        endpoint.pop("resourceId")
    elif defect == "invalid-id":
        endpoint["resourceId"] = "/invalid"
    elif defect == "wrong-target-type":
        endpoint["resourceId"] = TARGET_RG + "/providers/Microsoft.Storage/storageAccounts/storage"
    elif defect == "identity":
        source.pop("identity")
    elif defect == "principal":
        source["identity"]["userAssignedIdentities"][UAMI].pop("principalId")
        error_type = AzureResponseError
    else:
        unlink_rbac.ensure_unlink_reader.side_effect = AzureResponseError("Reader grant denied")
        error_type = AzureResponseError
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    original = deepcopy(source)
    with pytest.raises(error_type):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert source == original
    client.namespaces.begin_create_or_replace.assert_not_called()
    if defect != "rbac":
        unlink_rbac.ensure_unlink_reader.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["get", "put"])
@pytest.mark.parametrize("error_type", [HttpResponseError, ServiceRequestError])
def test_delete_does_not_translate_or_swallow_backend_errors(fixture_cmd, kind, section, _endpoint_type, stage, error_type):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = error_type("original backend error")
    operation = client.namespaces.get if stage == "get" else client.namespaces.begin_create_or_replace
    operation.side_effect = error
    with pytest.raises(error_type) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is error
    if stage == "get":
        client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_command_handler_forwards_only_endpoint_selectors(mocker, kind, section, _endpoint_type):
    provider_type = mocker.patch.object(commands_link, "LinkProvider")
    handler = getattr(commands_link, f"adr_link_{kind}_remove")
    cmd, client = Mock(), Mock()
    assert handler(cmd, client, "primary", "ns", "rg") is getattr(provider_type.return_value, kind + "_remove").return_value
    provider_type.assert_called_once_with(cmd, client=client)
    getattr(provider_type.return_value, kind + "_remove").assert_called_once_with(
        endpoint_name="primary", namespace_name="ns", resource_group_name="rg",
    )


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("status", [200, 201])
@pytest.mark.parametrize("state", ["Accepted", "Failed"])
def test_delete_real_sdk_sends_only_get_and_put_after_rbac(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type, status, state,
):
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    initial = {"location": "centraluseuap", "properties": {"provisioningState": state}}
    with responses.RequestsMock() as network, DeviceRegistryMgmtClient(credential, "sub") as client:
        network.get(URL, json=namespace(), headers={"eTag": ETAG})
        network.put(URL, json=initial, status=status, headers={
            "Azure-AsyncOperation": URL + "/must-not-poll", "Location": URL + "/must-not-follow", "Retry-After": "60",
        })
        result = getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
        assert result == initial
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert all(call.request.url == URL + "?api-version=2026-11-02-preview" for call in network.calls)
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert "primary" not in body["properties"][section]["endpoints"]
        assert body["identity"] == {"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {UAMI: {}}}
        unlink_rbac.ensure_unlink_reader.assert_called_once_with("ns-user", TARGET_RG)


@pytest.mark.parametrize("stage", ["get", "put"])
@pytest.mark.parametrize("status", [400, 403, 404, 409, 412, 429, 500])
def test_delete_real_sdk_preserves_backend_error_without_retries(fixture_cmd, stage, status):
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    failure = {"error": {"code": "BackendUnlinkRejected", "message": "Original backend deletion detail."}}
    with responses.RequestsMock() as network, DeviceRegistryMgmtClient(credential, "sub") as client:
        if stage == "put":
            network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.add("GET" if stage == "get" else "PUT", URL, json=failure, status=status)
        with pytest.raises(HttpResponseError, match="Original backend deletion detail") as raised:
            LinkProvider(fixture_cmd, client=client).hub_remove("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert len(network.calls) == (1 if stage == "get" else 2)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_initial_response(offline_cli, mocker, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
                       return_value=(namespace(), ETAG))
    initial = {"properties": {"provisioningState": "Accepted"}}
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       return_value=SimpleNamespace(result=lambda: initial))
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 0
    assert json.loads(output.getvalue()) == initial
    assert get.call_count == put.call_count == 1
    assert put.call_args.kwargs["polling"] is False
    assert put.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("etag", [None, "", " ", "*", 7])
def test_delete_missing_etag_stops_before_rbac_and_put(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, etag):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), etag)
    with pytest.raises(AzureResponseError, match="usable ETag header"):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    unlink_rbac.ensure_unlink_reader.assert_not_called()
    client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_sdk_requires_header_even_when_body_has_etag(fixture_cmd, unlink_rbac, kind, section, _endpoint_type):
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    source = namespace()
    source["etag"] = ETAG
    with responses.RequestsMock() as network, DeviceRegistryMgmtClient(credential, "sub") as client:
        network.get(URL, json=source)
        with pytest.raises(AzureResponseError, match="usable ETag header"):
            getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET"]
        unlink_rbac.ensure_unlink_reader.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_sdk_preserves_concurrent_changes_and_can_be_rerun(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type,
):
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    stored = namespace()
    current_etag = ETAG
    concurrent = None

    def read(_request):
        return 200, {"ETag": current_etag}, json.dumps(stored)

    def concurrent_write(*_args):
        nonlocal current_etag, concurrent
        stored["tags"]["concurrent"] = "keep"
        stored["identity"]["userAssignedIdentities"][UAMI + "-concurrent"] = {}
        endpoints = stored["properties"][section]["endpoints"]
        endpoints["concurrent"] = deepcopy(endpoints["primary"])
        endpoints["concurrent"]["resourceId"] += "-concurrent"
        current_etag = '"namespace-version-2"'
        concurrent = deepcopy(stored)

    def replace(request):
        nonlocal stored, current_etag
        if request.headers.get("If-Match") != current_etag:
            return 412, {}, json.dumps({"error": {"code": "PreconditionFailed", "message": "Namespace changed."}})
        stored = json.loads(request.body)
        current_etag = '"namespace-version-3"'
        return 200, {"ETag": current_etag}, json.dumps(stored)

    unlink_rbac.ensure_unlink_reader.side_effect = concurrent_write
    with responses.RequestsMock() as network, DeviceRegistryMgmtClient(credential, "sub") as client:
        network.add_callback("GET", URL, callback=read, content_type="application/json")
        network.add_callback("PUT", URL, callback=replace, content_type="application/json")
        provider = LinkProvider(fixture_cmd, client=client)
        with pytest.raises(HttpResponseError) as raised:
            getattr(provider, kind + "_remove")("primary", "ns", "rg")
        assert raised.value.status_code == 412
        assert stored == concurrent
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG

        unlink_rbac.ensure_unlink_reader.side_effect = None
        result = getattr(provider, kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET", "PUT"]
        assert network.calls[3].request.headers["If-Match"] == '"namespace-version-2"'
        assert result == stored
        assert stored["tags"]["concurrent"] == "keep"
        assert UAMI + "-concurrent" in stored["identity"]["userAssignedIdentities"]
        assert "concurrent" in stored["properties"][section]["endpoints"]
        assert "primary" not in stored["properties"][section]["endpoints"]
        assert unlink_rbac.ensure_unlink_reader.call_count == 2


@pytest.mark.parametrize("option", ["--no-wait", "--timeout", "--interval", "--delete-linked-resource", "--system-assigned-mi"])
@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_delete_rejects_composite_and_wait_options(offline_cli, kind, option):
    with pytest.raises(SystemExit) as raised:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                            "-g", "rg", "--yes", option, *(["10"] if option in ("--timeout", "--interval") else [])])
    assert raised.value.code == 2
