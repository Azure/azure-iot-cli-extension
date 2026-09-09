# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, CLIInternalError
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError
from azure.core import MatchConditions

from azext_iot.core.custom import (
    _drop_none_create_values,
    _get_resource_group_from_hub,
    _hub_description_for_write,
    _protect_hub_link_identity,
    _sanitize_arm_identity,
    iot_hub_create,
    iot_hub_identity_assign,
    iot_hub_identity_remove,
    iot_hub_policy_create,
    iot_hub_policy_delete,
    iot_hub_policy_key_renew,
    iot_hub_route_create,
    iot_hub_route_delete,
    iot_hub_route_update,
    iot_hub_routing_endpoint_create,
    iot_hub_routing_endpoint_delete,
    iot_hub_update,
    iot_message_enrichment_create,
    iot_message_enrichment_delete,
    iot_message_enrichment_update,
    update_iot_hub_custom,
)
from azext_iot.core.shared import AuthenticationType, IotHubSku


def _hub(link_state="Success", identity_type="SystemAssigned", uami=None):
    selected_identity = {"type": identity_type}
    if uami:
        selected_identity["userAssignedIdentity"] = uami
    return {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub",
        "location": "centraluseuap",
        "etag": "etag",
        "sku": {"name": "S1", "capacity": 1},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "hub-principal",
            "tenantId": "tenant",
            "userAssignedIdentities": {
                uami or "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/other": {
                    "principalId": "uami-principal",
                    "clientId": "client",
                }
            },
        },
        "properties": {
            "eventHubEndpoints": {
                "events": {"retentionTimeInDays": 1, "partitionCount": 4}
            },
            "cloudToDevice": {
                "defaultTtlAsIso8601": "1:00:00",
                "maxDeliveryCount": 10,
                "feedback": {
                    "lockDurationAsIso8601": "0:00:05",
                    "ttlAsIso8601": "1:00:00",
                    "maxDeliveryCount": 10,
                },
            },
            "messagingEndpoints": {"fileNotifications": {}},
            "storageEndpoints": {"$default": {}},
            "deviceRegistry": {
                "namespaceResourceId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns",
                "identity": selected_identity,
                "linkingProperties": {"state": link_state},
            },
            "provisioningState": "Succeeded",
            "hostName": "hub.azure-devices.net",
        },
    }


def test_gen2_is_not_a_supported_cli_sku():
    assert "GEN2" not in {item.value for item in IotHubSku}


def test_modeless_create_cleaner_and_resource_group_fallbacks():
    assert _drop_none_create_values(
        {"items": [{"value": 1, "unset": None}], "unset": None}
    ) == {"items": [{"value": 1}]}
    assert _get_resource_group_from_hub({}, fallback="direct") == "direct"
    assert _get_resource_group_from_hub(
        {
            "id": (
                "/subscriptions/sub/resourceGroups/from-id/providers/"
                "Microsoft.Devices/IotHubs/hub"
            )
        }
    ) == "from-id"
    with pytest.raises(CLIInternalError, match="resource group"):
        _get_resource_group_from_hub({})


def test_standard_hub_create_has_no_resource_side_namespace_state(mocker):
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )
    cmd = MagicMock()
    client = MagicMock()
    poller = client.iot_hub_resource.begin_create_or_update.return_value

    result = iot_hub_create(
        cmd=cmd,
        client=client,
        hub_name="hub",
        resource_group_name="rg",
        sku="S1",
    )

    assert result is poller
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]
    assert body["sku"]["name"] == "S1"
    assert "deviceRegistry" not in body["properties"]
    poller.add_done_callback.assert_not_called()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"enable_fileupload_notifications": True},
            "storage endpoint",
        ),
        (
            {"fileupload_storage_connectionstring": "connection-string"},
            "container name",
        ),
        (
            {"fileupload_storage_container_name": "container"},
            "connection string",
        ),
        (
            {
                "fileupload_storage_identity": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/uami"
                )
            },
            "file upload storage authentication",
        ),
        (
            {
                "system_identity": True,
                "identity_role": "Contributor",
            },
            "scope",
        ),
    ],
)
def test_hub_create_validates_inputs_before_put(kwargs, message):
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }

    with pytest.raises(RequiredArgumentMissingError, match=message):
        iot_hub_create(
            MagicMock(), client, "hub", "rg", **kwargs
        )

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_rethrows_existing_lookup_error():
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": False
    }
    error = HttpResponseError(message="service unavailable")
    error.status_code = 503
    client.iot_hub_resource.get.side_effect = error

    with pytest.raises(HttpResponseError, match="service unavailable"):
        iot_hub_create(MagicMock(), client, "hub", "rg")

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_treats_disappearing_name_as_new(mocker):
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": False
    }
    error = HttpResponseError(message="not found")
    error.status_code = 404
    client.iot_hub_resource.get.side_effect = error
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )

    iot_hub_create(MagicMock(), client, "hub", "rg")

    assert client.iot_hub_resource.begin_create_or_update.called


