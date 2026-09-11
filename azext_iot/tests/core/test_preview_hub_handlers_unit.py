# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from datetime import timedelta
from itertools import combinations

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError, CLIInternalError, InvalidArgumentValueError,
    RequiredArgumentMissingError, UnclassifiedUserFault,
)
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.core import custom


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("rg", [None, "rg"])
def test_resource_get_and_list(preview_mgmt, kind, rg):
    cmd, client, hub, dps, _ = preview_mgmt
    resource = hub if kind == "hub" else dps
    operations = getattr(client, f"iot_{kind}_resource")
    operations.list_by_resource_group.return_value = [resource]
    get = getattr(custom, f"iot_{kind}_get")
    args = (cmd, client, kind) if kind == "hub" else (client, kind)
    assert get(*args, resource_group_name=rg) is resource
    assert getattr(custom, f"iot_{kind}_list")(client, rg) == [resource]
    if rg:
        key = "resource_name" if kind == "hub" else "provisioning_service_name"
        operations.get.assert_called_once_with(resource_group_name="rg", **{key: kind})
        if kind == "hub":
            operations.list_by_resource_group.assert_called_once_with(resource_group_name="rg")
        else:
            operations.list_by_resource_group.assert_called_once_with("rg")
    else:
        operations.get.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("resources", [None, [], [{"name": "another"}]])
def test_missing_subscription_resource(preview_mgmt, kind, resources):
    cmd, client, _, _, _ = preview_mgmt
    operations = getattr(client, f"iot_{kind}_resource")
    operations.list_by_subscription.return_value = resources
    with pytest.raises(CLIInternalError, match="current subscription"):
        if kind == "hub":
            custom.iot_hub_get(cmd, client, "missing")
        else:
            custom.iot_dps_get(client, "missing")
    operations.get.assert_not_called()


@pytest.mark.parametrize("missing", ["resource_group", "hub"])
def test_hub_get_rejects_missing_resource(preview_mgmt, missing, mocker):
    cmd, client, _, _, _ = preview_mgmt
    if missing == "resource_group":
        resource_factory = mocker.patch.object(custom, "resource_service_factory")
        resource_factory.return_value.resource_groups.check_existence.return_value = False
    else:
        client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": True}
    with pytest.raises(CLIError, match="could not be found|was not found"):
        custom.iot_hub_get(cmd, client, "hub", "rg")
    client.iot_hub_resource.get.assert_not_called()


@pytest.mark.parametrize("handler,operation", [
    ("iot_hub_delete", "begin_delete"), ("iot_hub_sku_list", "get_valid_skus"),
    ("iot_hub_get_stats", "get_stats"),
])
def test_hub_resource_operations_discover_group(preview_mgmt, handler, operation):
    _, client, _, _, _ = preview_mgmt
    method = getattr(client.iot_hub_resource, operation)
    assert getattr(custom, handler)(client, "HUB") is method.return_value
    method.assert_called_once_with(resource_group_name="rg", resource_name="HUB")


def test_quota_preserves_other_limits(preview_mgmt):
    _, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.get_quota_metrics.return_value = iter([
        {"name": "TotalDeviceCount", "maxValue": 100, "currentValue": 20},
        {"name": "DailyMessageQuota", "maxValue": 400000, "currentValue": 12},
    ])
    assert custom.iot_hub_get_quota_metrics(client, "hub", "rg") == [
        {"name": "TotalDeviceCount", "maxValue": "Unlimited", "currentValue": 20},
        {"name": "DailyMessageQuota", "maxValue": 400000, "currentValue": 12},
    ]


@pytest.mark.parametrize("show_all", [False, True])
@pytest.mark.parametrize("hub_name", [None, "hub"])
@pytest.mark.parametrize("key_type,key", [(custom.KeyType.primary.value, "primary"), (custom.KeyType.secondary, "secondary")])
def test_preview_connection_string_shape(preview_mgmt, show_all, hub_name, key_type, key):
    _, client, _, _, _ = preview_mgmt
    policy = {"keyName": "owner", "primaryKey": "primary", "secondaryKey": "secondary"}
    client.iot_hub_resource.get_keys_for_key_name.return_value = policy
    client.iot_hub_resource.list_keys.return_value = [policy]
    connection_string = f"HostName=hub.azure-devices.net;SharedAccessKeyName=owner;SharedAccessKey={key}"
    result = custom.iot_hub_show_connection_string(
        client, hub_name, policy_name="owner", show_all=show_all, key_type=key_type
    )
    if hub_name is None:
        assert result == [{"name": "hub", "connectionString": [connection_string]}]
    else:
        assert result == {"connectionString": [connection_string] if show_all else connection_string}
    if show_all:
        client.iot_hub_resource.list_keys.assert_called_once_with(resource_group_name="rg", resource_name="hub")
    else:
        client.iot_hub_resource.get_keys_for_key_name.assert_called_once_with(
            resource_group_name="rg", resource_name="hub", key_name="owner"
        )


