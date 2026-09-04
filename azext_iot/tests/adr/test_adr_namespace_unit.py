# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.namespace import (
    NamespaceProvider,
    _build_namespace_identity,
    _clean_migrate_resource_ids,
    _managed_identity_type,
)


UAMI_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
)


def _namespace_not_found():
    error = HttpResponseError(message="Namespace not found")
    error.status_code = 404
    return error


def test_namespace_provider_surfaces_exclude_raw_endpoint_parameters():
    removed = {
        "messaging_endpoints",
        "provisioning_endpoints",
        "updating_endpoints",
    }

    for operation in (NamespaceProvider.create, NamespaceProvider.update):
        assert removed.isdisjoint(inspect.signature(operation).parameters)


def test_namespace_create_basic(fixture_namespace_provider, mock_poller):
    fixture_namespace_provider.client.namespaces.get.side_effect = (
        _namespace_not_found()
    )
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace"})
    )

    result = fixture_namespace_provider.create(
        namespace_name="namespace",
        resource_group_name="rg",
        location="eastus",
        tags={"env": "test"},
    )

    assert result == {"name": "namespace", "resourceGroup": "rg"}
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        resource={
            "location": "eastus",
            "tags": {"env": "test"},
            "identity": {"type": "SystemAssigned"},
        },
    )


def test_namespace_create_resolves_resource_group_location(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.side_effect = (
        _namespace_not_found()
    )
    fixture_namespace_provider._ensure_location = Mock(return_value="westus2")
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create("namespace", "rg")

    fixture_namespace_provider._ensure_location.assert_called_once_with(
        fixture_namespace_provider.cmd.cli_ctx, "rg", None
    )


def test_namespace_create_no_wait_handles_whitespace_uami(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.side_effect = (
        _namespace_not_found()
    )
    poller = mock_poller({"name": "namespace"})
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        poller
    )

    result = fixture_namespace_provider.create(
        "namespace",
        "rg",
        location="eastus",
        outbound_mi_user_assigned=" ",
        no_wait=True,
    )

    assert result is poller
    body = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["identity"] == {"type": "SystemAssigned"}
    assert "properties" not in body


def test_namespace_identity_can_be_user_assigned_only():
    assert _build_namespace_identity(
        user_assigned_identity=UAMI_ID
    ) == {
        "type": "UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}},
    }


@pytest.mark.parametrize(
    "has_system_assigned,user_identity_ids,expected",
    [
        (True, set(), "SystemAssigned"),
        (False, {UAMI_ID}, "UserAssigned"),
        (False, set(), "None"),
    ],
)
def test_managed_identity_type(
    has_system_assigned, user_identity_ids, expected
):
    assert (
        _managed_identity_type(has_system_assigned, user_identity_ids)
        == expected
    )


def test_namespace_create_outbound_uami(fixture_namespace_provider, mock_poller):
    fixture_namespace_provider.client.namespaces.get.side_effect = (
        _namespace_not_found()
    )
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create(
        "namespace",
        "rg",
        location="eastus",
        outbound_mi_user_assigned=UAMI_ID,
    )

    body = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["properties"]["outboundIdentity"] == {
        "type": "UserAssigned",
        "userAssignedIdentity": UAMI_ID,
    }
    assert body["identity"] == {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}},
    }


def test_namespace_outbound_identity_is_mutually_exclusive(
    fixture_namespace_provider,
):
    with pytest.raises(MutuallyExclusiveArgumentError):
        fixture_namespace_provider.create(
            "namespace",
            "rg",
            location="eastus",
            outbound_mi_system_assigned=True,
            outbound_mi_user_assigned=UAMI_ID,
        )


