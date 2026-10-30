# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

import pytest
import responses
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import DeserializationError, HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.core.polling import LROPoller
from azure.mgmt.core.polling.arm_polling import ARMPolling

from azext_iot.adr import commands_link
from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.rbac import LinkRbacManager
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient


KINDS = [
    ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
    ("dps", "provisioning", DPS_ENDPOINT_TYPE),
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


@pytest.mark.parametrize("grant_reader", [False, True])
@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_live_unlink_scenarios_preserve_the_native_reader(mocker, grant_reader, kind, section, _endpoint_type):
    import logging
    from azext_iot.adr.providers.base import ADRResourceStateError
    from azext_iot.tests.adr import test_adr_link_delete_int as scenarios

    scenario = scenarios.TestADRLinkDelete("test_adr_link_hub_dps_delete")
    before = namespace()
    reader = mocker.patch.object(scenario, "_reader_assignments", return_value=[{"id": "native-reader"}])
    cleanup = mocker.patch.object(scenario, "addCleanup")
    mocker.patch.object(scenarios, "sleep")

    def command(text):
        if " remove " in text:
            logging.getLogger("cli.azext_iot.adr").info("Observed a read-capable role assignment")
            raise ADRResourceStateError("Live target cannot be removed", before)
        assert text.startswith("iot adr ns show ")
        return Mock(get_output_in_json=lambda: deepcopy(before))

    scenario.cmd = Mock(side_effect=command)
    if grant_reader:
        scenario._assert_requested_reader_retained("ns", kind, section, "primary")
    else:
        scenario._assert_live_target_removal_rejected("ns", kind, section, "primary")
    assert reader.call_count == (3 if grant_reader else 2)
    cleanup.assert_not_called()
    assert not any("role assignment create" in item.args[0] for item in scenario.cmd.call_args_list)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("identity", ["mixed", "system", "user"])
@pytest.mark.parametrize("grant_reader", [False, True])
def test_delete_preserves_namespace_and_waits_without_target_reads(
    mocker, fixture_cmd, unlink_rbac, kind, section, _endpoint_type, identity, grant_reader,
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
    client.namespaces.begin_update.return_value.result.return_value = completed
    provider = LinkProvider(fixture_cmd, client=client)
    for name in ("_get_target", "_preflight_link"):
        mocker.patch.object(provider, name, side_effect=AssertionError(f"Unexpected {name}"))
    wait = mocker.spy(provider, "_wait")
    unlink_rbac.check_unlink_read_access.side_effect = (
        lambda *_, **__: client.namespaces.begin_update.assert_not_called()
    )

    assert getattr(provider, kind + "_remove")("primary", "ns", "rg", grant_reader=grant_reader) is completed
    assert wait.call_args.kwargs == {"no_wait": False, "failure_target": (section, "primary")}
    unlink_rbac.check_unlink_read_access.assert_called_once_with(
        "ns-system" if identity == "system" else "ns-user", TARGET_RG, grant_reader=grant_reader,
    )

    client.namespaces.get.assert_called_once_with(resource_group_name="rg", namespace_name="ns", retry_total=0, cls=ANY)
    arguments = client.namespaces.begin_update.call_args.kwargs
    assert set(arguments) == {"resource_group_name", "namespace_name", "properties", "headers", "retry_total", "polling"}
    assert arguments["headers"] == {"If-Match": ETAG}
    assert arguments["namespace_name"] == "ns" and arguments["resource_group_name"] == "rg"
    assert arguments["retry_total"] == 0
    polling = arguments["polling"]
    assert isinstance(polling, ARMPolling)
    assert polling._timeout == 7
    assert polling._path_format_arguments == {"endpoint": client._config.base_url}
    assert polling._operation_config == {}
    assert arguments["properties"] == {"properties": {section: {"endpoints": {"primary": None}}}}
    assert source == original
    assert [call[0] for call in client.mock_calls] == [
        "namespaces.get", "namespaces.begin_update", "namespaces.begin_update().result",
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
    client.namespaces.begin_update.assert_not_called()
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
    client.namespaces.begin_update.assert_called_once()
    assert "Could not verify" in caplog.text
    assert "Continuing without changing role assignments; ADR may reject removal." in caplog.text
    if defect == "identity":
        assert "identity" not in client.namespaces.begin_update.call_args.kwargs["properties"]
    if defect != "rbac":
        unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("resource_id", [
    pytest.param(123, id="integer"),
    pytest.param(["invalid"], id="list"),
    pytest.param({"id": "invalid"}, id="object"),
    pytest.param(True, id="boolean"),
])
@pytest.mark.parametrize("no_rbac_check", [False, True])
def test_delete_real_sdk_non_string_resource_id_does_not_block_unlink(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, resource_id, no_rbac_check,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["resourceId"] = resource_id
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.patch(URL, json=completed)

        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", no_rbac_check=no_rbac_check,
        )

        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        assert json.loads(network.calls[1].request.body) == {"properties": {section: {"endpoints": {"primary": None}}}}
        assert ("did not include a string resourceId" in caplog.text) is (not no_rbac_check)
        assert ("Continuing without changing role assignments" in caplog.text) is (not no_rbac_check)
        unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("prefix", ["", "/subscriptions/sub", "/resourceGroups/rg"])
@pytest.mark.parametrize("no_rbac_check", [False, True])
def test_delete_real_sdk_unscoped_resource_id_is_advisory(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, prefix, no_rbac_check,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["resourceId"] = f"{prefix}/providers/{_endpoint_type}/primary"
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.patch(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", no_rbac_check=no_rbac_check,
        )
        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert body == {"properties": {section: {"endpoints": {"primary": None}}}}
    assert ("resource-group-scoped ARM resource ID" in caplog.text) is (not no_rbac_check)
    assert ("Continuing without changing role assignments" in caplog.text) is (not no_rbac_check)
    unlink_rbac.check_unlink_read_access.assert_not_called()


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
@pytest.mark.parametrize("state,no_rbac_check", [
    pytest.param("Succeeded", False, id="advisory"),
    pytest.param("Succeeded", True, id="no-rbac-check"),
    pytest.param("Failed", False, id="failed-link"),
    pytest.param("LinkedResourceDeleted", False, id="deleted-resource"),
])
def test_delete_real_sdk_malformed_identity_is_advisory(
    fixture_cmd, unlink_client, unlink_rbac, caplog, kind, section, _endpoint_type, field, value, state, no_rbac_check,
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
        network.patch(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")(
            "primary", "ns", "rg", no_rbac_check=no_rbac_check,
        )
        assert result == completed
        assert source == original
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
        body = json.loads(network.calls[1].request.body)
        assert body == {"properties": {section: {"endpoints": {"primary": None}}}}
        assert ("Could not verify" in caplog.text) is (state == "Succeeded" and not no_rbac_check)
        assert ("Continuing without changing role assignments" in caplog.text) is (state == "Succeeded" and not no_rbac_check)
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
        network.patch(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")

        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "GET", "PATCH"]
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
    client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["get", "patch", "result"])
@pytest.mark.parametrize("error_type", [HttpResponseError, ServiceRequestError, DeserializationError])
def test_delete_does_not_translate_or_swallow_backend_errors(fixture_cmd, kind, section, _endpoint_type, stage, error_type):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = error_type("original backend error")
    operation = {
        "get": client.namespaces.get,
        "patch": client.namespaces.begin_update,
        "result": client.namespaces.begin_update.return_value.result,
    }[stage]
    operation.side_effect = error
    with pytest.raises(error_type) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is error
    if stage == "get":
        client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["patch", "result"])
def test_delete_conflict_warns_and_preserves_original_exception(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, stage,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = HttpResponseError("original conflict detail")
    error.status_code = 412
    operation = client.namespaces.begin_update
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
    assert client.namespaces.get.call_count == client.namespaces.begin_update.call_count == 1
    unlink_rbac.check_unlink_read_access.assert_called_once_with("ns-user", TARGET_RG, grant_reader=False)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("no_rbac_check", [False, True])
@pytest.mark.parametrize("grant_reader", [False, True])
def test_delete_command_handler_forwards_selectors_and_flags(
    mocker, kind, section, _endpoint_type, no_wait, no_rbac_check, grant_reader,
):
    provider_type = mocker.patch.object(commands_link, "LinkProvider")
    handler = getattr(commands_link, f"adr_link_{kind}_remove")
    cmd, client = Mock(), Mock()
    assert handler(
        cmd, client, "primary", "ns", "rg", no_wait=no_wait, no_rbac_check=no_rbac_check, grant_reader=grant_reader,
    ) is getattr(
        provider_type.return_value, kind + "_remove",
    ).return_value
    provider_type.assert_called_once_with(cmd, client=client)
    getattr(provider_type.return_value, kind + "_remove").assert_called_once_with(
        endpoint_name="primary", namespace_name="ns", resource_group_name="rg",
        no_wait=no_wait, no_rbac_check=no_rbac_check, grant_reader=grant_reader,
    )


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("status", [200, 202])
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
        network.patch(URL, json=initial, status=status, headers={
            "Azure-AsyncOperation": STATUS_URL, "Location": URL + "/must-not-follow", "Retry-After": "0",
        })
        network.get(STATUS_URL, json={"status": "Running"})
        network.get(STATUS_URL, json={"status": "Succeeded"})
        network.get(URL, json=completed)
        result = getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert result == completed
        assert [call.request.method for call in network.calls] == ["GET", "PATCH", "GET", "GET", "GET"]
        assert [call.request.url for call in network.calls[2:4]] == [STATUS_URL, STATUS_URL]
        assert network.calls[1].request.headers["If-Match"] == expected_etag
        body = json.loads(network.calls[1].request.body)
        assert body == {"properties": {section: {"endpoints": {"primary": None}}}}
        unlink_rbac.check_unlink_read_access.assert_called_once_with("ns-user", TARGET_RG, grant_reader=False)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_delete_real_sdk_raises_async_service_failure(fixture_cmd, unlink_client, kind, section, _endpoint_type, state):
    from azext_iot.tests.adr.test_adr_link_delete_int import _assert_unlink_service_rejection

    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.patch(URL, json={"properties": {"provisioningState": "Accepted"}}, status=202,
                      headers={"Azure-AsyncOperation": STATUS_URL})
        network.get(STATUS_URL, json={
            "status": state, "error": {"code": "BackendUnlinkRejected", "message": "Original backend unlink detail."},
        })
        with pytest.raises(HttpResponseError, match="Original backend unlink detail") as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert [call.request.method for call in network.calls] == ["GET", "PATCH", "GET"]
        assert network.calls[-1].request.url == STATUS_URL
        namespace_id = URL.removeprefix("https://management.azure.com")
        if state == "Failed":
            assert _assert_unlink_service_rejection(raised.value, namespace_id) == "BackendUnlinkRejected"
        else:
            with pytest.raises(AssertionError, match="did not fail"):
                _assert_unlink_service_rejection(raised.value, namespace_id)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["async-status", "final-resource"])
@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_delete_real_sdk_preserves_polling_http_error_after_retries(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, stage, status,
):
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.patch(URL, json={"properties": {"provisioningState": "Accepted"}}, status=202,
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
            ["GET", "PATCH"] + (["GET"] if stage == "final-resource" else []) + ["GET"] * attempts
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
        network.patch(URL, json={"properties": {"provisioningState": "Accepted"}}, status=202,
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
        assert [call.request.method for call in network.calls] == ["GET", "PATCH", "GET", "GET", "GET"]
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
        network.patch(URL, json={
            "properties": {"provisioningState": state},
            "error": {"code": "BackendUnlinkRejected", "message": "Original inline unlink detail."},
        })
        with pytest.raises(AzureResponseError, match="BackendUnlinkRejected: Original inline unlink detail"):
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_no_wait_returns_poller_without_waiting(mocker, fixture_cmd, kind, section, _endpoint_type):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    provider = LinkProvider(fixture_cmd, client=client)
    wait = mocker.patch.object(provider, "_await_terminal", side_effect=AssertionError("Unexpected wait"))
    assert getattr(provider, kind + "_remove")("primary", "ns", "rg", no_wait=True) is (
        client.namespaces.begin_update.return_value
    )
    wait.assert_not_called()
    client.namespaces.begin_update.return_value.result.assert_not_called()


@pytest.mark.parametrize("stage", ["get", "patch"])
@pytest.mark.parametrize("status", [400, 403, 404, 409, 412, 429, 500, 503])
def test_delete_real_sdk_preserves_backend_error_without_retries(fixture_cmd, unlink_client, caplog, stage, status):
    failure = {"error": {"code": "BackendUnlinkRejected", "message": "Original backend deletion detail."}}
    with responses.RequestsMock() as network:
        if stage == "patch":
            network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.add("GET" if stage == "get" else "PATCH", URL, json=failure, status=status)
        with pytest.raises(HttpResponseError, match="Original backend deletion detail") as raised:
            LinkProvider(fixture_cmd, client=unlink_client).hub_remove("primary", "ns", "rg")
        assert raised.value.status_code == status
        assert raised.value.error.code == "BackendUnlinkRejected"
        assert len(network.calls) == (1 if stage == "get" else 2)
        assert ("rerun the remove command" in caplog.text) is (stage == "patch" and status == 412)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [ServiceRequestError, ServiceResponseError])
def test_delete_real_sdk_does_not_retry_patch_transport_error(
    fixture_cmd, unlink_client, kind, section, _endpoint_type, error_type,
):
    error = error_type("Original PATCH transport error.")
    with responses.RequestsMock() as network:
        network.get(URL, json=namespace(), headers={"ETag": ETAG})
        network.patch(URL, body=error)
        with pytest.raises(error_type) as raised:
            getattr(LinkProvider(fixture_cmd, client=unlink_client), kind + "_remove")("primary", "ns", "rg")
        assert raised.value is error
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_returns_completed_response(offline_cli, mocker, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
                       return_value=(namespace(), ETAG))
    completed = {"properties": {"provisioningState": "Succeeded", section: {"endpoints": {}}}}
    patch = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update",
                         return_value=SimpleNamespace(result=lambda: completed))
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 0
    assert json.loads(output.getvalue()) == completed
    assert get.call_count == patch.call_count == 1
    assert isinstance(patch.call_args.kwargs["polling"], ARMPolling)
    assert patch.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_reports_conflict(offline_cli, mocker, caplog, kind, section, _endpoint_type):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get",
                       return_value=(namespace(), ETAG))
    error = HttpResponseError("Original backend conflict detail.")
    error.status_code = 412
    patch = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update",
                         side_effect=error)
    output = StringIO()

    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) == 1

    assert output.getvalue() == ""
    assert "Original backend conflict detail." in caplog.text
    assert "Inspect the namespace with 'az iot adr ns show' and rerun the remove command." in caplog.text
    assert get.call_count == patch.call_count == 1
    assert patch.call_args.kwargs["headers"] == {"If-Match": ETAG}


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
    client.namespaces.begin_update.assert_not_called()


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

    def concurrent_write(*_args, **_kwargs):
        nonlocal current_etag, concurrent
        stored["tags"]["concurrent"] = "keep"
        stored["identity"]["userAssignedIdentities"][UAMI + "-concurrent"] = {}
        endpoints = stored["properties"][section]["endpoints"]
        endpoints["concurrent"] = deepcopy(endpoints["primary"])
        endpoints["concurrent"]["resourceId"] += "-concurrent"
        current_etag = '"namespace-version-2"'
        concurrent = deepcopy(stored)

    def update(request):
        nonlocal current_etag
        if request.headers.get("If-Match") != current_etag:
            return 412, {}, json.dumps({"error": {"code": "PreconditionFailed", "message": "Namespace changed."}})
        assert json.loads(request.body) == {"properties": {section: {"endpoints": {"primary": None}}}}
        del stored["properties"][section]["endpoints"]["primary"]
        stored["properties"]["provisioningState"] = "Succeeded"
        current_etag = '"namespace-version-3"'
        return 200, {"ETag": current_etag}, json.dumps(stored)

    unlink_rbac.check_unlink_read_access.side_effect = concurrent_write
    with responses.RequestsMock() as network, DeviceRegistryMgmtClient(credential, "sub") as client:
        network.add_callback("GET", URL, callback=read, content_type="application/json")
        network.add_callback("PATCH", URL, callback=update, content_type="application/json")
        provider = LinkProvider(fixture_cmd, client=client)
        with pytest.raises(HttpResponseError) as raised:
            getattr(provider, kind + "_remove")("primary", "ns", "rg")
        assert raised.value.status_code == 412
        assert stored == concurrent
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG

        unlink_rbac.check_unlink_read_access.side_effect = None
        result = getattr(provider, kind + "_remove")("primary", "ns", "rg")
        assert [call.request.method for call in network.calls] == ["GET", "PATCH", "GET", "PATCH"]
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
    patch = mocker.patch(
        "azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update",
        return_value=SimpleNamespace(result=Mock(side_effect=error)),
    )
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "-o", "json"], out_file=output) != 0
    assert not output.getvalue().strip()
    assert "Original asynchronous unlink error" in str(offline_cli.result.error)
    patch.assert_called_once()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_real_cli_accepts_no_wait(offline_cli, mocker, kind, section, _endpoint_type):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=(namespace(), ETAG))
    poller = Mock(spec=LROPoller)
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update", return_value=poller)
    output = StringIO()
    assert offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                               "-g", "rg", "--yes", "--no-wait", "-o", "json"], out_file=output) == 0
    poller.result.assert_not_called()
    assert not output.getvalue().strip()