def test_connection_string_no_hubs(preview_mgmt):
    _, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.list_by_subscription.return_value = None
    with pytest.raises(CLIError, match="No IoT Hub found"):
        custom.iot_hub_show_connection_string(client)


@pytest.mark.parametrize("with_body", [False, True])
def test_consumer_group_create_supports_preview_signatures(mocker, preview_mgmt, with_body):
    _, client, _, _, _ = preview_mgmt
    arguments = ["consumer_group_body"] if with_body else []
    mocker.patch("azure.cli.core.util.get_arg_list", return_value=arguments)
    method = client.iot_hub_resource.create_event_hub_consumer_group
    assert custom.iot_hub_consumer_group_create(client, "hub", "cg") is method.return_value
    expected = {"resource_group_name": "rg", "resource_name": "hub", "event_hub_endpoint_name": "events", "name": "cg"}
    if with_body:
        expected["consumer_group_body"] = {"properties": {"name": "cg"}}
    method.assert_called_once_with(**expected)


@pytest.mark.parametrize("action,operation", [
    ("list", "list_event_hub_consumer_groups"),
    ("get", "get_event_hub_consumer_group"),
    ("delete", "delete_event_hub_consumer_group"),
])
def test_consumer_group_operations(preview_mgmt, action, operation):
    _, client, _, _, _ = preview_mgmt
    args = () if action == "list" else ("cg",)
    method = getattr(client.iot_hub_resource, operation)
    assert getattr(custom, f"iot_hub_consumer_group_{action}")(client, "hub", *args) is method.return_value
    expected = {"resource_group_name": "rg", "resource_name": "hub", "event_hub_endpoint_name": "events"}
    if action != "list":
        expected["name"] = "cg"
    method.assert_called_once_with(**expected)


PERMISSIONS = ["registryread", "registrywrite", "serviceconnect", "deviceconnect"]


@pytest.mark.parametrize("permissions", [
    list(items) for size in range(1, 5) for items in combinations(PERMISSIONS, size)
])
def test_policy_create_deduplicates_permissions(preview_mgmt, permissions):
    cmd, client, hub, _, _ = preview_mgmt
    existing = {"keyName": "existing", "rights": "DeviceConnect"}
    client.iot_hub_resource.list_keys.return_value = [existing]
    assert custom.iot_hub_policy_create(cmd, client, "hub", "new", permissions + permissions, "rg") is (
        client.iot_hub_resource.begin_create_or_update.return_value
    )
    policies = hub["properties"]["authorizationPolicies"]
    assert policies[0] == existing
    assert policies[1]["keyName"] == "new"
    assert {right.lower() for right in policies[1]["rights"].split(", ")} == set(permissions)
    client.iot_hub_resource.begin_create_or_update.assert_called_once_with(
        resource_group_name="rg", resource_name="hub", iot_hub_description=custom._hub_description_for_write(hub),
        **custom.hub_etag_arguments(hub),
    )


@pytest.mark.parametrize("action", ["create", "delete", "renew"])
def test_policy_conflicts_do_not_write(preview_mgmt, action):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.list_keys.return_value = [{"keyName": "OWNER"}] if action == "create" else []
    with pytest.raises(CLIError, match="already existed|not found"):
        if action == "create":
            custom.iot_hub_policy_create(cmd, client, "hub", "owner", ["registryread"], "rg")
        elif action == "delete":
            custom.iot_hub_policy_delete(cmd, client, "hub", "owner", "rg")
        else:
            custom.iot_hub_policy_key_renew(cmd, client, "hub", "owner", "primary", "rg")
    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_policy_delete_is_case_insensitive(preview_mgmt):
    cmd, client, hub, _, _ = preview_mgmt
    keep = {"keyName": "keep"}
    client.iot_hub_resource.list_keys.return_value = [keep, {"keyName": "OWNER"}]
    assert custom.iot_hub_policy_delete(cmd, client, "hub", "owner", "rg") is (
        client.iot_hub_resource.begin_create_or_update.return_value
    )
    assert hub["properties"]["authorizationPolicies"] == [keep]


