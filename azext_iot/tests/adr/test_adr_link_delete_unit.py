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
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import DeserializationError, HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.core.polling import LROPoller
from azure.mgmt.core.polling.arm_polling import ARMPolling

from azext_iot.adr import commands_link
from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE, SU_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.rbac import LinkRbacManager
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
ETAG = '"namespace-version-1"'
# RFC 9110 etagc: printable boundaries, literal backslash and obs-text boundaries.
BOUNDARY_ETAG = '"!#~\\\x80\xff"'


@pytest.fixture(autouse=True)
def unlink_rbac(mocker):
    return mocker.patch.object(LinkProvider, "_rbac_manager").return_value


@pytest.fixture
def unlink_client():
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    with DeviceRegistryMgmtClient(credential, "sub", polling_interval=0, retry_backoff_factor=0) as client:
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
    client = Mock(_config=SimpleNamespace(
        polling_interval=7, base_url="https://centraluseuap.management.azure.com",
    ))
    client.namespaces.get.return_value = (source, ETAG)
    completed = {"properties": {"provisioningState": "Succeeded"}}
    client.namespaces.begin_create_or_replace.return_value.result.return_value = completed
    provider = LinkProvider(fixture_cmd, client=client)
    for name in ("_get_target", "_preflight_link"):
        mocker.patch.object(provider, name, side_effect=AssertionError(f"Unexpected {name}"))
    wait = mocker.spy(provider, "_wait")
    unlink_rbac.check_unlink_read_access.side_effect = lambda *_: client.namespaces.begin_create_or_replace.assert_not_called()

    assert getattr(provider, kind + "_remove")("primary", "ns", "rg") is completed
    assert wait.call_args.kwargs == {"no_wait": False, "failure_target": (section, "primary")}
    unlink_rbac.check_unlink_read_access.assert_called_once_with("ns-system" if identity == "system" else "ns-user", TARGET_RG)

    client.namespaces.get.assert_called_once_with(resource_group_name="rg", namespace_name="ns", retry_total=0, cls=ANY)
    arguments = client.namespaces.begin_create_or_replace.call_args.kwargs
    assert set(arguments) == {"resource_group_name", "namespace_name", "resource", "headers", "retry_total", "polling"}
    assert arguments["headers"] == {"If-Match": ETAG}
    assert arguments["namespace_name"] == "ns" and arguments["resource_group_name"] == "rg"
    assert arguments["retry_total"] == 0
    polling = arguments["polling"]
    assert isinstance(polling, ARMPolling)
    assert polling._timeout == 7
    assert polling._path_format_arguments == {"endpoint": client._config.base_url}
    assert polling._operation_config == {}
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
    unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("defect", ["missing-id", "invalid-id", "wrong-target-type", "identity", "principal", "rbac"])
def test_delete_preflight_failure_warns_and_continues(fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, defect):
    source = namespace()
    endpoint = source["properties"][section]["endpoints"]["primary"]
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
    else:
        unlink_rbac.check_unlink_read_access.side_effect = AzureResponseError("Role lookup denied")
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    original = deepcopy(source)
    getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert source == original
    client.namespaces.begin_create_or_replace.assert_called_once()
    assert "Could not verify" in caplog.text
    assert "Continuing without changing role assignments; ADR may reject removal." in caplog.text
    if defect == "identity":
        assert "identity" not in client.namespaces.begin_create_or_replace.call_args.kwargs["resource"]
    if defect != "rbac":
        unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("resource_id", [
    pytest.param(123, id="integer"),
    pytest.param(["invalid"], id="list"),
    pytest.param({"id": "invalid"}, id="object"),
    pytest.param(True, id="boolean"),
])
@pytest.mark.parametrize("skip", [False, True])
def test_delete_real_sdk_non_string_resource_id_does_not_block_unlink(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, resource_id, skip,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["resourceId"] = resource_id
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.put(URL, json=completed)

        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", skip_rbac_check=skip,
        )

        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        assert "primary" not in json.loads(network.calls[1].request.body)["properties"][section]["endpoints"]
        assert ("did not include a string resourceId" in caplog.text) is (not skip)
        assert ("Continuing without changing role assignments" in caplog.text) is (not skip)
        unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("prefix", ["", "/subscriptions/sub", "/resourceGroups/rg"])
