# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import Mock

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
from azext_iot.tests.adr.test_adr_validation_scenarios_unit import offline_cli  # noqa: F401


KINDS = [
    ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
    ("dps", "provisioning", DPS_ENDPOINT_TYPE),
    ("su", "updating", SU_ENDPOINT_TYPE),
]
URL = "https://management.azure.com/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
UAMI = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi"
TARGET_RG = "/subscriptions/target-sub/resourceGroups/target-rg"


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
    client.namespaces.get.return_value = source
    initial = {"properties": {"provisioningState": "Accepted"}}
    client.namespaces.begin_create_or_replace.return_value.result.return_value = initial
    provider = LinkProvider(fixture_cmd, client=client)
    for name in ("_get_target", "_preflight_link", "_wait", "_await_terminal"):
        mocker.patch.object(provider, name, side_effect=AssertionError(f"Unexpected {name}"))
    unlink_rbac.ensure_unlink_reader.side_effect = lambda *_: client.namespaces.begin_create_or_replace.assert_not_called()

    assert getattr(provider, kind + "_delete")("primary", "ns", "rg") is initial
    unlink_rbac.ensure_unlink_reader.assert_called_once_with("ns-system" if identity == "system" else "ns-user", TARGET_RG)

    client.namespaces.get.assert_called_once_with(resource_group_name="rg", namespace_name="ns", retry_total=0)
    arguments = client.namespaces.begin_create_or_replace.call_args.kwargs
    assert set(arguments) == {"resource_group_name", "namespace_name", "resource", "polling", "retry_total"}
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
    client.namespaces.get.return_value = source
    with pytest.raises(ResourceNotFoundError, match="primary"):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_delete")("primary", "ns", "rg")
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
    client.namespaces.get.return_value = source
    original = deepcopy(source)
    with pytest.raises(error_type):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_delete")("primary", "ns", "rg")
    assert source == original
    client.namespaces.begin_create_or_replace.assert_not_called()
    if defect != "rbac":
        unlink_rbac.ensure_unlink_reader.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["get", "put"])
@pytest.mark.parametrize("error_type", [HttpResponseError, ServiceRequestError])
def test_delete_does_not_translate_or_swallow_backend_errors(fixture_cmd, kind, section, _endpoint_type, stage, error_type):
    client = Mock()
    client.namespaces.get.return_value = namespace()
    error = error_type("original backend error")
    operation = client.namespaces.get if stage == "get" else client.namespaces.begin_create_or_replace
    operation.side_effect = error
    with pytest.raises(error_type) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_delete")("primary", "ns", "rg")
    assert raised.value is error
    if stage == "get":
        client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_command_handler_forwards_only_endpoint_selectors(mocker, kind, section, _endpoint_type):
    provider_type = mocker.patch.object(commands_link, "LinkProvider")
    handler = getattr(commands_link, f"adr_link_{kind}_delete")
    cmd, client = Mock(), Mock()
    assert handler(cmd, client, "primary", "ns", "rg") is getattr(provider_type.return_value, kind + "_delete").return_value
    provider_type.assert_called_once_with(cmd, client=client)
    getattr(provider_type.return_value, kind + "_delete").assert_called_once_with(
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
        network.get(URL, json=namespace())
        network.put(URL, json=initial, status=status, headers={
            "Azure-AsyncOperation": URL + "/must-not-poll", "Location": URL + "/must-not-follow", "Retry-After": "60",
        })
        result = getattr(LinkProvider(fixture_cmd, client=client), kind + "_delete")("primary", "ns", "rg")
        assert result == initial
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert all(call.request.url == URL + "?api-version=2026-11-02-preview" for call in network.calls)
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
            network.get(URL, json=namespace())
        network.add("GET" if stage == "get" else "PUT", URL, json=failure, status=status)
        with pytest.raises(HttpResponseError, match="Original backend deletion detail") as raised:
            LinkProvider(fixture_cmd, client=client).hub_delete("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert len(network.calls) == (1 if stage == "get" else 2)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_initial_response(offline_cli, mocker, kind, section, _endpoint_type):  # noqa: F811
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=namespace())
    initial = {"properties": {"provisioningState": "Accepted"}}
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       return_value=SimpleNamespace(result=lambda: initial))
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "delete", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 0
    assert json.loads(output.getvalue()) == initial
    assert get.call_count == put.call_count == 1
    assert put.call_args.kwargs["polling"] is False


@pytest.mark.parametrize("option", ["--no-wait", "--timeout", "--interval", "--delete-linked-resource", "--system-assigned-mi"])
@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_delete_rejects_composite_and_wait_options(offline_cli, kind, option):  # noqa: F811
    with pytest.raises(SystemExit) as raised:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "delete", "-n", "primary", "--ns", "ns",
                            "-g", "rg", "--yes", option, *(["10"] if option in ("--timeout", "--interval") else [])])
    assert raised.value.code == 2
