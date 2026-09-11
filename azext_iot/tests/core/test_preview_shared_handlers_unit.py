# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

from azext_iot import _factory
from azext_iot.common.base_discovery import _format_policy_set
from azext_iot.constants import IOTDPS_RESOURCE_ID, IOTHUB_RESOURCE_ID
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.iothub.providers.message_endpoint import MessageEndpoint


@pytest.fixture(params=["hub", "dps"])
def discovery(request, mocker, preview_mgmt):
    _, _, hub, dps, _ = preview_mgmt
    kind = request.param
    client = mocker.Mock(spec=[
        "list_by_subscription", "list_by_resource_group", "list_keys", "get",
        "get_keys_for_key_name", "list_keys_for_key_name",
    ])
    resource = deepcopy(hub if kind == "hub" else dps)
    if kind == "dps":
        resource["properties"].update(serviceOperationsHostName="dps.azure-devices-provisioning.net", idScope="scope")
    subject = IotHubDiscovery(client) if kind == "hub" else DPSDiscovery(client)
    policy = {
        "keyName": "owner", "rights": "RegistryWrite, ServiceConnect, DeviceConnect, ServiceConfig, EnrollmentWrite",
        "primaryKey": "primary", "secondaryKey": "secondary",
    }
    client.get.return_value = resource
    client.list_by_subscription.return_value.by_page.return_value = [[{"name": "other"}], [resource]]
    client.list_by_resource_group.return_value.by_page.return_value = [[resource]]
    client.list_keys.return_value.by_page.return_value = [[{"keyName": "unusable", "rights": "Read"}], [policy]]
    client.get_keys_for_key_name.return_value = policy
    client.list_keys_for_key_name.return_value = policy
    return subject, client, resource, policy, kind


@pytest.mark.parametrize("rg", [None, "rg"])
def test_discovery_flattens_resource_pages(discovery, rg):
    subject, client, resource, _, _ = discovery
    assert subject.get_resources(rg) == ([resource] if rg else [{"name": "other"}, resource])
    if rg:
        client.list_by_resource_group.assert_called_once_with(resource_group_name="rg")
        client.list_by_subscription.assert_not_called()
    else:
        client.list_by_subscription.assert_called_once_with()
        client.list_by_resource_group.assert_not_called()


@pytest.mark.parametrize("rg", [None, "rg"])
def test_discovery_finds_resource_with_preview_operation_names(discovery, rg):
    subject, client, resource, _, kind = discovery
    assert subject.find_resource(kind.upper(), rg) is resource
    if rg:
        key = "resource_name" if kind == "hub" else "provisioning_service_name"
        client.get.assert_called_once_with(resource_group_name="rg", **{key: kind.upper()})
    else:
        client.get.assert_not_called()


@pytest.mark.parametrize("pages", [[], [[{"name": "other"}]]])
def test_discovery_missing_subscription_resource(discovery, pages):
    subject, client, _, _, _ = discovery
    client.list_by_subscription.return_value.by_page.return_value = pages
    with pytest.raises(ResourceNotFoundError, match="current subscription unknown"):
        subject.find_resource("missing")


def test_discovery_resource_lookup_error_uses_preview_error_contract(discovery):
    subject, client, _, _, _ = discovery
    client.get.side_effect = HttpResponseError(message="not found")
    with pytest.raises(ResourceNotFoundError, match="resource group: rg"):
        subject.find_resource("missing", "rg")
    client.list_by_subscription.assert_not_called()


@pytest.mark.parametrize("policy_name", ["auto", "owner"])
def test_discovery_selects_usable_or_named_policy(discovery, policy_name):
    subject, client, _, policy, kind = discovery
    assert subject.find_policy(kind, "rg", policy_name) == policy
    arguments = {"resource_group_name": "rg", "resource_name" if kind == "hub" else "provisioning_service_name": kind}
    if policy_name == "auto":
        client.list_keys.assert_called_once_with(**arguments)
        client.get_keys_for_key_name.assert_not_called()
    else:
        client.get_keys_for_key_name.assert_called_once_with(key_name="owner", **arguments)
        client.list_keys.assert_not_called()


def test_discovery_reports_missing_privileged_policy(discovery):
    subject, client, _, _, kind = discovery
    client.list_keys.return_value.by_page.return_value = [[{"keyName": "read-only", "rights": "Read"}]]
    with pytest.raises(ResourceNotFoundError, match="Unable to discover a priviledged policy") as raised:
        subject.find_policy(kind, "rg")
    assert all(right in str(raised.value) for right in subject.necessary_rights_set)


@pytest.mark.parametrize("rights", [{"Read"}, {"Read", "Write"}, {"Read", "Write", "Connect"}])
def test_policy_error_formats_each_required_right(rights):
    result = _format_policy_set(rights)
    assert {part.strip(" ,'") for part in result.replace("and ", "").split("'") if part.strip(" ,'")} == rights
    assert result.count(" and ") == (1 if len(rights) > 1 else 0)
    assert result.count(",") == (len(rights) - 1 if len(rights) > 2 else 0)


@pytest.mark.parametrize("prefix", ["", "https://", "http://"])
@pytest.mark.parametrize("auth_type", ["key", "login"])
def test_discovery_get_target_normalizes_url_and_uses_preview_group(discovery, prefix, auth_type):
    subject, client, resource, _, kind = discovery
    result = subject.get_target(prefix + kind, rg="rg", auth_type=auth_type)
    hostname = resource["properties"]["hostName" if kind == "hub" else "serviceOperationsHostName"]
    assert result["entity"] == hostname
    assert result["policy"] == ("owner" if auth_type == "key" else "login")
    assert result["primarykey"] == ("primary" if auth_type == "key" else "login")
    assert result["cs"] == (
        f"HostName={hostname};SharedAccessKeyName={result['policy']};SharedAccessKey={result['primarykey']}"
    )
    arguments = {"resource_group_name": "rg", "resource_name" if kind == "hub" else "provisioning_service_name": kind}
    client.get.assert_called_once_with(**arguments)
    if kind == "hub":
        assert result["resourcegroup"] == "rg"
    else:
        assert result["idscope"] == "scope"
    if auth_type == "login":
        client.list_keys.assert_not_called()