def test_hub_create_qatar_requires_data_residency(mocker):
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="qatarcentral",
    )

    with pytest.raises(InvalidArgumentValueError, match="Data Residency"):
        iot_hub_create(MagicMock(), client, "hub", "rg")


def test_hub_create_upsert_applies_every_explicit_writable_option():
    selected = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/selected"
    )
    current = _routing_hub()
    current["identity"]["userAssignedIdentities"] = {
        selected: {"principalId": "server-owned"}
    }
    current["properties"]["storageEndpoints"]["$default"] = {
        "connectionString": "old",
        "containerName": "old",
    }
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": False
    }
    client.iot_hub_resource.get.return_value = current

    iot_hub_create(
        MagicMock(),
        client,
        "hub",
        "rg",
        location="centraluseuap",
        sku="S2",
        unit=2,
        partition_count=8,
        retention_day=2,
        c2d_ttl=2,
        c2d_max_delivery_count=20,
        disable_local_auth=True,
        disable_device_sas=True,
        disable_module_sas=True,
        enable_data_residency=True,
        feedback_lock_duration=10,
        feedback_ttl=2,
        feedback_max_delivery_count=20,
        enable_fileupload_notifications=True,
        fileupload_notification_lock_duration=10,
        fileupload_notification_max_delivery_count=20,
        fileupload_notification_ttl=2,
        fileupload_storage_connectionstring="new-connection-string",
        fileupload_storage_container_name="new-container",
        fileupload_sas_ttl=2,
        fileupload_storage_authentication_type=(
            AuthenticationType.IdentityBased
        ),
        fileupload_storage_identity=selected,
        min_tls_version="1.2",
        tags={"phase": "upsert"},
    )

    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]
    assert body["sku"] == {"name": "S2", "capacity": 2}
    assert body["tags"] == {"phase": "upsert"}
    properties = body["properties"]
    assert properties["eventHubEndpoints"]["events"] == {
        "retentionTimeInDays": 2,
        "partitionCount": 8,
    }
    cloud_to_device = properties["cloudToDevice"]
    assert str(cloud_to_device["defaultTtlAsIso8601"]) == "2:00:00"
    assert cloud_to_device["maxDeliveryCount"] == 20
    assert str(
        cloud_to_device["feedback"]["lockDurationAsIso8601"]
    ) == "0:00:10"
    assert str(cloud_to_device["feedback"]["ttlAsIso8601"]) == "2:00:00"
    assert cloud_to_device["feedback"]["maxDeliveryCount"] == 20
    notifications = properties["messagingEndpoints"]["fileNotifications"]
    assert str(notifications["lockDurationAsIso8601"]) == "0:00:10"
    assert str(notifications["ttlAsIso8601"]) == "2:00:00"
    assert notifications["maxDeliveryCount"] == 20
    storage = properties["storageEndpoints"]["$default"]
    assert storage["connectionString"] == "new-connection-string"
    assert storage["containerName"] == "new-container"
    assert str(storage["sasTtlAsIso8601"]) == "2:00:00"
    assert storage["authenticationType"] == AuthenticationType.IdentityBased
    assert storage["identity"] == {"userAssignedIdentity": selected}
    for name in (
        "disableLocalAuth",
        "disableDeviceSAS",
        "disableModuleSAS",
        "enableDataResidency",
        "enableFileUploadNotifications",
    ):
        assert properties[name] is True
    assert properties["minTlsVersion"] == "1.2"