def test_namespace_rejects_invalid_user_assigned_identity(
    fixture_namespace_provider,
):
    with pytest.raises(InvalidArgumentValueError, match="resource ID"):
        fixture_namespace_provider.create(
            "namespace",
            "rg",
            location="eastus",
            outbound_mi_user_assigned="not-an-arm-id",
        )
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_namespace_rejects_non_uami_resource_id(fixture_namespace_provider):
    storage_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.Storage/storageAccounts/account"
    )
    with pytest.raises(InvalidArgumentValueError, match="userAssignedIdentities"):
        fixture_namespace_provider.create(
            "namespace",
            "rg",
            location="eastus",
            outbound_mi_user_assigned=storage_id,
        )


def test_namespace_show_and_list(fixture_namespace_provider):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "name": "namespace"
    }
    fixture_namespace_provider.client.namespaces.list_by_resource_group.return_value = iter(
        [{"name": "one"}]
    )
    fixture_namespace_provider.client.namespaces.list_by_subscription.return_value = iter(
        [{"name": "one"}, {"name": "two"}]
    )

    assert fixture_namespace_provider.show("namespace", "rg") == {
        "name": "namespace"
    }
    assert fixture_namespace_provider.list("rg") == [{"name": "one"}]
    assert fixture_namespace_provider.list() == [
        {"name": "one"},
        {"name": "two"},
    ]


def test_namespace_update_tags(fixture_namespace_provider, mock_poller):
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_poller(
        {"name": "namespace"}
    )

    fixture_namespace_provider.update(
        "namespace", "rg", tags={"env": "production"}
    )

    fixture_namespace_provider.client.namespaces.begin_update.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        properties={"tags": {"env": "production"}},
    )
    fixture_namespace_provider.client.namespaces.get.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_namespace_update_observability_preserves_endpoints(
    fixture_namespace_provider, mock_poller, enabled
):
    endpoint = {
        "endpointType": "Microsoft.EventGrid/namespaces",
        "address": "eventgrid.example",
        "scopeId": "scope",
        "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
                      "Microsoft.EventGrid/namespaces/eg",
    }
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "properties": {
            "observability": {
                "enabled": not enabled,
                "endpoints": {"event-grid": endpoint},
            }
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_poller(
        {"name": "namespace"}
    )

    fixture_namespace_provider.update(
        "namespace", "rg", observability_enabled=enabled
    )

    fixture_namespace_provider.client.namespaces.begin_update.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        properties={
            "properties": {
                "observability": {
                    "enabled": enabled,
                    "endpoints": {"event-grid": endpoint},
                }
            }
        },
    )


@pytest.mark.parametrize(
    "observability",
    [
        None,
        {"enabled": False},
        {"enabled": False, "endpoints": {}},
        {"enabled": False, "endpoints": {"site": {"resourceId": "incomplete"}}},
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_namespace_update_observability_requires_complete_existing_endpoint(
    fixture_namespace_provider, observability, enabled
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "properties": {"observability": observability}
    }

    with pytest.raises(
        InvalidArgumentValueError,
        match="complete service-configured observability endpoint",
    ):
        fixture_namespace_provider.update(
            "namespace", "rg", observability_enabled=enabled
        )

    fixture_namespace_provider.client.namespaces.begin_update.assert_not_called()


def test_namespace_update_observability_and_outbound_identity_share_lookup(
    fixture_namespace_provider, mock_poller
):
    endpoint = {
        "endpointType": "Microsoft.EventGrid/namespaces",
        "address": "eventgrid.example",
        "scopeId": "scope",
        "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
                      "Microsoft.EventGrid/namespaces/eg",
    }
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "observability": {
                "enabled": False,
                "endpoints": {"event-grid": endpoint},
            }
        },
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_poller(
        {"name": "namespace"}
    )

    fixture_namespace_provider.update(
        "namespace",
        "rg",
        observability_enabled=True,
        outbound_mi_system_assigned=True,
    )

    fixture_namespace_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
    )
    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body["identity"] == {"type": "SystemAssigned"}
    assert body["properties"]["observability"] == {
        "enabled": True,
        "endpoints": {"event-grid": endpoint},
    }