@pytest.mark.parametrize("skip", [False, True])
def test_delete_real_sdk_unscoped_resource_id_is_advisory(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, prefix, skip,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["resourceId"] = f"{prefix}/providers/{_endpoint_type}/primary"
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.put(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", skip_rbac_check=skip,
        )
        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert "primary" not in body["properties"][section]["endpoints"]
        assert body["identity"]["userAssignedIdentities"] == {UAMI: {}}
    assert ("resource-group-scoped ARM resource ID" in caplog.text) is (not skip)
    assert ("Continuing without changing role assignments" in caplog.text) is (not skip)
    unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("field", ["identity", "userAssignedIdentities"])
@pytest.mark.parametrize("value", [
    pytest.param(123, id="integer"),
    pytest.param(0, id="zero"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param(UAMI, id="string"),
    pytest.param("", id="empty-string"),
    pytest.param([UAMI], id="list"),
    pytest.param([], id="empty-list"),
    pytest.param([{"id": UAMI}], id="list-of-objects"),
])
@pytest.mark.parametrize("outbound_type,state,skip", [
    pytest.param("UserAssigned", "Succeeded", False, id="user-advisory"),
    pytest.param("UserAssigned", "Succeeded", True, id="user-skip"),
    pytest.param("SystemAssigned", "Succeeded", False, id="system-advisory"),
    pytest.param("SystemAssigned", "Succeeded", True, id="system-skip"),
    pytest.param("UserAssigned", "Failed", False, id="failed-link"),
    pytest.param("SystemAssigned", "LinkedResourceDeleted", False, id="deleted-resource"),
])
def test_delete_real_sdk_rejects_malformed_identity_containers_before_preflight(
    fixture_cmd, unlink_client, unlink_rbac, mocker, caplog,
    kind, section, _endpoint_type, field, value, outbound_type, state, skip,
):
    source = namespace()
    source["properties"]["outboundIdentity"]["type"] = outbound_type
    source["properties"][section]["endpoints"]["primary"]["linkingState"] = state
    if field == "identity":
        source["identity"] = value
    else:
        source["identity"]["userAssignedIdentities"] = value
    original = deepcopy(source)
    provider = LinkProvider(fixture_cmd, client=unlink_client)
    preflight = mocker.patch.object(provider, "_check_unlink_permissions")
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        with pytest.raises(AzureResponseError, match="attached identities cannot be safely preserved") as error:
            getattr(provider, kind + "_remove")("primary", "ns", "rg", skip_rbac_check=skip)
        assert field in str(error.value)
        assert [call.request.method for call in network.calls] == ["GET"]
    assert source == original
    preflight.assert_not_called()
    unlink_rbac.check_unlink_read_access.assert_not_called()
    assert "Continuing" not in caplog.text


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("skip", [False, True])
def test_delete_rejects_non_string_attached_identity_keys(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, skip):
    source = namespace()
    source["identity"]["userAssignedIdentities"] = {123: {}}
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    with pytest.raises(AzureResponseError, match="identity.userAssignedIdentities"):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg", skip_rbac_check=skip)
    client.namespaces.begin_create_or_replace.assert_not_called()
    unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("identity,expected", [
    pytest.param(None, None, id="null"),
    pytest.param({}, {}, id="empty-object"),
    pytest.param({"type": "None"}, {"type": "None"}, id="no-identity"),
    pytest.param(
        {"type": "SystemAssigned", "principalId": "ns-system", "userAssignedIdentities": None},
        {"type": "SystemAssigned"}, id="null-attachments",
    ),
    pytest.param(
        {"type": "SystemAssigned", "principalId": "ns-system", "userAssignedIdentities": {}},
        {"type": "SystemAssigned"}, id="empty-attachments",
    ),
    pytest.param(
        {"type": "SystemAssigned, UserAssigned", "principalId": "ns-system", "userAssignedIdentities": {
            UAMI: {"principalId": "ns-user"}, UAMI + "-other": None,
        }},
        {"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {UAMI: {}, UAMI + "-other": {}}},
        id="multiple-attachments",
    ),
])
@pytest.mark.parametrize("skip", [False, True])
def test_delete_real_sdk_preserves_supported_identity_shapes(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, identity, expected, skip,
):
    source = namespace()
    source["identity"] = identity
    source["properties"]["outboundIdentity"] = {"type": "SystemAssigned"}
    original = deepcopy(source)
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.put(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", skip_rbac_check=skip,
        )
        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert body["identity"] == expected
        assert "primary" not in body["properties"][section]["endpoints"]
    assert source == original


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("field,value", [
    pytest.param("outbound-id", ["bad-id"], id="uami-id-list"),
    pytest.param("outbound-id", {"id": UAMI}, id="uami-id-object"),
    pytest.param("outbound-id", 123, id="uami-id-integer"),
    pytest.param("attached-details", ["bad-projection"], id="attached-details-list"),
    pytest.param("attached-details", 123, id="attached-details-integer"),
    pytest.param("attached-details", True, id="attached-details-boolean"),
    pytest.param("outbound", ["bad-outbound"], id="outbound-identity-list"),
])
@pytest.mark.parametrize("state,skip", [
    pytest.param("Succeeded", False, id="advisory"),
    pytest.param("Succeeded", True, id="explicit-skip"),
    pytest.param("Failed", False, id="failed-link"),
    pytest.param("LinkedResourceDeleted", False, id="deleted-resource"),
])
def test_delete_real_sdk_malformed_identity_is_advisory(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, field, value, state, skip,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["linkingState"] = state
    if field == "outbound-id":
        source["properties"]["outboundIdentity"]["userAssignedIdentity"] = value
    elif field == "attached-details":
        source["identity"]["userAssignedIdentities"][UAMI] = value
    else:
        source["properties"]["outboundIdentity"] = value
    original = deepcopy(source)
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.put(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", skip_rbac_check=skip,
        )
        assert result == completed
        assert source == original
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert "primary" not in body["properties"][section]["endpoints"]
        assert body["properties"]["outboundIdentity"] == source["properties"]["outboundIdentity"]
        assert body["identity"] == {"type": source["identity"]["type"], "userAssignedIdentities": {UAMI: {}}}
        assert ("Could not verify" in caplog.text) is (state == "Succeeded" and not skip)
        assert ("Continuing without changing role assignments" in caplog.text) is (state == "Succeeded" and not skip)
        unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_sdk_group_deserialization_failure_is_advisory(
    fixture_cmd, mocker, unlink_client, caplog, kind, section, _endpoint_type,
):
    from azure.mgmt.resource import ResourceManagementClient

    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", 9999999999)
    manager = LinkRbacManager(fixture_cmd.cli_ctx, cli=Mock())
    check = mocker.spy(manager, "check_unlink_read_access")
    mocker.patch.object(LinkProvider, "_rbac_manager", return_value=manager)
    mocker.patch("azext_iot._factory._get_canary_credential_scopes", return_value=["https://management.azure.com/.default"])
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    group_url = "https://management.azure.com/subscriptions/target-sub/resourcegroups/target-rg"
    with ResourceManagementClient(credential, "target-sub") as resources, responses.RequestsMock() as network:
        mocker.patch("azure.cli.core.commands.client_factory.get_mgmt_service_client", return_value=resources)
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.get(group_url, json=["malformed-group"])
        network.put(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")

        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "GET", "PUT"]
        assert network.calls[1].request.url.split("?")[0] == group_url
        assert network.calls[2].request.headers["If-Match"] == ETAG
        assert isinstance(check.spy_exception, DeserializationError)
        assert "Could not verify" in caplog.text
        assert "Continuing without changing role assignments" in caplog.text
        manager.cli.invoke.assert_not_called()
        assert not manager.created


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [AttributeError, TypeError, ValueError])
def test_delete_does_not_swallow_unexpected_advisory_errors(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type, error_type,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = error_type("unexpected implementation failure")
    unlink_rbac.check_unlink_read_access.side_effect = error
    with pytest.raises(error_type) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is error
    client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["get", "put", "result"])
@pytest.mark.parametrize("error_type", [HttpResponseError, ServiceRequestError, DeserializationError])
def test_delete_does_not_translate_or_swallow_backend_errors(fixture_cmd, kind, section, _endpoint_type, stage, error_type):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
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
@pytest.mark.parametrize("stage", ["put", "result"])
def test_delete_conflict_warns_and_preserves_original_exception(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, stage,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = HttpResponseError("original conflict detail")
    error.status_code = 412
    operation = client.namespaces.begin_create_or_replace
    if stage == "result":
        operation = operation.return_value.result
    operation.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")

    assert raised.value is error
    assert str(raised.value) == "original conflict detail"
    assert raised.value.status_code == 412
    assert "Namespace 'ns' changed before endpoint removal (HTTP 412)." in caplog.text
    assert "Inspect the namespace with 'az iot adr ns show' and rerun the remove command." in caplog.text
    assert client.namespaces.get.call_count == client.namespaces.begin_create_or_replace.call_count == 1
    unlink_rbac.check_unlink_read_access.assert_called_once_with("ns-user", TARGET_RG)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("skip", [False, True])
def test_delete_command_handler_forwards_selectors_and_flags(mocker, kind, section, _endpoint_type, no_wait, skip):
    provider_type = mocker.patch.object(commands_link, "LinkProvider")
    handler = getattr(commands_link, f"adr_link_{kind}_remove")
    cmd, client = Mock(), Mock()
    assert handler(cmd, client, "primary", "ns", "rg", no_wait=no_wait, skip_rbac_check=skip) is getattr(
        provider_type.return_value, kind + "_remove",
    ).return_value
    provider_type.assert_called_once_with(cmd, client=client)
    getattr(provider_type.return_value, kind + "_remove").assert_called_once_with(
        endpoint_name="primary", namespace_name="ns", resource_group_name="rg",
        no_wait=no_wait, skip_rbac_check=skip,
    )


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("status", [200, 201])
@pytest.mark.parametrize("etag,expected_etag", [
    pytest.param(ETAG, ETAG, id="strong-etag"),
    pytest.param(f" \t{ETAG}\t ", ETAG, id="trim-http-ows"),
    pytest.param('""', '""', id="empty-opaque-tag"),
    pytest.param(BOUNDARY_ETAG, BOUNDARY_ETAG, id="allowed-character-boundaries"),
])
def test_delete_real_sdk_polls_async_status_and_returns_completed_namespace(
    fixture_cmd, unlink_rbac, unlink_client, kind, section, _endpoint_type, status, etag, expected_etag,
):
    initial = {"location": "centraluseuap", "properties": {"provisioningState": "Accepted"}}
    completed = deepcopy(initial)
    completed["properties"] = {"provisioningState": "Succeeded", section: {"endpoints": {}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"eTag": etag})
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
        assert network.calls[1].request.headers["If-Match"] == expected_etag
        body = json.loads(network.calls[1].request.body)
        assert "primary" not in body["properties"][section]["endpoints"]
        assert body["identity"] == {"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {UAMI: {}}}
        unlink_rbac.check_unlink_read_access.assert_called_once_with("ns-user", TARGET_RG)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_delete_real_sdk_raises_async_service_failure(fixture_cmd, unlink_client, kind, section, _endpoint_type, state):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
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
@pytest.mark.parametrize("stage", ["async-status", "final-resource"])
@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_delete_real_sdk_preserves_polling_http_error_after_retries(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, stage, status,
):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.put(URL, json={"properties": {"provisioningState": "Accepted"}}, status=201,
                    headers={"Azure-AsyncOperation": STATUS_URL})
        if stage == "final-resource":
            network.get(STATUS_URL, json={"status": "Succeeded"})
        failure_url = STATUS_URL if stage == "async-status" else URL
        network.get(failure_url, status=status, json={
            "error": {"code": "StatusReadDenied", "message": "Original operation-status error."},
        })
        with pytest.raises(HttpResponseError, match="Original operation-status error") as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "StatusReadDenied"
        policy = unlink_client._config.retry_policy
        attempts = 1 if status == 403 else 1 + min(policy.total_retries, policy.status_retries)
        assert [call.request.method for call in network.calls] == (
            ["GET", "PUT"] + (["GET"] if stage == "final-resource" else []) + ["GET"] * attempts
        )
        expected_url = STATUS_URL if stage == "async-status" else network.calls[0].request.url
        assert all(call.request.url == expected_url for call in network.calls[-attempts:])


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["async-status", "final-resource"])
@pytest.mark.parametrize("failure", [
    pytest.param(429, id="throttled"),
    pytest.param(500, id="server-error"),
    pytest.param(503, id="unavailable"),
    pytest.param(ServiceRequestError, id="connection-error"),
    pytest.param(ServiceResponseError, id="read-error"),
])
def test_delete_real_sdk_recovers_from_transient_polling_error(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, stage, failure,
):
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.put(URL, json={"properties": {"provisioningState": "Accepted"}}, status=201,
                    headers={"Azure-AsyncOperation": STATUS_URL})
        if stage == "final-resource":
            network.get(STATUS_URL, json={"status": "Succeeded"})
        failure_url = STATUS_URL if stage == "async-status" else URL
        if isinstance(failure, int):
            network.get(failure_url, status=failure, json={"error": {"code": "Transient", "message": "Try again."}})
        else:
            network.get(failure_url, body=failure("Transient transport error."))
        network.get(failure_url, json={"status": "Succeeded"} if stage == "async-status" else completed)
        if stage == "async-status":
            network.get(URL, json=completed)

        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")

        assert result == completed
        assert network.calls[1].request.headers["If-Match"] == ETAG
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET", "GET", "GET"]
        resource_url = network.calls[0].request.url
        assert [call.request.url for call in network.calls] == (
            [resource_url, resource_url, STATUS_URL, STATUS_URL, resource_url] if stage == "async-status"
            else [resource_url, resource_url, STATUS_URL, resource_url, resource_url]
        )


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_delete_rejects_inline_terminal_failure(fixture_cmd, unlink_client, kind, section, _endpoint_type, state):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
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
    client.namespaces.get.return_value = (namespace(), ETAG)
    provider = LinkProvider(fixture_cmd, client=client)
    wait = mocker.patch.object(provider, "_await_terminal", side_effect=AssertionError("Unexpected wait"))
    assert getattr(provider, kind + "_remove")("primary", "ns", "rg", no_wait=True) is (
        client.namespaces.begin_create_or_replace.return_value
    )
    wait.assert_not_called()
    client.namespaces.begin_create_or_replace.return_value.result.assert_not_called()


@pytest.mark.parametrize("stage", ["get", "put"])
@pytest.mark.parametrize("status", [400, 403, 404, 409, 412, 429, 500, 503])
def test_delete_real_sdk_preserves_backend_error_without_retries(fixture_cmd, unlink_client, caplog, stage, status):
    failure = {"error": {"code": "BackendUnlinkRejected", "message": "Original backend deletion detail."}}
    with responses.RequestsMock() as network:
        if stage == "put":
            network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.add("GET" if stage == "get" else "PUT", URL, json=failure, status=status)
        with pytest.raises(HttpResponseError, match="Original backend deletion detail") as raised:
            LinkProvider(fixture_cmd, client=unlink_client).hub_remove("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert len(network.calls) == (1 if stage == "get" else 2)
        assert ("rerun the remove command" in caplog.text) is (stage == "put" and status == 412)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [ServiceRequestError, ServiceResponseError])
def test_delete_real_sdk_does_not_retry_put_transport_error(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, error_type,
):
    error = error_type("Original PUT transport error.")
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.put(URL, body=error)
        with pytest.raises(error_type) as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value is error
        assert [call.request.method for call in network.calls] == ["GET", "PUT"]
        assert network.calls[1].request.headers["If-Match"] == ETAG


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_completed_response(offline_cli, mocker, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
                       return_value=(namespace(), ETAG))
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       return_value=SimpleNamespace(result=lambda: completed))
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 0
    assert json.loads(output.getvalue()) == completed
    assert get.call_count == put.call_count == 1
    assert isinstance(put.call_args.kwargs["polling"], ARMPolling)
    assert put.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_reports_conflict(offline_cli, mocker, caplog, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
                       return_value=(namespace(), ETAG))
    error = HttpResponseError("Original backend conflict detail.")
    error.status_code = 412
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       side_effect=error)
    output = StringIO()

    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 1

    assert output.getvalue() == ""
    assert "Original backend conflict detail." in caplog.text
    assert "Inspect the namespace with 'az iot adr ns show' and rerun the remove command." in caplog.text
    assert get.call_count == put.call_count == 1
    assert put.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("etag", [
    pytest.param(None, id="missing-header"),
    pytest.param("", id="empty-header"),
    pytest.param(" ", id="space-only-header"),
    pytest.param("\t", id="tab-only-header"),
    pytest.param("*", id="wildcard"),
    pytest.param(" \t*\t ", id="wildcard-with-http-ows"),
    pytest.param(7, id="integer-header"),
    pytest.param(b'"v1"', id="bytes-header"),
    pytest.param('W/"v1"', id="weak-etag"),
    pytest.param(' \tW/"v1"\t ', id="weak-etag-with-http-ows"),
    pytest.param('w/"v1"', id="lowercase-weak-prefix"),
    pytest.param("v1", id="unquoted-tag"),
    pytest.param('"v1', id="missing-closing-quote"),
    pytest.param('v1"', id="missing-opening-quote"),
    pytest.param('"v"1"', id="embedded-quote"),
    pytest.param('"v1", "v2"', id="multiple-tags"),
    pytest.param('"with space"', id="embedded-space"),
    pytest.param('"with\ttab"', id="embedded-tab"),
    pytest.param('"\x00"', id="nul-control-character"),
    pytest.param('"\x1f"', id="c0-control-upper-boundary"),
    pytest.param('"\x7f"', id="del-control-character"),
    pytest.param('"\u0100"', id="outside-latin1-range"),
    pytest.param('\n"v1"', id="leading-line-feed"),
    pytest.param('"v1"\r', id="trailing-carriage-return"),
    pytest.param('"v1"\r\n', id="trailing-crlf"),
])
def test_delete_unusable_etag_stops_before_rbac_and_put(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, etag):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), etag)
    with pytest.raises(AzureResponseError, match="usable ETag header"):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    unlink_rbac.check_unlink_read_access.assert_not_called()
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
        unlink_rbac.check_unlink_read_access.assert_not_called()


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

    unlink_rbac.check_unlink_read_access.side_effect = concurrent_write
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

        unlink_rbac.check_unlink_read_access.side_effect = None
        result = getattr(provider, kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET", "PUT", "GET", "PUT"]
        assert network.calls[3].request.headers["If-Match"] == '"namespace-version-2"'
        assert result == stored
        assert stored["tags"]["concurrent"] == "keep"
        assert UAMI + "-concurrent" in stored["identity"]["userAssignedIdentities"]
        assert "concurrent" in stored["properties"][section]["endpoints"]
        assert "primary" not in stored["properties"][section]["endpoints"]
        assert unlink_rbac.check_unlink_read_access.call_count == 2


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_nonzero_for_operation_failure(offline_cli, mocker, kind, section, _endpoint_type):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=(namespace(), ETAG))
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
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=(namespace(), ETAG))
    poller = Mock(spec=LROPoller)
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace", return_value=poller)
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "--no-wait", "-o", "json"], out_file=output) == 0
    poller.result.assert_not_called()
    assert not output.getvalue().strip()


