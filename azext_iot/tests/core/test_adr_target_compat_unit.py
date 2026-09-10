# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, RequiredArgumentMissingError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError

from azext_iot import _factory
from azext_iot.core import custom
from azext_iot.tests.test_factory_unit import CLOUD_CONFIGS, _build_cli_ctx


CANARY = "https://centraluseuap.management.azure.com"
NAMESPACE_ID = (
    "/subscriptions/namespace-sub/resourceGroups/ns-rg/providers/"
    "Microsoft.DeviceRegistry/namespaces/ns"
)
TARGETS = [
    ("hub", "iot_hub_resource", "IotHubs", "resource_name",
     "iot_hub_service_factory", "adr_iot_hub_service_factory",
     "2026-10-01-preview", "2026-10-01-preview"),
    ("dps", "iot_dps_resource", "provisioningServices", "provisioning_service_name",
     "iot_service_provisioning_factory", "adr_iot_service_provisioning_factory",
     "2026-06-01-preview", "2026-06-01-preview"),
]


@pytest.mark.parametrize("cloud", CLOUD_CONFIGS, ids=lambda value: value["id"])
@pytest.mark.parametrize("target", TARGETS, ids=lambda value: value[0])
@pytest.mark.parametrize("adr", [False, True], ids=["general", "adr"])
@pytest.mark.parametrize("subscription", [None, "target-sub"])
def test_native_preview_management_wire_contract(
    mocker, mocked_response, cloud, target, adr, subscription,
):
    kind, group, resource_type, name_arg, general_factory, adr_factory, default_api, adr_api = target
    cli_ctx = _build_cli_ctx(mocker, cloud)
    credential = mocker.Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("test-token", 4102444800)
    get_credential = mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    selected_sub = subscription or "test-sub-id"
    endpoint = CANARY if adr else cloud["resource_manager"]
    resource_id = (
        f"/subscriptions/{selected_sub}/resourceGroups/rg/providers/"
        f"Microsoft.Devices/{resource_type}/{kind}"
    )
    response = {
        "id": resource_id, "identity": {"type": "SystemAssigned", "principalId": "principal"},
        "properties": {
            "provisioningState": "Succeeded",
            "deviceRegistry": {"identity": {"type": "SystemAssigned"}},
            "deviceRegistryNamespaces": [{"resourceId": NAMESPACE_ID}],
            "futureUnknownProjection": {"preserved": True},
        },
    }
    mocked_response.add("GET", endpoint + resource_id, json=response, status=200)
    mocked_response.add("DELETE", endpoint + resource_id, status=204)
    factory = getattr(_factory, adr_factory if adr else general_factory)
    with factory(cli_ctx, subscription_id=subscription) as client:
        operations = getattr(client, group)
        arguments = {"resource_group_name": "rg", name_arg: kind}
        assert operations.get(**arguments) == response
        # Preview's native DELETE callbacks work without the generated-SDK repair.
        assert operations.begin_delete(**arguments, polling=False).result() is None
        assert client._config.api_version == (adr_api if adr else default_api)
    assert [call.request.method for call in mocked_response.calls] == ["GET", "DELETE"]
    for call in mocked_response.calls:
        assert parse_qs(urlsplit(call.request.url).query)["api-version"] == [
            adr_api if adr else default_api
        ]
        assert f"/subscriptions/{selected_sub}/" in call.request.url
    get_credential.assert_called_once_with(cli_ctx, subscription_id=selected_sub)
    assert credential.get_token.call_args.args == tuple(cloud["expected_scopes"])


@pytest.mark.parametrize("factory_name", [
    "adr_service_factory", "adr_iot_hub_service_factory",
    "adr_iot_service_provisioning_factory", "adr_update_instance_service_factory",
])
def test_adr_command_factories_use_cli_selected_subscription(mocker, factory_name):
    cli_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[0])
    cli_ctx.data["subscription_id"] = "explicit-namespace-sub"
    fallback = mocker.patch("azure.cli.core._profile.Profile.get_subscription_id")
    credential = mocker.patch.object(_factory, "get_cli_credential", return_value=object())
    client = getattr(_factory, factory_name)(cli_ctx, {"namespace_name": "ns"})
    assert client._config.subscription_id == "explicit-namespace-sub"
    credential.assert_called_once_with(cli_ctx, subscription_id="explicit-namespace-sub")
    fallback.assert_not_called()