def test_namespace_update_outbound_uami_preserves_identity_assignments(
    fixture_namespace_provider, mock_poller
):
    existing_id = UAMI_ID.replace("identity", "existing")
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {existing_id: {"principalId": "ignored"}},
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_poller(
        {"name": "namespace"}
    )

    fixture_namespace_provider.update(
        "namespace", "rg", outbound_mi_user_assigned=UAMI_ID
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {
                existing_id: {},
                UAMI_ID: {},
            },
        },
        "properties": {
            "outboundIdentity": {
                "type": "UserAssigned",
                "userAssignedIdentity": UAMI_ID,
            }
        },
    }


def test_namespace_update_outbound_uami_deduplicates_id_casing(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = (
        mock_poller({})
    )

    fixture_namespace_provider.update(
        "namespace",
        "rg",
        outbound_mi_user_assigned=UAMI_ID.replace("identity", "IDENTITY"),
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body["identity"] == {
        "type": "UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}},
    }


def test_namespace_update_rejects_empty_patch(fixture_namespace_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
        fixture_namespace_provider.update("namespace", "rg")
    fixture_namespace_provider.client.namespaces.begin_update.assert_not_called()


def test_namespace_update_no_wait(fixture_namespace_provider, mock_poller):
    poller = mock_poller({})
    fixture_namespace_provider.client.namespaces.begin_update.return_value = poller

    result = fixture_namespace_provider.update(
        "namespace", "rg", tags={}, no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()


def test_namespace_delete_propagates_unrelated_service_error(
    fixture_namespace_provider,
):
    error = HttpResponseError(message="Service unavailable")
    error.status_code = 503
    fixture_namespace_provider.client.namespaces.begin_delete.side_effect = error

    with pytest.raises(HttpResponseError, match="Service unavailable"):
        fixture_namespace_provider.delete("namespace", "rg")


def test_namespace_delete_not_empty_lists_safe_destructive_cleanup(
    fixture_namespace_provider,
):
    error = HttpResponseError(
        message="NamespaceNotEmpty: child resources remain\nbackend detail"
    )
    fixture_namespace_provider.client.namespaces.begin_delete.side_effect = error

    with pytest.raises(AzureResponseError) as raised:
        fixture_namespace_provider.delete("namespace", "rg")

    message = str(raised.value)
    assert "job run delete" in message
    assert "ca policy delete" in message
    assert "link hub delete" in message
    assert "link dps delete" in message
    assert "link su delete" in message
    assert "permanently deletes" in message


def test_namespace_create_preserves_existing_observability(
    fixture_namespace_provider, mock_poller
):
    observability = {
        "enabled": True,
        "endpoints": {
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ExtendedLocation/customLocations/site": {
                "endpointType": "Microsoft.EventGrid/namespaces",
                "address": "eventgrid.example",
                "scopeId": "scope",
                "resourceId": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.EventGrid/namespaces/eg"
                ),
            }
        },
    }
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "properties": {"observability": observability}
    }
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create(
        "namespace",
        "rg",
        location="eastus",
        tags={"phase": "replaced"},
    )

    resource = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert resource["properties"]["observability"] == observability


def test_namespace_create_upsert_preserves_unspecified_namespace_state(
    fixture_namespace_provider, mock_poller
):
    existing = {
        "location": "centraluseuap",
        "tags": {"existing": "tag"},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        },
        "properties": {
            "uuid": "read-only",
            "provisioningState": "Succeeded",
            "outboundIdentity": {"type": "SystemAssigned"},
            "management": {"endpoints": {"management": {"resourceId": "/management"}}},
            "provisioning": {"endpoints": {"dps": {"resourceId": "/dps"}}},
            "messaging": {"endpoints": {"hub": {"resourceId": "/hub"}}},
            "updating": {"endpoints": {"su": {"resourceId": "/su"}}},
        },
    }
    fixture_namespace_provider.client.namespaces.get.return_value = existing
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create("namespace", "rg")

    resource = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert resource["location"] == "centraluseuap"
    assert resource["tags"] == {"existing": "tag"}
    assert resource["identity"] == {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}},
    }
    assert resource["properties"] == {
        key: value
        for key, value in existing["properties"].items()
        if key not in {"uuid", "provisioningState"}
    }