def test_discovery_key_hostname_resolves_short_resource_name(discovery):
    subject, client, _, _, kind = discovery
    result = subject.get_target(f"{kind}.azure-devices.net", "rg")
    key = "resource_name" if kind == "hub" else "provisioning_service_name"
    client.get.assert_called_once_with(resource_group_name="rg", **{key: kind})
    assert result["policy"] == "owner"


def test_discovery_login_hostname_bypasses_management(discovery):
    subject, client, _, _, kind = discovery
    result = subject.get_target(f"https://{kind}.example.test", auth_type="login")
    assert result["entity"] == f"{kind}.example.test"
    assert result["policy"] == "login"
    assert result["cs"] == f"HostName={kind}.example.test;SharedAccessKeyName=login;SharedAccessKey=login"
    assert client.mock_calls == []


def test_discovery_connection_string_bypasses_management(discovery):
    subject, client, _, _, kind = discovery
    cstring = f"HostName={kind}.example.test;SharedAccessKeyName=owner;SharedAccessKey=key"
    result = subject.get_target(kind, login=cstring)
    assert result["cs"] == cstring
    assert result["entity"] == f"{kind}.example.test"
    assert result["policy"] == "owner"
    assert client.mock_calls == []


@pytest.mark.parametrize("error", [HttpResponseError(message="denied"), ResourceNotFoundError("missing")])
def test_discovery_targets_skips_inaccessible_resources_with_warning(mocker, discovery, error):
    subject, client, resource, policy, kind = discovery
    inaccessible = deepcopy(resource)
    inaccessible["name"] = "inaccessible"
    client.list_by_subscription.return_value.by_page.return_value = [[inaccessible], [resource]]
    client.get.side_effect = [error, resource]
    warning = mocker.patch("azext_iot.common.base_discovery.logger.warning")
    targets = subject.get_targets()
    assert len(targets) == 1
    assert targets[0]["policy"] == policy["keyName"]
    warning.assert_called_once()
    assert warning.call_args.args[1] == "inaccessible"
    assert client.get.call_count == 2
    assert targets[0]["entity"].startswith(kind + ".")


def test_discovery_empty_targets(discovery):
    subject, client, _, _, _ = discovery
    client.list_by_subscription.return_value.by_page.return_value = []
    assert subject.get_targets() == []
    client.get.assert_not_called()


def test_resource_factory_uses_cli_resource_profile(mocker):
    from azure.cli.core.profiles import ResourceType

    get_client = mocker.patch("azure.cli.core.commands.client_factory.get_mgmt_service_client")
    cli_ctx = mocker.Mock()
    assert _factory.resource_service_factory(cli_ctx) is get_client.return_value
    get_client.assert_called_once_with(cli_ctx, ResourceType.MGMT_RESOURCE_RESOURCES)


@pytest.mark.parametrize("kind,resource_id,sdk_class", [
    ("iothub", IOTHUB_RESOURCE_ID, "azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs"),
    ("dps", IOTDPS_RESOURCE_ID, "azext_iot.sdk.dps.service.ProvisioningServiceClient"),
])
@pytest.mark.parametrize("override", [False, True])
def test_service_sdk_factory_uses_login_or_explicit_credentials(mocker, kind, resource_id, sdk_class, override):
    cmd = mocker.Mock()
    target = {"entity": "service.example.test", "policy": "login", "cmd": cmd}
    credential = mocker.Mock()
    oauth = mocker.patch.object(_factory, "IoTOAuth", return_value=credential)
    constructor = mocker.patch(sdk_class)
    resolver = _factory.SdkResolver(target, auth_override=credential if override else None)
    assert getattr(resolver, f"_get_{kind}_service_sdk")() is constructor.return_value
    constructor.assert_called_once_with(credentials=credential, base_url="https://service.example.test")
    if override:
        oauth.assert_not_called()
    else:
        oauth.assert_called_once_with(cli_ctx=cmd.cli_ctx, resource_id=resource_id)


def test_fabric_endpoint_delete_by_type_preserves_other_types(mocker, preview_mgmt):
    cmd, client, hub, _, _ = preview_mgmt
    endpoints = hub["properties"]["routing"]["endpoints"]
    endpoints["eventStreams"] = [{"name": "fabric-one"}, {"name": "fabric-two"}]
    endpoints["eventHubs"] = [{"name": "keep-eventhub"}]
    factory = mocker.patch("azext_iot.iothub.providers.discovery.iot_hub_service_factory", return_value=client)
    mocker.patch("azext_iot.iothub.providers.discovery.get_subscription_id", return_value="sub")
    mocker.patch("azext_iot.iothub.providers.message_endpoint.EmbeddedCLI")
    provider = MessageEndpoint(cmd, "hub", "rg")
    assert provider.delete(endpoint_type="FABRIC-EVENTSTREAM") is client.iot_hub_resource.begin_create_or_update.return_value
    assert endpoints["eventStreams"] == []
    assert endpoints["eventHubs"] == [{"name": "keep-eventhub"}]
    client.iot_hub_resource.begin_create_or_update.assert_called_once_with("rg", "hub", hub, etag="hub-etag")
    factory.assert_called_once_with(cmd.cli_ctx)