@pytest.mark.parametrize("option", [
    "--timeout", "--interval", "--delete-linked-resource", "--system-assigned-mi", "--skip-permission-check",
])
@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_delete_rejects_composite_and_wait_options(offline_cli, kind, option):
    with pytest.raises(SystemExit) as raised:
        offline_cli.invoke(["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns",
                            "-g", "rg", "--yes", option, *(["10"] if option in ("--timeout", "--interval") else [])])
    assert raised.value.code == 2


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["Succeeded", "Failed", "LinkedResourceDeleted"])
@pytest.mark.parametrize("no_rbac_check", [False, True])
def test_delete_warning_explains_state_and_hub_prerequisites(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, state, no_rbac_check,
):
    source = namespace()
    source["properties"][section]["endpoints"]["primary"]["linkingState"] = state
    client = Mock()
    client.namespaces.get.return_value = (source, ETAG)
    getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg", no_rbac_check=no_rbac_check)
    assert "For a Succeeded link, delete the linked resource first" in caplog.text
    assert "Failed links do not require the linked resource to be deleted." in caplog.text
    assert ("EndpointUsedByNestedDevices" in caplog.text) is (kind == "hub")
    if kind == "hub":
        assert "any Hub endpoint, including Failed links" in caplog.text
        assert "Deleting the IoT Hub does not clear these references." in caplog.text
    assert unlink_rbac.check_unlink_read_access.call_count == (state == "Succeeded" and not no_rbac_check)
    client.namespaces.begin_update.assert_called_once()