@pytest.mark.parametrize(
    "fileupload_identity, expected_option",
    [
        (None, "--system-assigned-mi"),
        (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/uami",
            "--user-assigned-mi",
        ),
    ],
)
def test_hub_create_identity_file_upload_errors_use_canonical_options(
    fileupload_identity, expected_option
):
    with pytest.raises(ArgumentUsageError, match=expected_option):
        iot_hub_create(
            cmd=MagicMock(),
            client=MagicMock(),
            hub_name="hub",
            resource_group_name="rg",
            fileupload_storage_authentication_type=(
                AuthenticationType.IdentityBased
            ),
            fileupload_storage_identity=fileupload_identity,
        )


def test_generic_update_keeps_projection_for_final_identity_guard():
    instance = _hub()
    original_projection = instance["properties"]["deviceRegistry"].copy()

    result = update_iot_hub_custom(instance, tags={"env": "test"}, unit=2)

    assert result["tags"] == {"env": "test"}
    assert result["sku"]["capacity"] == 2
    assert result["properties"]["deviceRegistry"] == original_projection
    assert original_projection["namespaceResourceId"].endswith("/namespaces/ns")


def test_hub_put_strips_server_state_and_uses_etag_match_condition():
    client = MagicMock()
    parameters = _hub()
    client.iot_hub_resource.get.return_value = deepcopy(parameters)

    iot_hub_update(client, "hub", parameters, "rg")

    kwargs = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert kwargs["match_condition"] == MatchConditions.IfNotModified
    assert kwargs["etag"] == "etag"
    assert "deviceRegistry" not in kwargs["iot_hub_description"]["properties"]
    assert "hostName" not in kwargs["iot_hub_description"]["properties"]
    assert parameters["properties"]["deviceRegistry"]


def _routing_hub():
    hub = _hub()
    hub["properties"]["routing"] = {
        "endpoints": {
            "eventHubs": [],
            "serviceBusQueues": [],
            "serviceBusTopics": [],
            "storageContainers": [],
        },
        "routes": [],
        "enrichments": [],
    }
    return hub


def _assert_if_not_modified(client):
    kwargs = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert kwargs["etag"] == "etag"
    assert kwargs["match_condition"] == MatchConditions.IfNotModified


def test_policy_read_modify_write_uses_etag_match_condition(mocker):
    client = MagicMock()
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get", return_value=_routing_hub()
    )
    mocker.patch(
        "azext_iot.core.custom.iot_hub_policy_list", return_value=[]
    )

    iot_hub_policy_create(
        MagicMock(),
        client,
        "hub",
        "policy",
        ["serviceconnect"],
        resource_group_name="rg",
    )

    _assert_if_not_modified(client)


def test_route_read_modify_write_uses_etag_match_condition(mocker):
    client = MagicMock()
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get", return_value=_routing_hub()
    )

    iot_hub_route_create(
        MagicMock(),
        client,
        "hub",
        "route",
        "DeviceMessages",
        "events",
        resource_group_name="rg",
    )

    _assert_if_not_modified(client)


def test_enrichment_read_modify_write_uses_etag_match_condition(mocker):
    client = MagicMock()
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get", return_value=_routing_hub()
    )

    iot_message_enrichment_create(
        MagicMock(),
        client,
        "hub",
        "tenant",
        "$twin.tags.tenant",
        ["events"],
        resource_group_name="rg",
    )

    _assert_if_not_modified(client)