@pytest.mark.parametrize(
    "existing_identity",
    [
        {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                UAMI_ID: {
                    "principalId": "server-owned",
                    "clientId": "server-owned",
                }
            },
        },
        {"type": "None"},
        None,
    ],
)
def test_namespace_create_upsert_preserves_identity_exactly_when_unspecified(
    fixture_namespace_provider, mock_poller, existing_identity
):
    existing = {
        "location": "centraluseuap",
        "properties": {"observability": {"enabled": True}},
    }
    if existing_identity is not None:
        existing["identity"] = existing_identity
    fixture_namespace_provider.client.namespaces.get.return_value = existing
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create("namespace", "rg")

    body = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    if existing_identity is None:
        assert "identity" not in body
    elif existing_identity["type"] == "None":
        assert body["identity"] == {"type": "None"}
    else:
        assert body["identity"] == {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }


def test_namespace_create_upsert_outbound_uami_does_not_add_sami(
    fixture_namespace_provider, mock_poller
):
    existing_uami = UAMI_ID.replace("identity", "existing")
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "location": "centraluseuap",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {existing_uami: {}},
        },
        "properties": {},
    }
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create(
        "namespace",
        "rg",
        outbound_mi_user_assigned=UAMI_ID,
    )

    body = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["identity"] == {
        "type": "UserAssigned",
        "userAssignedIdentities": {
            existing_uami: {},
            UAMI_ID: {},
        },
    }
    assert body["properties"]["outboundIdentity"] == {
        "type": "UserAssigned",
        "userAssignedIdentity": UAMI_ID,
    }


def test_namespace_create_upsert_can_clear_outbound_identity(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "location": "centraluseuap",
        "identity": {"type": "SystemAssigned"},
        "properties": {
            "outboundIdentity": {"type": "SystemAssigned"},
        },
    }
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create(
        "namespace",
        "rg",
        outbound_mi_system_assigned=False,
    )

    resource = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert resource["properties"]["outboundIdentity"] is None


@pytest.mark.parametrize("enabled", [True, False])
def test_namespace_create_observability_overrides_enabled_and_preserves_endpoints(
    fixture_namespace_provider, mock_poller, enabled
):
    endpoint = {
        "endpointType": "Microsoft.EventGrid/namespaces",
        "address": "eventgrid.example",
        "scopeId": "scope",
        "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/"
                      "Microsoft.EventGrid/namespaces/eg",
    }
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "properties": {
            "observability": {
                "enabled": not enabled,
                "endpoints": {"event-grid": endpoint},
            }
        }
    }
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = (
        mock_poller({"name": "namespace", "resourceGroup": "rg"})
    )

    fixture_namespace_provider.create(
        "namespace",
        "rg",
        location="eastus",
        observability_enabled=enabled,
    )

    resource = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert resource["properties"]["observability"] == {
        "enabled": enabled,
        "endpoints": {"event-grid": endpoint},
    }


@pytest.mark.parametrize("enabled", [True, False])
def test_namespace_create_observability_requires_existing_endpoint(
    fixture_namespace_provider, enabled
):
    fixture_namespace_provider.client.namespaces.get.side_effect = (
        _namespace_not_found()
    )

    with pytest.raises(
        InvalidArgumentValueError,
        match="complete service-configured observability endpoint",
    ):
        fixture_namespace_provider.create(
            "namespace",
            "rg",
            location="eastus",
            observability_enabled=enabled,
        )

    fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_namespace_create_propagates_existing_namespace_lookup_error(
    fixture_namespace_provider,
):
    error = HttpResponseError(message="Service unavailable")
    error.status_code = 503
    fixture_namespace_provider.client.namespaces.get.side_effect = error

    with pytest.raises(HttpResponseError, match="Service unavailable"):
        fixture_namespace_provider.create(
            "namespace",
            "rg",
            location="eastus",
        )
    fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_namespace_migrate_no_wait(fixture_namespace_provider, mock_poller):
    asset_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/assets/asset"
    )
    poller = mock_poller({"migrateResults": []})
    fixture_namespace_provider.client.namespaces.begin_migrate.return_value = poller

    result = fixture_namespace_provider.migrate(
        "namespace",
        "rg",
        [asset_id, asset_id.upper()],
        no_wait=True,
    )

    assert result is poller
    fixture_namespace_provider.client.namespaces.begin_migrate.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        body={"scope": "Resources", "resourceIds": [asset_id]},
    )