@pytest.mark.parametrize("state", ["Succeeded", "Failed"])
@pytest.mark.parametrize("no_rbac_check", [False, True])
def test_delete_real_sdk_preserves_hub_device_reference_rejection(fixture_cmd, unlink_client, caplog, state, no_rbac_check):
    source = namespace()
    source["properties"]["messaging"]["endpoints"]["primary"]["linkingState"] = state
    with responses.RequestsMock() as network:
        network.get(URL, json=source, headers={"ETag": ETAG})
        network.patch(URL, status=400, json={"error": {
            "code": "EndpointUsedByNestedDevices", "message": "Registry Devices still reference this Hub endpoint.",
        }})
        with pytest.raises(HttpResponseError) as raised:
            LinkProvider(fixture_cmd, client=unlink_client).hub_remove("primary", "ns", "rg", no_rbac_check=no_rbac_check)
        assert raised.value.status_code == 400
        assert raised.value.error.code == "EndpointUsedByNestedDevices"
        assert [call.request.method for call in network.calls] == ["GET", "PATCH"]
        assert network.calls[1].request.headers["If-Match"] == ETAG
    assert "Clear Registry Device IoT Hub capability references" in caplog.text


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("state", ["LinkedResourceDeleted", "Failed", "InProgress", "Canceled", "", None, "Unexpected"])
@pytest.mark.parametrize("grant_reader", [False, True])
def test_delete_state_gate_skips_identity_target_and_permission_work(
    fixture_cmd, mocker, unlink_rbac, caplog, kind, section, _endpoint_type, state, grant_reader,
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
    getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")(
        "primary", "ns", "rg", grant_reader=grant_reader,
    )
    resolver.assert_not_called()
    unlink_rbac.check_unlink_read_access.assert_not_called()
    client.namespaces.begin_update.assert_called_once()
    assert ("permission preflight is unavailable" in caplog.text) is (state not in ("LinkedResourceDeleted", "Failed"))


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [
    AzureResponseError, HttpResponseError, ServiceRequestError, ServiceResponseError, DeserializationError,
])
@pytest.mark.parametrize("stage", ["patch", "result"])
def test_delete_permission_errors_warn_but_do_not_swallow_backend_rejection(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, error_type, stage,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    unlink_rbac.check_unlink_read_access.side_effect = error_type("permission lookup unavailable")
    rejection = HttpResponseError("ADR unlink rejected")
    operation = client.namespaces.begin_update
    if stage == "result":
        operation = operation.return_value.result
    operation.side_effect = rejection
    with pytest.raises(HttpResponseError) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg")
    assert raised.value is rejection
    assert "permission lookup unavailable" in caplog.text
    assert "ADR may reject removal" in caplog.text


@pytest.mark.parametrize("status", [400, 409, 401, 403, 404, 412, 429, 500, 503])
@pytest.mark.parametrize("method,resource", [("PATCH", "ns"), ("GET", "ns"), ("PATCH", "other")])
def test_live_unlink_negative_requires_a_structured_namespace_mutation_rejection(status, method, resource):
    from azext_iot.tests.adr.test_adr_link_delete_int import _assert_unlink_service_rejection

    namespace_id = "/subscriptions/s/resourceGroups/g/providers/Microsoft.DeviceRegistry/namespaces/ns"
    error = HttpResponseError("Synthetic rejection")
    error.status_code = status
    error.error = SimpleNamespace(code="SyntheticServiceRejection")
    error.response = SimpleNamespace(request=SimpleNamespace(
        method=method, url="https://management.azure.com" + namespace_id.removesuffix("ns") + resource,
    ))
    if status == 400 and method == "PATCH" and resource == "ns":
        _assert_unlink_service_rejection(error, namespace_id)
    else:
        with pytest.raises(AssertionError):
            _assert_unlink_service_rejection(error, namespace_id)


@pytest.mark.parametrize("state,foreign", [("Failed", False), ("Canceled", False), ("Failed", True)])
def test_live_unlink_inline_failure_requires_the_same_failed_namespace(state, foreign):
    from azext_iot.adr.providers.base import ADRResourceStateError
    from azext_iot.tests.adr.test_adr_link_delete_int import _assert_unlink_service_rejection

    namespace_id = URL.removeprefix("https://management.azure.com")
    error = ADRResourceStateError("Synthetic terminal failure", {
        "id": namespace_id + ("-other" if foreign else ""),
        "properties": {"provisioningState": state},
    })
    if state == "Failed" and not foreign:
        assert _assert_unlink_service_rejection(error, namespace_id) is None
    else:
        with pytest.raises(AssertionError):
            _assert_unlink_service_rejection(error, namespace_id)


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("option", [None, "--no-rbac-check", "--grant-reader"])
def test_delete_real_cli_no_rbac_check_is_independent_of_yes_and_no_wait(
    offline_cli, mocker, unlink_rbac, kind, section, _endpoint_type, no_wait, option,
):
    mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get", return_value=(namespace(), ETAG))
    poller = Mock(spec=LROPoller)
    poller.result.return_value = {"properties": {"provisioningState": "Succeeded"}}
    patch = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update",
                         return_value=poller)
    output = StringIO()
    args = ["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns", "-g", "rg", "--yes"]
    if option:
        args.append(option)
    if no_wait:
        args.append("--no-wait")
    assert offline_cli.invoke(args, out_file=output) == 0
    if option == "--no-rbac-check":
        unlink_rbac.check_unlink_read_access.assert_not_called()
    else:
        unlink_rbac.check_unlink_read_access.assert_called_once_with(
            "ns-user", TARGET_RG, grant_reader=option == "--grant-reader",
        )
    assert poller.result.call_count == (0 if no_wait else 1)
    assert patch.call_args.kwargs["headers"] == {"If-Match": ETAG}


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
def test_delete_no_rbac_check_does_not_bypass_etag_or_endpoint_validation(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), None)
    provider = LinkProvider(fixture_cmd, client=client)
    with pytest.raises(AzureResponseError, match="usable ETag"):
        getattr(provider, kind + "_remove")("primary", "ns", "rg", no_rbac_check=True)
    client.namespaces.get.return_value = (namespace(), ETAG)
    with pytest.raises(ResourceNotFoundError):
        getattr(provider, kind + "_remove")("missing", "ns", "rg", no_rbac_check=True)
    unlink_rbac.check_unlink_read_access.assert_not_called()
    client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("option", ["--no-rbac-check", "--grant-reader"])
