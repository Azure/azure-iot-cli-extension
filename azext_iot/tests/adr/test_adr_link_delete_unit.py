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
from azure.core.polling import LROPoller

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
STATUS_URL = (
    "https://management.azure.com/subscriptions/sub/providers/"
    "Microsoft.DeviceRegistry/locations/westus/asyncOperationStatuses/unlink"
)
UAMI = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi"
TARGET_RG = "/subscriptions/target-sub/resourceGroups/target-rg"


@pytest.fixture(autouse=True)
def unlink_rbac(mocker):
    return mocker.patch.object(LinkProvider, "_rbac_manager").return_value


@pytest.fixture
def unlink_client():
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    with DeviceRegistryMgmtClient(credential, "sub", polling_interval=0, retry_total=0) as client:
        yield client


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
def test_delete_preserves_namespace_and_waits_without_target_reads(
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
    completed = {"properties": {"provisioningState": "Succeeded"}}
    client.namespaces.begin_create_or_replace.return_value.result.return_value = completed
    provider = LinkProvider(fixture_cmd, client=client)
    for name in ("_get_target", "_preflight_link"):
        mocker.patch.object(provider, name, side_effect=AssertionError(f"Unexpected {name}"))
    wait = mocker.spy(provider, "_wait")
    unlink_rbac.ensure_unlink_reader.side_effect = lambda *_: client.namespaces.begin_create_or_replace.assert_not_called()

    assert getattr(provider, kind + "_remove")("primary", "ns", "rg") is completed
    assert wait.call_args.kwargs == {"no_wait": False, "failure_target": (section, "primary")}
    unlink_rbac.ensure_unlink_reader.assert_called_once_with("ns-system" if identity == "system" else "ns-user", TARGET_RG)

    client.namespaces.get.assert_called_once_with(resource_group_name="rg", namespace_name="ns", retry_total=0)
    arguments = client.namespaces.begin_create_or_replace.call_args.kwargs
    assert set(arguments) == {"resource_group_name", "namespace_name", "resource", "retry_total"}
    assert arguments["namespace_name"] == "ns" and arguments["resource_group_name"] == "rg"
    assert arguments["retry_total"] == 0
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
    client.namespaces.get.return_value = source
    original = deepcopy(source)
    with pytest.raises(error_type):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert source == original
    client.namespaces.begin_create_or_replace.assert_not_called()
    if defect != "rbac":
        unlink_rbac.ensure_unlink_reader.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["get", "put", "result"])
@pytest.mark.parametrize("error_type", [HttpResponseError, ServiceRequestError])
def test_delete_does_not_translate_or_swallow_backend_errors(fixture_cmd, kind, section, _endpoint_type, stage, error_type):
    client = Mock()
    client.namespaces.get.return_value = namespace()
    error = error_type("original backend error")
    operation = {
        "get": client.namespaces.get,
        "put": client.namespaces.begin_create_or_replace,
        "result": client.namespaces.begin_create_or_replace.return_value.result,
    }[stage]
    operation.side_effect = error
    with pytest.raises(error_type) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is error
    if stage == "get":
        client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("no_wait", [False, True])