def test_software_update_data_factory_requires_service_endpoint(mocker):
    cli_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[0])
    with pytest.raises(RequiredArgumentMissingError, match="service-derived"):
        _factory.adr_software_update_data_service_factory(cli_ctx)
    credential = mocker.patch.object(_factory, "get_cli_credential", return_value=object())
    client = _factory.adr_software_update_data_service_factory(
        cli_ctx, endpoint="updates.example.test"
    )
    assert client._config.endpoint == "updates.example.test"
    credential.assert_called_once_with(cli_ctx)


@pytest.fixture(params=TARGETS, ids=lambda value: value[0])
def guard_target(request, mocker):
    kind, group, resource_type, name_arg, _, factory_name, _, _ = request.param
    resource = {
        "id": f"/subscriptions/target-sub/resourceGroups/target-rg/providers/Microsoft.Devices/{resource_type}/{kind}",
        "name": kind, "location": "centraluseuap", "etag": "etag",
        "identity": {"type": "SystemAssigned", "principalId": "principal"},
        "properties": {},
    }
    factory = mocker.patch.object(_factory, factory_name)
    get = getattr(factory.return_value, group).get
    get.return_value = deepcopy(resource)
    return kind, group, name_arg, resource, factory, get


def test_identity_target_reads_selected_subscription_without_mutating_general_response(mocker, guard_target):
    kind, _, name_arg, resource, factory, get = guard_target
    cmd = mocker.Mock()
    authoritative = get.return_value
    authoritative["properties"]["newProjection"] = {"preserved": True}
    original = deepcopy(resource)
    assert custom._adr_identity_target(cmd, resource, kind) == authoritative
    assert resource == original
    factory.assert_called_once_with(cmd.cli_ctx, subscription_id="target-sub")
    get.assert_called_once_with(resource_group_name="target-rg", **{name_arg: kind})


@pytest.mark.parametrize("response", [None, {}, {"id": "/wrong/resource"}])
def test_identity_target_rejects_unverifiable_response(mocker, guard_target, response):
    kind, _, _, resource, _, get = guard_target
    get.return_value = response
    with pytest.raises(ArgumentUsageError, match="could not be validated"):
        custom._adr_identity_target(mocker.Mock(), resource, kind)


@pytest.mark.parametrize("resource", [None, {}, {"id": 123}, {"id": "/invalid"}])
def test_identity_target_requires_arm_id_before_factory(mocker, guard_target, resource):
    kind, _, _, _, factory, _ = guard_target
    with pytest.raises(ArgumentUsageError, match="target resource ID"):
        custom._adr_identity_target(mocker.Mock(), resource, kind)
    factory.assert_not_called()


def test_direct_python_guard_accepts_authoritative_object(guard_target):
    kind, _, _, resource, factory, _ = guard_target
    assert custom._adr_identity_target(None, resource, kind) is resource
    factory.assert_not_called()