def test_delete_permission_flags_do_not_bypass_confirmation(offline_cli, mocker, kind, option):
    confirm = mocker.patch("azure.cli.core.commands.AzCliCommand._user_confirmed", return_value=False)
    provider = mocker.patch.object(commands_link, "LinkProvider")
    assert offline_cli.invoke(
        ["iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns", "-g", "rg",
         option],
    ) != 0
    confirm.assert_called_once()
    assert "only the namespace endpoint, not the linked resource" in confirm.call_args.args[0]
    assert "--grant-reader are retained even if removal fails" in confirm.call_args.args[0]
    provider.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_delete_real_cli_rejects_conflicting_permission_flags(offline_cli, mocker, unlink_rbac, caplog, kind):
    get = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.get")
    patch = mocker.patch("azext_iot.sdk.deviceregistry.operations.NamespacesOperations.begin_update")
    assert offline_cli.invoke([
        "iot", "adr", "ns", "link", kind, "remove", "-n", "primary", "--ns", "ns", "-g", "rg",
        "--yes", "--no-rbac-check", "--grant-reader",
    ]) != 0
    assert "--grant-reader cannot be combined with --no-rbac-check." in caplog.text
    get.assert_not_called()
    patch.assert_not_called()
    unlink_rbac.check_unlink_read_access.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("error_type", [
    AzureResponseError, HttpResponseError, ServiceRequestError, ServiceResponseError, DeserializationError,
])
@pytest.mark.parametrize("no_wait", [False, True])
def test_delete_grant_setup_errors_stop_before_namespace_put(
    fixture_cmd, unlink_rbac, caplog, kind, section, _endpoint_type, error_type, no_wait,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    error = error_type("setup failed after a possible role assignment")
    unlink_rbac.check_unlink_read_access.side_effect = error
    with pytest.raises(AzureResponseError, match="Reader setup could not be completed") as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")(
            "primary", "ns", "rg", grant_reader=True, no_wait=no_wait,
        )
    assert raised.value.__cause__ is error
    assert "endpoint removal was not submitted" in str(raised.value)
    assert "already created are retained" in str(raised.value)
    assert "Continuing without changing role assignments" not in caplog.text
    client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("invalid", ["etag", "identity", "endpoint", "target", "outbound", "principal"])