@pytest.mark.parametrize("renew,keys", [("primary", (None, "s")), ("secondary", ("p", None)), ("swap", ("s", "p"))])
@pytest.mark.parametrize("no_wait", [False, True])
def test_policy_key_renew(preview_mgmt, renew, keys, no_wait):
    cmd, client, hub, _, wait = preview_mgmt
    keep = {"keyName": "keep"}
    client.iot_hub_resource.list_keys.return_value = [
        keep, {"keyName": "OWNER", "rights": "DeviceConnect", "primaryKey": "p", "secondaryKey": "s"}
    ]
    result = custom.iot_hub_policy_key_renew(cmd, client, "hub", "owner", renew, "rg", no_wait=no_wait)
    assert hub["properties"]["authorizationPolicies"] == [
        keep, {"keyName": "OWNER", "rights": "DeviceConnect", "primaryKey": keys[0], "secondaryKey": keys[1]}
    ]
    if no_wait:
        assert result is client.iot_hub_resource.begin_create_or_update.return_value
        wait.assert_not_called()
    else:
        assert result is client.iot_hub_resource.get_keys_for_key_name.return_value
        wait.assert_called_once_with(client.iot_hub_resource.begin_create_or_update.return_value)


@pytest.mark.parametrize("no_wait", [False, True])
def test_manual_failover_selects_secondary(preview_mgmt, no_wait):
    cmd, client, hub, _, wait = preview_mgmt
    result = custom.iot_hub_manual_failover(cmd, client, "hub", no_wait=no_wait)
    client.iot_hub.begin_manual_failover.assert_called_once_with(
        iot_hub_name="hub", resource_group_name="rg", failover_input={"failoverRegion": "eastus"}
    )
    if no_wait:
        assert result is client.iot_hub.begin_manual_failover.return_value
        wait.assert_not_called()
    else:
        assert result is hub
        wait.assert_called_once_with(client.iot_hub.begin_manual_failover.return_value)


def test_hub_update_preserves_preview_defaults_and_explicit_false(preview_mgmt):
    _, _, hub, _, _ = preview_mgmt
    original = deepcopy(hub)
    assert custom.update_iot_hub_custom(hub) is hub
    assert hub == original
    result = custom.update_iot_hub_custom(
        hub, tags={}, sku="S2", unit=2, retention_day=3, c2d_ttl=2, c2d_max_delivery_count=4,
        feedback_lock_duration=6, feedback_ttl=7, feedback_max_delivery_count=8,
        enable_fileupload_notifications=False, fileupload_notification_lock_duration=9,
        fileupload_notification_max_delivery_count=10, fileupload_notification_ttl=11,
        disable_local_auth=False, disable_device_sas=True, disable_module_sas=False, min_tls_version="1.2",
    )
    assert result["tags"] == {}
    assert result["sku"] == {"name": "S2", "capacity": 2, "tier": "Standard"}
    props = result["properties"]
    assert props["cloudToDevice"] == {
        "defaultTtlAsIso8601": timedelta(hours=2), "maxDeliveryCount": 4,
        "feedback": {"lockDurationAsIso8601": timedelta(seconds=6), "ttlAsIso8601": timedelta(hours=7),
                     "maxDeliveryCount": 8},
    }
    assert props["messagingEndpoints"]["fileNotifications"] == {
        "lockDurationAsIso8601": timedelta(seconds=9), "maxDeliveryCount": 10, "ttlAsIso8601": timedelta(hours=11)
    }
    assert props["eventHubEndpoints"]["events"]["retentionTimeInDays"] == 3
    assert props["disableLocalAuth"] is False
    assert props["disableDeviceSAS"] is True
    assert props["disableModuleSAS"] is False
    assert props["enableFileUploadNotifications"] is False
    assert props["minTlsVersion"] == "1.2"
    assert props["routing"] == original["properties"]["routing"]