def test_delete_command_handler_forwards_selectors_and_no_wait(mocker, kind, section, _endpoint_type, no_wait):
    provider_type = mocker.patch.object(commands_link, "LinkProvider")
    handler = getattr(commands_link, f"adr_link_{kind}_remove")
    cmd, client = Mock(), Mock()
    assert handler(cmd, client, "primary", "ns", "rg", no_wait=no_wait) is getattr(
        provider_type.return_value, kind + "_remove",
    ).return_value
    provider_type.assert_called_once_with(cmd, client=client)
    getattr(provider_type.return_value, kind + "_remove").assert_called_once_with(
        endpoint_name="primary", namespace_name="ns", resource_group_name="rg",
        no_wait=no_wait,
    )


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("status", [200, 201])
def test_delete_real_sdk_polls_async_status_and_returns_completed_namespace(
    fixture_cmd, unlink_rbac, unlink_client, kind, section, _endpoint_type, status,
):
    initial = {"location": "centraluseuap", "properties": {"provisioningState": "Accepted"}}
    completed = deepcopy(initial)
    completed["properties"] = {"provisioningState": "Succeeded", section: {"endpoints": {}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace())
        network.put(URL, json=initial, status=status, headers={
            "Azure-AsyncOperation": STATUS_URL, "Location": URL + "/must-not-follow", "Retry-After": "0",
        })
        network.get(STATUS_URL, json={"status": "Running"})
        network.get(STATUS_URL, json={"status": "Succeeded"})
        network.get(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET", "GET", "GET"]
        assert [call.request.url for call in network.calls[2:4]] == [STATUS_URL, STATUS_URL]
        body = json.loads(network.calls[1].request.body)
        assert "primary" not in body["properties"][section]["endpoints"]
        assert body["identity"] == {"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {UAMI: {}}}
        unlink_rbac.ensure_unlink_reader.assert_called_once_with("ns-user", TARGET_RG)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_delete_real_sdk_raises_async_service_failure(fixture_cmd, unlink_client, kind, section, _endpoint_type, state):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace())
        network.put(URL, json={"properties": {"provisioningState": "Accepted"}}, status=201,
                    headers={"Azure-AsyncOperation": STATUS_URL})
        network.get(STATUS_URL, json={
            "status": state, "error": {"code": "BackendUnlinkRejected", "message": "Original backend unlink detail."},
        })
        with pytest.raises(HttpResponseError, match="Original backend unlink detail") as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET"]
        assert network.calls[-1].request.url == STATUS_URL


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("status", [403, 500])
def test_delete_real_sdk_preserves_async_status_http_error(fixture_cmd, unlink_client, kind, section, _endpoint_type, status):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace())
        network.put(URL, json={"properties": {"provisioningState": "Accepted"}}, status=201,
                    headers={"Azure-AsyncOperation": STATUS_URL})
        network.get(STATUS_URL, status=status, json={
            "error": {"code": "StatusReadDenied", "message": "Original operation-status error."},
        })
        with pytest.raises(HttpResponseError, match="Original operation-status error") as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "StatusReadDenied"
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET"]


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_delete_rejects_inline_terminal_failure(fixture_cmd, unlink_client, kind, section, _endpoint_type, state):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace())
        network.put(URL, json={
            "properties": {"provisioningState": state},
            "error": {"code": "BackendUnlinkRejected", "message": "Original inline unlink detail."},
        })
        with pytest.raises(AzureResponseError, match="BackendUnlinkRejected: Original inline unlink detail"):
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_no_wait_returns_poller_without_waiting(mocker, fixture_cmd, kind, section, _endpoint_type):
    client = Mock()
    client.namespaces.get.return_value = namespace()
    provider = LinkProvider(fixture_cmd, client=client)
    wait = mocker.patch.object(provider, "_await_terminal", side_effect=AssertionError("Unexpected wait"))
    assert getattr(provider, kind + "_remove")("primary", "ns", "rg", no_wait=True) is (
        client.namespaces.begin_create_or_replace.return_value
    )
    wait.assert_not_called()
    client.namespaces.begin_create_or_replace.return_value.result.assert_not_called()


@pytest.mark.parametrize("stage", ["get", "put"])
@pytest.mark.parametrize("status", [400, 403, 404, 409, 412, 429, 500])
def test_delete_real_sdk_preserves_backend_error_without_retries(fixture_cmd, unlink_client, stage, status):
    failure = {"error": {"code": "BackendUnlinkRejected", "message": "Original backend deletion detail."}}
    with responses.RequestsMock() as network:
        if stage == "put":
            network.get(URL, json=namespace())
        network.add("GET" if stage == "get" else "PUT", URL, json=failure, status=status)
        with pytest.raises(HttpResponseError, match="Original backend deletion detail") as raised:
            LinkProvider(fixture_cmd, client=unlink_client).hub_remove("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert len(network.calls) == (1 if stage == "get" else 2)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_completed_response(offline_cli, mocker, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=namespace())
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       return_value=SimpleNamespace(result=lambda: completed))
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 0
    assert json.loads(output.getvalue()) == completed
    assert get.call_count == put.call_count == 1
    assert "polling" not in put.call_args.kwargs


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_nonzero_for_operation_failure(offline_cli, mocker, kind, section, _endpoint_type):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=namespace())
    error = HttpResponseError("(BackendUnlinkRejected) Original asynchronous unlink error.")
    put = mocker.patch(
        "azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
        return_value=SimpleNamespace(result=Mock(side_effect=error)),
    )
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) != 0
    assert not output.getvalue().strip()
    assert "Original asynchronous unlink error" in str(offline_cli.result.error)
    put.assert_called_once()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_accepts_no_wait(offline_cli, mocker, kind, section, _endpoint_type):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=namespace())
    poller = Mock(spec=LROPoller)
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace", return_value=poller)
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "--no-wait", "-o", "json"], out_file=output) == 0
    poller.result.assert_not_called()
    assert not output.getvalue().strip()


@pytest.mark.parametrize("option", ["--timeout", "--interval", "--delete-linked-resource", "--system-assigned-mi"])
@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_delete_rejects_composite_and_wait_options(offline_cli, kind, option):
    with pytest.raises(SystemExit) as raised:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                            "-g", "rg", "--yes", option, *(["10"] if option in ("--timeout", "--interval") else [])])
    assert raised.value.code == 2