def test_delete_grant_validates_before_any_rbac_write(fixture_cmd, unlink_rbac, kind, section, _endpoint_type, invalid):
    source = namespace()
    endpoint = source["properties"][section]["endpoints"]["primary"]
    if invalid == "identity":
        source["identity"] = []
    elif invalid == "endpoint":
        endpoint["endpointType"] = "Wrong.Type"
    elif invalid == "target":
        endpoint["resourceId"] = "/subscriptions/target-sub/providers/Microsoft.Devices/IotHubs/missing-rg"
    elif invalid == "outbound":
        source["properties"]["outboundIdentity"] = []
    elif invalid == "principal":
        source["identity"]["userAssignedIdentities"][UAMI].pop("principalId")
    client = Mock()
    client.namespaces.get.return_value = (source, None if invalid == "etag" else ETAG)
    with pytest.raises((AzureResponseError, ResourceNotFoundError)):
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg", grant_reader=True)
    unlink_rbac.check_unlink_read_access.assert_not_called()
    client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind,section,_endpoint_type", KINDS)
@pytest.mark.parametrize("stage", ["patch", "result"])
@pytest.mark.parametrize("status", [400, 403, 412, 500])
def test_delete_grant_is_retained_on_namespace_failure_without_retry(
    fixture_cmd, unlink_rbac, kind, section, _endpoint_type, stage, status,
):
    client = Mock()
    client.namespaces.get.return_value = (namespace(), ETAG)
    unlink_rbac.created = [("ns-user", "Reader", TARGET_RG)]
    failure = HttpResponseError("original namespace failure")
    failure.status_code = status
    operation = client.namespaces.begin_update
    if stage == "result":
        operation = operation.return_value.result
    operation.side_effect = failure
    with pytest.raises(HttpResponseError) as raised:
        getattr(LinkProvider(fixture_cmd, client=client), kind + "_remove")("primary", "ns", "rg", grant_reader=True)
    assert raised.value is failure
    assert client.namespaces.get.call_count == client.namespaces.begin_update.call_count == 1
    assert unlink_rbac.created == [("ns-user", "Reader", TARGET_RG)]
    assert unlink_rbac.method_calls == [call.check_unlink_read_access("ns-user", TARGET_RG, grant_reader=True)]