@pytest.mark.parametrize("auth,identity", [("identityBased", "/identities/user"), ("keyBased", None), ("", None)])
def test_fileupload_update_contract(preview_mgmt, auth, identity):
    _, _, hub, _, _ = preview_mgmt
    hub["identity"] = {"type": "SystemAssigned, UserAssigned"}
    storage = custom.update_iot_hub_custom(
        hub, fileupload_storage_connectionstring="new-cs", fileupload_storage_container_name="uploads",
        fileupload_sas_ttl=2, fileupload_storage_authentication_type=auth,
        fileupload_storage_container_uri="https://storage.test/uploads", fileupload_storage_identity=identity,
    )["properties"]["storageEndpoints"]["$default"]
    assert storage["connectionString"] == "new-cs"
    assert storage["containerName"] == "uploads"
    assert storage["sasTtlAsIso8601"] == timedelta(hours=2)
    assert storage["authenticationType"] == (auth or None)
    if identity:
        assert storage["identity"] == {"userAssignedIdentity": identity}
        assert storage["containerUri"] == "https://storage.test/uploads"
    elif auth == "keyBased":
        assert storage["identity"] is None
    else:
        assert storage["containerUri"] is None


@pytest.mark.parametrize("recreate", [False, True])
def test_fileupload_missing_default_endpoint(preview_mgmt, recreate):
    _, _, hub, _, _ = preview_mgmt
    hub["properties"]["storageEndpoints"] = {}
    if not recreate:
        with pytest.raises(UnclassifiedUserFault, match="no default storage endpoint"):
            custom.update_iot_hub_custom(hub, fileupload_sas_ttl=2)
    else:
        custom.update_iot_hub_custom(
            hub, fileupload_storage_connectionstring="cs", fileupload_storage_container_name="uploads"
        )
        assert hub["properties"]["storageEndpoints"] == {
            "$default": {"connectionString": "cs", "containerName": "uploads"}
        }


@pytest.mark.parametrize("identity_type,storage_identity,message", [
    (None, None, "no identity"), ("None", None, "no identity"),
    ("UserAssigned", "[system]", "System managed identity"),
    ("SystemAssigned", "/identities/user", "must be added"),
])
def test_fileupload_identity_rejections(preview_mgmt, identity_type, storage_identity, message):
    _, _, hub, _, _ = preview_mgmt
    hub["identity"] = {"type": identity_type}
    with pytest.raises(ArgumentUsageError, match=message):
        custom.update_iot_hub_custom(
            hub, fileupload_storage_authentication_type="identityBased", fileupload_storage_identity=storage_identity
        )


@pytest.mark.parametrize("arguments,message", [
    ({"fileupload_storage_connectionstring": "cs"}, "container name"),
    ({"fileupload_storage_container_name": "uploads"}, "connection string"),
    ({"fileupload_storage_authentication_type": "keyBased", "fileupload_storage_identity": "[system]"}, "IdentityBased"),
])
def test_fileupload_update_incomplete_arguments(preview_mgmt, arguments, message):
    _, _, hub, _, _ = preview_mgmt
    with pytest.raises((RequiredArgumentMissingError, ArgumentUsageError), match=message):
        custom.update_iot_hub_custom(hub, **arguments)


@pytest.mark.parametrize("arguments,message", [
    ({"enable_fileupload_notifications": True}, "storage endpoint"),
    ({"fileupload_storage_connectionstring": "cs"}, "container name"),
    ({"fileupload_storage_container_name": "uploads"}, "connection string"),
    ({"fileupload_storage_identity": "/identities/user"}, "IdentityBased"),
    ({"fileupload_storage_authentication_type": "identityBased"}, "System managed identity"),
    ({"fileupload_storage_authentication_type": "identityBased", "fileupload_storage_identity": "/identities/user"},
     "User identity"),
    ({"identity_role": "Reader"}, "scope"),
    ({"identity_scopes": ["/scope"]}, "role"),
    ({"location": "QatarCentral"}, "Data Residency"),
])
def test_hub_create_validation_precedes_write(preview_mgmt, arguments, message):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": True}
    with pytest.raises((RequiredArgumentMissingError, ArgumentUsageError, InvalidArgumentValueError), match=message):
        custom.iot_hub_create(cmd, client, "hub", "rg", **arguments)
    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_default_put_contract(preview_mgmt):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": True}
    result = custom.iot_hub_create(cmd, client, "hub", "rg")
    assert result is client.iot_hub_resource.begin_create_or_update.return_value
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]
    assert body["location"] == "westus"
    assert body["sku"] == {"name": "S1", "capacity": 1}
    assert "identity" not in body
    assert body["properties"]["eventHubEndpoints"] == {"events": {"retentionTimeInDays": 1, "partitionCount": 4}}
    assert body["properties"]["storageEndpoints"]["$default"] == {
        "sasTtlAsIso8601": timedelta(hours=1), "connectionString": "", "containerName": "",
    }
    assert body["properties"]["enableFileUploadNotifications"] is False
    assert body["properties"]["disableLocalAuth"] is True