def test_every_remaining_hub_read_modify_write_uses_match_condition(mocker):
    hub = _routing_hub()
    hub["properties"]["routing"]["routes"] = [
        {
            "name": "route",
            "source": "DeviceMessages",
            "endpointNames": ["events"],
            "condition": "true",
            "isEnabled": True,
        }
    ]
    hub["properties"]["routing"]["enrichments"] = [
        {
            "key": "tenant",
            "value": "$twin.tags.tenant",
            "endpointNames": ["events"],
        }
    ]
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get",
        side_effect=lambda *_args, **_kwargs: deepcopy(hub),
    )
    mocker.patch(
        "azext_iot.core.custom.iot_hub_policy_list",
        return_value=[
            {
                "keyName": "policy",
                "rights": "ServiceConnect",
                "primaryKey": "primary",
                "secondaryKey": "secondary",
            }
        ],
    )
    mocker.patch("azext_iot.core.custom.LongRunningOperation")
    client = MagicMock()
    cmd = MagicMock()

    iot_hub_policy_delete(cmd, client, "hub", "policy", "rg")
    iot_hub_policy_key_renew(
        cmd, client, "hub", "policy", "primary", "rg", no_wait=True
    )
    iot_hub_policy_key_renew(
        cmd, client, "hub", "policy", "secondary", "rg"
    )
    iot_hub_routing_endpoint_create(
        cmd,
        client,
        "hub",
        "endpoint",
        "eventhub",
        "rg",
        "sub",
        connection_string="Endpoint=sb://example/",
        resource_group_name="rg",
    )
    iot_hub_routing_endpoint_delete(
        cmd, client, "hub", resource_group_name="rg"
    )
    iot_hub_route_delete(
        cmd, client, "hub", route_name="route", resource_group_name="rg"
    )
    iot_hub_route_update(
        cmd,
        client,
        "hub",
        "route",
        condition="false",
        resource_group_name="rg",
    )
    iot_message_enrichment_update(
        cmd,
        client,
        "hub",
        "tenant",
        "$twin.tags.site",
        ["events"],
        "rg",
    )
    iot_message_enrichment_delete(
        cmd, client, "hub", "tenant", resource_group_name="rg"
    )

    calls = client.iot_hub_resource.begin_create_or_update.call_args_list
    assert len(calls) == 9
    assert all(
        call.kwargs["match_condition"]
        == MatchConditions.IfNotModified
        for call in calls
    )


def test_hub_write_identity_merge_keeps_only_writable_fields():
    body = _hub_description_for_write(_hub())

    assert body["identity"] == {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/other": {}
        },
    }
    assert "id" not in body
    assert "provisioningState" not in body["properties"]


def test_active_link_blocks_selected_system_identity_removal():
    with pytest.raises(
        ArgumentUsageError,
        match="link hub update --user-assigned-mi",
    ):
        _protect_hub_link_identity(
            _hub(), remove_system=True, remove_user_identities=None
        )


def test_active_link_blocks_selected_uami_removal_case_insensitively():
    uami = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/selected"
    hub = _hub(identity_type="UserAssigned", uami=uami)

    with pytest.raises(ArgumentUsageError, match="selected Hub"):
        _protect_hub_link_identity(
            hub,
            remove_system=False,
            remove_user_identities=[uami.upper()],
        )


def test_failed_or_unlinked_projection_does_not_block_identity_removal():
    failed = _hub(link_state="Failed")
    _protect_hub_link_identity(
        failed, remove_system=True, remove_user_identities=[]
    )
    failed["properties"]["deviceRegistry"].pop("namespaceResourceId")
    _protect_hub_link_identity(
        failed, remove_system=True, remove_user_identities=[]
    )


def test_identity_remove_preserves_active_selected_identity_and_omits_projection(
    mocker,
):
    hub = _hub()
    other_uami = next(iter(hub["identity"]["userAssignedIdentities"]))
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "SystemAssigned"}
    }
    client = MagicMock()

    result = iot_hub_identity_remove(
        MagicMock(),
        client,
        "hub",
        user_identities=[other_uami.upper()],
        resource_group_name="rg",
    )

    assert result == {"type": "SystemAssigned"}
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]
    assert body["identity"]["type"] == "SystemAssigned"
    assert "deviceRegistry" not in body["properties"]


def test_identity_assign_initializes_and_merges_identity(mocker):
    hub = {
        "location": "centraluseuap",
        "etag": "etag",
        "sku": {"name": "S1"},
        "identity": None,
        "properties": {},
    }
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "SystemAssigned, UserAssigned"}
    }
    client = MagicMock()
    uami = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
    )

    result = iot_hub_identity_assign(
        MagicMock(),
        client,
        "hub",
        system_identity=True,
        user_identities=[uami, uami.upper()],
        resource_group_name="rg",
    )

    assert result["type"] == "SystemAssigned, UserAssigned"
    identity = client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]["identity"]
    assert identity == {
        "type": "SystemAssigned, UserAssigned",
        "userAssignedIdentities": {uami: {}},
    }