@pytest.mark.parametrize(
    "resource_ids",
    [
        None,
        [],
        [""],
        ["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/a"],
        [
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceRegistry/assets/a/children/b"
        ],
    ],
)
def test_namespace_migrate_rejects_invalid_resource_ids(
    fixture_namespace_provider, resource_ids
):
    with pytest.raises((InvalidArgumentValueError, RequiredArgumentMissingError)):
        fixture_namespace_provider.migrate("namespace", "rg", resource_ids)
    fixture_namespace_provider.client.namespaces.begin_migrate.assert_not_called()


def test_clean_migrate_resource_ids_preserves_first_casing():
    resource_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/assets/asset"
    )
    assert _clean_migrate_resource_ids([resource_id, resource_id.upper()]) == [
        resource_id
    ]


def test_namespace_update_can_clear_explicit_outbound_identity(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_namespace_provider.update(
        "namespace", "rg", outbound_mi_system_assigned=False
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {"properties": {"outboundIdentity": None}}


def test_namespace_identity_show(fixture_namespace_provider):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"}
    }

    assert fixture_namespace_provider.identity_show("namespace", "rg") == {
        "type": "SystemAssigned"
    }


def test_namespace_identity_assign_preserves_existing_assignments(
    fixture_namespace_provider, mock_poller
):
    existing_id = UAMI_ID.replace("identity", "existing")
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {existing_id: {}},
        }
    }
    expected_identity = {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {existing_id: {}, UAMI_ID: {}},
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = (
        mock_poller({"identity": expected_identity})
    )

    result = fixture_namespace_provider.identity_assign(
        "namespace", "rg", user_assigned_identities=[UAMI_ID]
    )

    assert result == expected_identity
    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {"identity": expected_identity}


def test_namespace_identity_assign_rejects_noop(fixture_namespace_provider):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"}
    }

    with pytest.raises(InvalidArgumentValueError, match="already assigned"):
        fixture_namespace_provider.identity_assign(
            "namespace", "rg", system_assigned=True
        )
    fixture_namespace_provider.client.namespaces.begin_update.assert_not_called()


def test_namespace_identity_assignment_compares_ids_case_insensitively(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }
    }

    with pytest.raises(InvalidArgumentValueError, match="already assigned"):
        fixture_namespace_provider.identity_assign(
            "namespace",
            "rg",
            user_assigned_identities=[UAMI_ID.replace("identity", "IDENTITY")],
        )


def test_namespace_identity_assign_requires_selection(fixture_namespace_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Specify"):
        fixture_namespace_provider.identity_assign("namespace", "rg")


def test_namespace_identity_assign_rejects_empty_id(fixture_namespace_provider):
    with pytest.raises(InvalidArgumentValueError, match="must not be empty"):
        fixture_namespace_provider.identity_assign(
            "namespace", "rg", user_assigned_identities=[""]
        )


def test_namespace_identity_assign_system_only_no_wait(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "None"}
    }
    poller = mock_poller({})
    fixture_namespace_provider.client.namespaces.begin_update.return_value = poller

    result = fixture_namespace_provider.identity_assign(
        "namespace", "rg", system_assigned=True, no_wait=True
    )

    assert result is poller
    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {"identity": {"type": "SystemAssigned"}}


