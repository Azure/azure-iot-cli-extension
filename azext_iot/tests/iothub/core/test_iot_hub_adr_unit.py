# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, RequiredArgumentMissingError
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError

from azext_iot.core.custom import (
    _hub_description_for_write,
    _protect_hub_link_identity,
    _sanitize_arm_identity,
    iot_hub_create,
    iot_hub_identity_assign,
    iot_hub_identity_remove,
    iot_hub_update,
    update_iot_hub_custom,
)
from azext_iot.core.shared import IotHubSku


@pytest.fixture(autouse=True)
def authoritative_target(mocker):
    # These existing guard tests supply the authoritative response directly.
    # The target GET's transport and fail-closed contracts are tested separately.
    mocker.patch(
        "azext_iot.core.custom._adr_identity_target",
        side_effect=lambda cmd, resource, kind: resource,
    )


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


def test_hub_create_rethrows_existing_lookup_error():
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": False}
    error = HttpResponseError(message="service unavailable")
    error.status_code = 503
    client.iot_hub_resource.get.side_effect = error

    with pytest.raises(HttpResponseError, match="service unavailable"):
        iot_hub_create(MagicMock(), client, "hub", "rg")

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_hub_create_treats_disappearing_name_as_new(mocker):
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": False}
    error = HttpResponseError(message="not found")
    error.status_code = 404
    client.iot_hub_resource.get.side_effect = error
    mocker.patch("azext_iot.core.custom._ensure_location", return_value="centraluseuap")

    iot_hub_create(MagicMock(), client, "hub", "rg")

    assert client.iot_hub_resource.begin_create_or_update.called


def test_identity_assign_initializes_and_merges_identity(mocker):
    hub = {
        "location": "centraluseuap", "etag": "etag", "sku": {"name": "S1"},
        "identity": None, "properties": {},
    }
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {"identity": {"type": "SystemAssigned, UserAssigned"}}
    client = MagicMock()
    uami = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
    )
    result = iot_hub_identity_assign(
        MagicMock(), client, "hub", system_identity=True,
        user_identities=[uami, uami.upper()], resource_group_name="rg",
    )

    assert result["type"] == "SystemAssigned, UserAssigned"
    identity = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]["identity"]
    assert identity == {
        "type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {uami: {}},
    }


def test_identity_assign_user_only_and_argument_errors(mocker):
    hub = {
        "location": "centraluseuap", "etag": "etag", "sku": {"name": "S1"},
        "identity": None, "properties": {},
    }
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {"identity": {"type": "UserAssigned"}}
    client = MagicMock()
    uami = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
    )
    assert iot_hub_identity_assign(
        MagicMock(), client, "hub", user_identities=[uami], resource_group_name="rg",
    ) == {"type": "UserAssigned"}
    assert client.iot_hub_resource.begin_create_or_update.call_args.kwargs[
        "iot_hub_description"
    ]["identity"]["type"] == "UserAssigned"

    with pytest.raises(RequiredArgumentMissingError, match="No identities"):
        iot_hub_identity_assign(MagicMock(), client, "hub", resource_group_name="rg")
    with pytest.raises(RequiredArgumentMissingError, match="scope"):
        iot_hub_identity_assign(
            MagicMock(), client, "hub", system_identity=True,
            identity_role="Contributor", resource_group_name="rg",
        )


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


def test_identity_remove_preserves_active_selected_identity_and_omits_projection(mocker):
    hub = _hub()
    other_uami = next(iter(hub["identity"]["userAssignedIdentities"]))
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {"identity": {"type": "SystemAssigned"}}
    client = MagicMock()

    result = iot_hub_identity_remove(
        MagicMock(), client, "hub", user_identities=[other_uami.upper()],
        resource_group_name="rg",
    )

    assert result == {"type": "SystemAssigned"}
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]
    assert body["identity"]["type"] == "SystemAssigned"
    assert "deviceRegistry" not in body["properties"]


def test_identity_remove_system_validation_and_uami_preservation(mocker):
    client = MagicMock()
    no_system = _hub(link_state="Failed")
    no_system["identity"] = {"type": "UserAssigned"}
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=no_system)
    with pytest.raises(ArgumentUsageError, match="not currently using"):
        iot_hub_identity_remove(
            MagicMock(), client, "hub", system_identity=True, resource_group_name="rg",
        )

    uami = next(iter(_hub()["identity"]["userAssignedIdentities"]))
    with_system = _hub(link_state="Failed")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=with_system)
    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {uami: {}}},
    }
    result = iot_hub_identity_remove(
        MagicMock(), client, "hub", system_identity=True, resource_group_name="rg",
    )
    assert result["type"] == "UserAssigned"


def test_identity_remove_argument_missing_unknown_and_all_uamis(mocker):
    client = MagicMock()
    hub = _hub(link_state="Failed")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub)

    with pytest.raises(RequiredArgumentMissingError, match="No identities"):
        iot_hub_identity_remove(MagicMock(), client, "hub", resource_group_name="rg")
    with pytest.raises(ArgumentUsageError, match="not currently using"):
        iot_hub_identity_remove(
            MagicMock(), client, "hub", user_identities=["/identities/missing"],
            resource_group_name="rg",
        )

    lro = mocker.patch("azext_iot.core.custom.LongRunningOperation")
    lro.return_value.return_value = {"identity": {"type": "SystemAssigned"}}
    result = iot_hub_identity_remove(
        MagicMock(), client, "hub", user_identities=[], resource_group_name="rg",
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
    [{"type": "UserAssigned", "userAssignedIdentities": {}}, None],
)
def test_generic_update_blocks_active_sami_removal(desired_identity):
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


@pytest.mark.parametrize(
    "identity_kwargs, identity_type, uami",
    [
        ({"system_identity": False}, "SystemAssigned", None),
        (
            {"user_identities": [
                "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/replacement"
            ]},
            "UserAssigned",
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/selected",
        ),
    ],
)
def test_hub_create_upsert_blocks_active_identity_replacement(identity_kwargs, identity_type, uami):
    current = _hub(identity_type=identity_type, uami=uami)
    client = MagicMock()
    client.iot_hub_resource.check_name_availability.return_value = {"nameAvailable": False}
    client.iot_hub_resource.get.return_value = current

    with pytest.raises(ArgumentUsageError, match="active ADR link"):
        iot_hub_create(
            cmd=MagicMock(), client=client, hub_name="hub",
            resource_group_name="rg", **identity_kwargs,
        )

    client.iot_hub_resource.begin_create_or_update.assert_not_called()