@pytest.mark.parametrize("option", [
    "--timeout", "--interval", "--delete-linked-resource", "--system-assigned-mi", "--skip-permission-check",
])
@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_delete_rejects_composite_and_wait_options(offline_cli, kind, option):
    with pytest.raises(SystemExit) as raised:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                            "-g", "rg", "--yes", option, *(["10"] if option in ("--timeout", "--interval") else [])])
    assert raised.value.code == 2


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["LinkedResourceDeleted", "Failed", "InProgress", "Canceled", "", None, "Unexpected"])
def test_delete_state_gate_skips_identity_target_and_permission_work(
    fixture_cmd, mocker, unlink_rbac, caplog, kind, section, _endpoint_type, state,
):
    source = namespace()
    source.pop("identity")
    endpoint = source["properties"][section]["endpoints"]["primary"]
    endpoint.pop("resourceId")
    if state is None:
        endpoint.pop("linkingState")
    else:
        endpoint["linkingState"] = state
    resolver = mocker.patch("azext_iot.adr.providers.link.resolve_namespace_outbound_principal",
                            side_effect=AssertionError("Unexpected identity lookup"))
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    resolver.assert_not_called()
    unlink_rbac.check_unlink_read_access.assert_not_called()
    client.namespaces.begin_create_or_replace.assert_called_once()
    assert ("permission preflight is unavailable" in caplog.text) is (state not in ("LinkedResourceDeleted", "Failed"))


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [
    AzureResponseError, HttpResponseError, ServiceRequestError, ServiceResponseError, DeserializationError,
])
@pytest.mark.parametrize("stage", ["put", "result"])
def test_delete_permission_errors_warn_but_do_not_swallow_backend_rejection(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, error_type, stage,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    unlink_rbac.check_unlink_read_access.side_effect = error_type("permission lookup unavailable")
    rejection = HttpResponseError("ADR unlink rejected")
    operation = client.namespaces.begin_create_or_replace
    if stage == "result":
        operation = operation.return_value.result
    operation.side_effect = rejection
    with pytest.raises(HttpResponseError) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is rejection
    assert "permission lookup unavailable" in caplog.text
    assert "ADR may reject removal" in caplog.text


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("skip", [False, True])
def test_delete_real_cli_rbac_skip_is_independent_of_yes_and_no_wait(
    offline_cli, mocker, unlink_rbac, kind, section, _endpoint_type, no_wait, skip,
):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=(namespace(), ETAG))
    poller = Mock(spec=LROPoller)
    poller.result.return_value = {"properties": {"provisioningState": "Succeeded"}}
    put = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_create_or_replace",
                       return_value=poller)
    output = StringIO()
    args = ["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns", "-g", "rg", "--yes"]
    if skip:
        args.append("--skip-rbac-check")
    if no_wait:
        args.append("--no-wait")
    assert offline_cli.invoke(args, out_file=output) == 0
    assert unlink_rbac.check_unlink_read_access.call_count == (0 if skip else 1)
    assert poller.result.call_count == (0 if no_wait else 1)
    assert put.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_skip_rbac_check_does_not_bypass_etag_or_endpoint_validation(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), None)
    provider = LinkProvider(fixture_cmd, client=client)
    with pytest.raises(AzureResponseError, match="usable ETag"):
        getattr(provider, kind + "_remove")("primary", "ns", "rg", skip_rbac_check=True)
    client.namespaces.get.return_value = (namespace(), ETAG)
    with pytest.raises(ResourceNotFoundError):
        getattr(provider, kind + "_remove")("missing", "ns", "rg", skip_rbac_check=True)
    unlink_rbac.check_unlink_read_access.assert_not_called()
    client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_delete_skip_rbac_check_does_not_bypass_confirmation(offline_cli, mocker, kind):
    confirm = mocker.patch("azure.cli.core.commands.AzCliCommand._user_confirmed", return_value=False)
    provider = mocker.patch.object(commands_link, "LinkProvider")
    assert offline_cli.invoke(
        ["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns", "-g", "rg",
         "--skip-rbac-check"],
    ) != 0
    confirm.assert_called_once()
    assert "no role assignments are changed" in confirm.call_args.args[0]
    provider.assert_not_called()