def test_namespace_identity_remove_uses_null_uami_patch(
    fixture_namespace_provider, mock_poller
):
    keep_id = UAMI_ID.replace("identity", "keep")
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}, keep_id: {}},
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = (
        mock_poller(
            {
                "identity": {
                    "type": "SystemAssigned,UserAssigned",
                    "userAssignedIdentities": {keep_id: {}},
                }
            }
        )
    )

    fixture_namespace_provider.identity_remove(
        "namespace", "rg", user_assigned_identities=[UAMI_ID]
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {keep_id: {}, UAMI_ID: None},
        }
    }


def test_namespace_identity_removal_compares_ids_case_insensitively(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = (
        mock_poller({"identity": {"type": "None"}})
    )

    fixture_namespace_provider.identity_remove(
        "namespace",
        "rg",
        user_assigned_identities=[UAMI_ID.replace("identity", "IDENTITY")],
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {
        "identity": {
            "type": "None",
        }
    }


def test_namespace_identity_remove_last_uami_retains_system_identity(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }
    }
    fixture_namespace_provider.client.namespaces.begin_update.return_value = (
        mock_poller({"identity": {"type": "SystemAssigned"}})
    )

    fixture_namespace_provider.identity_remove(
        "namespace", "rg", user_assigned_identities=[UAMI_ID]
    )

    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {
        "identity": {
            "type": "SystemAssigned",
        }
    }


def test_namespace_identity_remove_rejects_outbound_identity(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        },
        "properties": {
            "outboundIdentity": {
                "type": "UserAssigned",
                "userAssignedIdentity": UAMI_ID,
            }
        },
    }

    with pytest.raises(InvalidArgumentValueError, match="outbound"):
        fixture_namespace_provider.identity_remove(
            "namespace", "rg", user_assigned_identities=[UAMI_ID]
        )


def test_namespace_identity_remove_requires_selection(fixture_namespace_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Specify"):
        fixture_namespace_provider.identity_remove("namespace", "rg")


def test_namespace_identity_remove_rejects_empty_namespace(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "None"}
    }
    with pytest.raises(InvalidArgumentValueError, match="no user-assigned"):
        fixture_namespace_provider.identity_remove(
            "namespace", "rg", user_assigned_identities=[]
        )


def test_namespace_identity_remove_rejects_unassigned_identity(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"}
    }
    with pytest.raises(InvalidArgumentValueError, match="not assigned"):
        fixture_namespace_provider.identity_remove(
            "namespace", "rg", user_assigned_identities=[UAMI_ID]
        )


def test_namespace_identity_remove_rejects_missing_system_identity(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "None"}
    }
    with pytest.raises(InvalidArgumentValueError, match="does not have"):
        fixture_namespace_provider.identity_remove(
            "namespace", "rg", system_assigned=True
        )


def test_namespace_identity_remove_rejects_system_outbound_identity(
    fixture_namespace_provider,
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"},
        "properties": {"outboundIdentity": {"type": "SystemAssigned"}},
    }
    with pytest.raises(InvalidArgumentValueError, match="outbound"):
        fixture_namespace_provider.identity_remove(
            "namespace", "rg", system_assigned=True
        )


def test_namespace_identity_remove_system_only_no_wait(
    fixture_namespace_provider, mock_poller
):
    fixture_namespace_provider.client.namespaces.get.return_value = {
        "identity": {"type": "SystemAssigned"}
    }
    poller = mock_poller({})
    fixture_namespace_provider.client.namespaces.begin_update.return_value = poller

    result = fixture_namespace_provider.identity_remove(
        "namespace", "rg", system_assigned=True, no_wait=True
    )

    assert result is poller
    body = fixture_namespace_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {"identity": {"type": "None"}}


def test_namespace_delete_no_wait(fixture_namespace_provider, mock_poller):
    poller = mock_poller(None)
    fixture_namespace_provider.client.namespaces.begin_delete.return_value = poller

    result = fixture_namespace_provider.delete(
        "namespace", "rg", no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()