@pytest.mark.parametrize("entry", ["generic", "dedicated"])
@pytest.mark.parametrize("outcome", ["linked", "unlinked", "forbidden"])
def test_identity_mutation_uses_adr_projection_and_fails_before_put(
    mocker, guard_target, entry, outcome,
):
    kind, group, _, resource, factory, get = guard_target
    cmd, client = mocker.Mock(), mocker.Mock()
    operations = getattr(client, group)
    operations.get.return_value = deepcopy(resource)
    desired = deepcopy(resource)
    desired["identity"] = {"type": "None"}
    namespace_factory = mocker.patch.object(_factory, "adr_service_factory")
    if outcome == "linked":
        if kind == "hub":
            get.return_value["properties"]["deviceRegistry"] = {
                "namespaceResourceId": NAMESPACE_ID,
                "identity": {"type": "SystemAssigned"},
                "linkingProperties": {"state": "Success"},
            }
        else:
            get.return_value["properties"]["deviceRegistryNamespaces"] = [{"resourceId": NAMESPACE_ID}]
            namespace_factory.return_value.namespaces.get.return_value = {
                "properties": {"provisioning": {"endpoints": {"dps": {
                    "resourceId": resource["id"],
                    "inboundCallerIdentity": {"type": "SystemAssigned"},
                }}}},
            }
    elif outcome == "forbidden":
        get.side_effect = HttpResponseError(message="Forbidden")
        get.side_effect.status_code = 403
    mocker.patch.object(custom, "iot_hub_get", return_value=deepcopy(resource))
    mocker.patch.object(custom, "LongRunningOperation").return_value.return_value = desired

    def mutate():
        if kind == "hub":
            if entry == "generic":
                return custom.iot_hub_update(client, kind, desired, "target-rg", cmd=cmd)
            return custom.iot_hub_identity_remove(
                cmd, client, kind, system_identity=True, resource_group_name="target-rg",
            )
        if entry == "generic":
            return custom.iot_dps_update(client, kind, desired, "target-rg", cmd=cmd)
        return custom.dps_identity_remove(
            client, kind, system_assigned=True, resource_group_name="target-rg", cmd=cmd,
        )

    if outcome == "unlinked":
        mutate()
        operations.begin_create_or_update.assert_called_once()
        body_key = "iot_hub_description" if kind == "hub" else "iot_dps_description"
        body = operations.begin_create_or_update.call_args.kwargs[body_key]
        assert body["identity"] == {"type": "None"}
        if kind == "hub":
            assert operations.begin_create_or_update.call_args.kwargs["etag"] == "etag"
    else:
        with pytest.raises(ArgumentUsageError, match="active ADR|could not be validated"):
            mutate()
        operations.begin_create_or_update.assert_not_called()
    factory.assert_called_once_with(cmd.cli_ctx, subscription_id="target-sub")
    if kind == "dps" and outcome == "linked":
        namespace_factory.assert_called_once_with(cmd.cli_ctx, subscription_id="namespace-sub")
    else:
        namespace_factory.assert_not_called()


def test_preview_hub_create_preserves_existing_identity_without_adr_read(mocker, preview_mgmt):
    cmd, client, hub, _, _ = preview_mgmt
    hub["identity"] = {
        "type": "SystemAssigned, UserAssigned", "principalId": "principal",
        "userAssignedIdentities": {"/identities/user": {"principalId": "user-principal"}},
    }
    original = deepcopy(hub)
    adr_factory = mocker.patch.object(_factory, "adr_iot_hub_service_factory")
    result = custom.iot_hub_create(cmd, client, "hub", "rg")
    assert result is client.iot_hub_resource.begin_create_or_update.return_value
    write = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert write["iot_hub_description"]["identity"] == {
        "type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {"/identities/user": {}},
    }
    assert write["etag"] == "hub-etag"
    assert hub == original
    adr_factory.assert_not_called()


@pytest.mark.parametrize("state", ["Success", "Failed"])
def test_preview_hub_create_identity_removal_uses_authoritative_link_state(mocker, preview_mgmt, state):
    cmd, client, hub, _, _ = preview_mgmt
    hub["id"] = "/subscriptions/target-sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub"
    original = deepcopy(hub)
    target = deepcopy(hub)
    target["properties"]["deviceRegistry"] = {
        "namespaceResourceId": NAMESPACE_ID, "identity": {"type": "SystemAssigned"},
        "linkingProperties": {"state": state},
    }
    adr_factory = mocker.patch.object(_factory, "adr_iot_hub_service_factory")
    adr_factory.return_value.iot_hub_resource.get.return_value = target
    if state == "Success":
        with pytest.raises(ArgumentUsageError, match="active ADR link"):
            custom.iot_hub_create(cmd, client, "hub", "rg", system_identity=False)
        client.iot_hub_resource.begin_create_or_update.assert_not_called()
    else:
        assert custom.iot_hub_create(cmd, client, "hub", "rg", system_identity=False) is (
            client.iot_hub_resource.begin_create_or_update.return_value
        )
        write = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
        assert write["iot_hub_description"]["identity"] == {"type": "None"}
        assert write["etag"] == "hub-etag"
    assert hub == original
    adr_factory.assert_called_once_with(cmd.cli_ctx, subscription_id="target-sub")
    adr_factory.return_value.iot_hub_resource.get.assert_called_once_with(
        resource_group_name="rg", resource_name="hub"
    )