def test_identity_assign_user_only_and_argument_errors(mocker):
    hub = {
        "location": "centraluseuap",
        "etag": "etag",
        "sku": {"name": "S1"},
        "identity": None,
        "properties": {},
    }
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "UserAssigned"}
    }
    client = MagicMock()
    uami = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
    )

    assert iot_hub_identity_assign(
        MagicMock(),
        client,
        "hub",
        user_identities=[uami],
        resource_group_name="rg",
    ) == {"type": "UserAssigned"}
    assert client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]["identity"]["type"] == "UserAssigned"

    with pytest.raises(RequiredArgumentMissingError, match="No identities"):
        iot_hub_identity_assign(
            MagicMock(), client, "hub", resource_group_name="rg"
        )
    with pytest.raises(RequiredArgumentMissingError, match="scope"):
        iot_hub_identity_assign(
            MagicMock(),
            client,
            "hub",
            system_identity=True,
            identity_role="Contributor",
            resource_group_name="rg",
        )


def test_identity_remove_system_validation_and_uami_preservation(mocker):
    client = MagicMock()
    no_system = _hub(link_state="Failed")
    no_system["identity"] = {"type": "UserAssigned"}
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=no_system)
    with pytest.raises(ArgumentUsageError, match="not currently using"):
        iot_hub_identity_remove(
            MagicMock(),
            client,
            "hub",
            system_identity=True,
            resource_group_name="rg",
        )

    uami = next(iter(_hub()["identity"]["userAssignedIdentities"]))
    with_system = _hub(link_state="Failed")
    mocker.patch(
        "azext_iot.core.custom.iot_hub_get", return_value=with_system
    )
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {uami: {}},
        }
    }
    result = iot_hub_identity_remove(
        MagicMock(),
        client,
        "hub",
        system_identity=True,
        resource_group_name="rg",
    )
    assert result["type"] == "UserAssigned"


def test_identity_remove_argument_missing_unknown_and_all_uamis(mocker):
    client = MagicMock()
    hub = _hub(link_state="Failed")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)

    with pytest.raises(RequiredArgumentMissingError, match="No identities"):
        iot_hub_identity_remove(
            MagicMock(), client, "hub", resource_group_name="rg"
        )
    with pytest.raises(ArgumentUsageError, match="not currently using"):
        iot_hub_identity_remove(
            MagicMock(),
            client,
            "hub",
            user_identities=["/identities/missing"],
            resource_group_name="rg",
        )

    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "SystemAssigned"}
    }
    result = iot_hub_identity_remove(
        MagicMock(),
        client,
        "hub",
        user_identities=[],
        resource_group_name="rg",
    )
    assert result == {"type": "SystemAssigned"}


def test_hub_write_sanitizer_accepts_absent_identity():
    assert _sanitize_arm_identity(None) is None
    assert _hub_description_for_write(
        {"location": "centraluseuap", "sku": {"name": "S1"}, "properties": {}}
    ) == {
        "location": "centraluseuap",
        "sku": {"name": "S1"},
        "properties": {},
    }