@pytest.mark.parametrize("disable_local_auth", [True, False])
def test_hub_create_honors_explicit_local_auth(preview_mgmt, disable_local_auth):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": True}
    custom.iot_hub_create(cmd, client, "hub", "rg", disable_local_auth=disable_local_auth)
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]
    assert body["properties"]["disableLocalAuth"] is disable_local_auth


@pytest.mark.parametrize("disable_local_auth", [True, False, None])
def test_hub_create_preserves_existing_local_auth(preview_mgmt, disable_local_auth):
    cmd, client, hub, _, _ = preview_mgmt
    if disable_local_auth is not None:
        hub["properties"]["disableLocalAuth"] = disable_local_auth
    custom.iot_hub_create(cmd, client, "hub", "rg")
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]
    assert body["properties"].get("disableLocalAuth") is disable_local_auth


@pytest.mark.parametrize("status", [404, 403])
def test_hub_create_existing_lookup_errors(preview_mgmt, status):
    cmd, client, _, _, _ = preview_mgmt
    error = HttpResponseError(message="lookup failed")
    error.status_code = status
    client.iot_hub_resource.get.side_effect = error
    if status == 404:
        assert custom.iot_hub_create(cmd, client, "hub", "rg") is (
            client.iot_hub_resource.begin_create_or_update.return_value
        )
    else:
        with pytest.raises(HttpResponseError) as raised:
            custom.iot_hub_create(cmd, client, "hub", "rg")
        assert raised.value is error
        client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_assigns_roles_after_completion(mocker, preview_mgmt):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": True}
    assignment = mocker.patch.object(custom, "create_role_assignment")
    poller = custom.iot_hub_create(
        cmd, client, "hub", "rg", system_identity=True, identity_role="Reader", identity_scopes=["/one", "/two"]
    )
    assignment.assert_not_called()
    poller.resource.return_value = {"identity": {"principalId": "principal"}}
    callback = poller.add_done_callback.call_args.args[0]
    callback(poller)
    assert assignment.call_count == 2
    for call, scope in zip(assignment.call_args_list, ["/one", "/two"]):
        context, principal = call.args
        assert context is cmd.cli_ctx
        assert principal == "principal"
        assert call.kwargs == {"identity_role": "Reader", "identity_scope": scope}
    error = HttpResponseError(message="creation failed")
    poller.resource.side_effect = error
    with pytest.raises(HttpResponseError) as raised:
        callback(poller)
    assert raised.value is error


def test_hub_identity_show_and_scoped_assignment(mocker, preview_mgmt):
    cmd, client, hub, _, wait = preview_mgmt
    assert custom.iot_hub_identity_show(cmd, client, "hub") == hub["identity"]
    hub["identity"]["principalId"] = "principal"
    wait.return_value = hub
    assignment = mocker.patch.object(custom, "create_role_assignment")
    assert custom.iot_hub_identity_assign(
        cmd, client, "hub", system_identity=True, identity_role="Reader", identity_scopes=["/one", "/two"]
    ) == hub["identity"]
    assert [call.kwargs["identity_scope"] for call in assignment.call_args_list] == ["/one", "/two"]
    assert all(call.kwargs["identity_role"] == "Reader" for call in assignment.call_args_list)


def test_build_identity_explicitly_disables_identity():
    assert custom._build_identity() == {"type": "None"}


@pytest.mark.parametrize("is_update,edge_enabled", [(False, True), (True, True), (False, False)])
def test_device_scope_is_parent_only_when_creating_edge_device(is_update, edge_enabled):
    from azext_iot.operations.hub import _assemble_device

    device = _assemble_device(
        is_update=is_update, device_id="device", auth_method="sas", edge_enabled=edge_enabled,
        pk="primary", sk="secondary", device_scope="scope",
    )
    assert device.device_id == "device"
    assert device.capabilities.iot_edge is edge_enabled
    assert device.authentication.symmetric_key.primary_key == "primary"
    assert device.authentication.symmetric_key.secondary_key == "secondary"
    if edge_enabled and not is_update:
        assert device.parent_scopes == ["scope"]
        assert device.device_scope is None
    else:
        assert device.device_scope == "scope"
        assert device.parent_scopes is None