@pytest.mark.parametrize(
    "desired_identity",
    [
        {"type": "UserAssigned", "userAssignedIdentities": {}},
        None,
    ],
)
def test_generic_update_blocks_active_sami_removal(
    desired_identity,
):
    client = MagicMock()
    current = _hub(identity_type="SystemAssigned")
    client.iot_hub_resource.get.return_value = current
    desired = deepcopy(current)
    if desired_identity is None:
        desired.pop("identity")
    else:
        desired["identity"] = desired_identity

    with pytest.raises(ArgumentUsageError, match="active ADR link"):
        iot_hub_update(client, "hub", desired, "rg")

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_generic_update_blocks_active_uami_nested_remove():
    selected = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/selected"
    )
    current = _hub(identity_type="UserAssigned", uami=selected)
    desired = deepcopy(current)
    desired["identity"]["userAssignedIdentities"].pop(selected)
    desired["identity"]["type"] = "SystemAssigned"
    client = MagicMock()
    client.iot_hub_resource.get.return_value = current

    with pytest.raises(ArgumentUsageError, match="selected Hub"):
        iot_hub_update(client, "hub", desired, "rg")

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_generic_update_allows_unrelated_set_and_keeps_guard_projection_local():
    current = _hub()
    desired = deepcopy(current)
    desired["tags"] = {"phase": "updated"}
    client = MagicMock()
    client.iot_hub_resource.get.return_value = current

    iot_hub_update(client, "hub", desired, "rg")

    kwargs = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert kwargs["iot_hub_description"]["tags"] == {"phase": "updated"}
    assert "deviceRegistry" not in kwargs["iot_hub_description"]["properties"]
    assert current["properties"]["deviceRegistry"]


def test_hub_create_upsert_preserves_unspecified_state_and_identity(mocker):
    current = _routing_hub()
    current["tags"] = {"existing": "tag"}
    current["sku"]["tier"] = "Standard"
    current["properties"]["eventHubEndpoints"]["events"].update(
        {
            "endpoint": "sb://service-owned/",
            "path": "hub",
            "partitionIds": ["0", "1", "2", "3"],
        }
    )
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": False
    }
    client.iot_hub_resource.get.return_value = current
    ensure_location = mocker.patch(
        "azext_iot.core.custom._ensure_location"
    )

    iot_hub_create(
        cmd=MagicMock(),
        client=client,
        hub_name="hub",
        resource_group_name="rg",
    )

    kwargs = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert kwargs["etag"] == "etag"
    assert kwargs["match_condition"] == MatchConditions.IfNotModified
    body = kwargs["iot_hub_description"]
    assert body["tags"] == {"existing": "tag"}
    assert body["identity"]["type"] == "SystemAssigned,UserAssigned"
    assert body["properties"]["routing"] == current["properties"]["routing"]
    assert "deviceRegistry" not in body["properties"]
    assert body["properties"]["eventHubEndpoints"]["events"] == {
        "retentionTimeInDays": 1,
        "partitionCount": 4,
    }
    ensure_location.assert_not_called()


@pytest.mark.parametrize(
    "identity_kwargs, identity_type, uami",
    [
        ({"system_identity": False}, "SystemAssigned", None),
        (
            {
                "user_identities": [
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/replacement"
                ]
            },
            "UserAssigned",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/selected",
        ),
    ],
)
def test_hub_create_upsert_blocks_active_identity_replacement(
    identity_kwargs, identity_type, uami
):
    current = _hub(identity_type=identity_type, uami=uami)
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": False
    }
    client.iot_hub_resource.get.return_value = current

    with pytest.raises(ArgumentUsageError, match="active ADR link"):
        iot_hub_create(
            cmd=MagicMock(),
            client=client,
            hub_name="hub",
            resource_group_name="rg",
            **identity_kwargs,
        )

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_role_callback_supports_dict_result(mocker):
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )
    role_assignment = mocker.patch(
        "azext_iot.core.custom.create_role_assignment"
    )
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }
    poller = client.iot_hub_resource.begin_create_or_update.return_value

    iot_hub_create(
        cmd=MagicMock(),
        client=client,
        hub_name="hub",
        resource_group_name="rg",
        system_identity=True,
        identity_role="Contributor",
        identity_scopes=["/scope/one", "/scope/two"],
    )
    callback = poller.add_done_callback.call_args.args[0]
    completed = MagicMock()
    completed.resource.return_value = {
        "identity": {"principalId": "principal"}
    }
    callback(completed)

    assert [call.args[1] for call in role_assignment.call_args_list] == [
        "principal",
        "principal",
    ]
    assert [
        call.kwargs["identity_scope"]
        for call in role_assignment.call_args_list
    ] == ["/scope/one", "/scope/two"]


def test_hub_create_role_callback_reports_missing_principal(mocker):
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }
    poller = client.iot_hub_resource.begin_create_or_update.return_value

    iot_hub_create(
        cmd=MagicMock(),
        client=client,
        hub_name="hub",
        resource_group_name="rg",
        system_identity=True,
        identity_role="Contributor",
        identity_scopes=["/scope"],
    )
    callback = poller.add_done_callback.call_args.args[0]
    completed = MagicMock()
    completed.resource.return_value = {"identity": {"type": "SystemAssigned"}}

    with pytest.raises(CLIInternalError, match="principalId"):
        callback(completed)


def test_hub_create_role_callback_propagates_assignment_error(mocker):
    mocker.patch(
        "azext_iot.core.custom._ensure_location",
        return_value="centraluseuap",
    )
    mocker.patch(
        "azext_iot.core.custom.create_role_assignment",
        side_effect=ArgumentUsageError("role denied"),
    )
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }
    poller = client.iot_hub_resource.begin_create_or_update.return_value

    iot_hub_create(
        cmd=MagicMock(),
        client=client,
        hub_name="hub",
        resource_group_name="rg",
        system_identity=True,
        identity_role="Contributor",
        identity_scopes=["/scope"],
    )
    callback = poller.add_done_callback.call_args.args[0]
    completed = MagicMock()
    completed.resource.return_value = {
        "identity": {"principalId": "principal"}
    }

    with pytest.raises(ArgumentUsageError, match="role denied"):
        callback(completed)


def test_hub_create_role_requires_requested_system_identity():
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {
        "nameAvailable": True
    }

    with pytest.raises(ArgumentUsageError, match="--system-assigned-mi"):
        iot_hub_create(
            cmd=MagicMock(),
            client=client,
            hub_name="hub",
            resource_group_name="rg",
            identity_role="Contributor",
            identity_scopes=["/scope"],
        )

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_identity_assign_role_supports_dict_result(mocker):
    current = _hub(link_state="Failed")
    current["identity"]["principalId"] = "before"
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=current)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "after",
        }
    }
    role_assignment = mocker.patch(
        "azext_iot.core.custom.create_role_assignment"
    )

    result = iot_hub_identity_assign(
        MagicMock(),
        MagicMock(),
        "hub",
        user_identities=[
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/new"
        ],
        identity_role="Contributor",
        identity_scopes=["/scope"],
        resource_group_name="rg",
    )

    assert result["principalId"] == "after"
    role_assignment.assert_called_once()
    assert role_assignment.call_args.args[1] == "after"


def test_identity_assign_role_requires_system_identity_before_put(mocker):
    current = _hub(link_state="Failed")
    current["identity"] = {
        "type": "UserAssigned",
        "userAssignedIdentities": {
            next(iter(current["identity"]["userAssignedIdentities"])): {}
        },
    }
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=current)
    client = MagicMock()

    with pytest.raises(ArgumentUsageError, match="--system-assigned"):
        iot_hub_identity_assign(
            MagicMock(),
            client,
            "hub",
            user_identities=[
                "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/new"
            ],
            identity_role="Contributor",
            identity_scopes=["/scope"],
            resource_group_name="rg",
        )

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_identity_assign_role_reports_missing_principal(mocker):
    current = _hub(link_state="Failed")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=current)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "SystemAssigned"}
    }

    with pytest.raises(CLIInternalError, match="principalId"):
        iot_hub_identity_assign(
            MagicMock(),
            MagicMock(),
            "hub",
            system_identity=True,
            identity_role="Contributor",
            identity_scopes=["/scope"],
            resource_group_name="rg",
        )


def test_identity_assign_role_error_is_not_a_dict_shape_failure(mocker):
    current = _hub(link_state="Failed")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=current)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {
            "type": "SystemAssigned",
            "principalId": "principal",
        }
    }
    role_assignment = mocker.patch(
        "azext_iot.core.custom.create_role_assignment",
        side_effect=ArgumentUsageError("role denied"),
    )

    with pytest.raises(ArgumentUsageError, match="role denied"):
        iot_hub_identity_assign(
            MagicMock(),
            MagicMock(),
            "hub",
            system_identity=True,
            identity_role="Contributor",
            identity_scopes=["/scope"],
            resource_group_name="rg",
        )

    role_assignment.assert_called_once()
