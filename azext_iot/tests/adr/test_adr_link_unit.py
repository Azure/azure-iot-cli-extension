# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import (
    SU_ENDPOINT_TYPE,
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    build_mi_body,
)
from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_helpers import (
    endpoint_update_body as _endpoint_update_body,
    namespace_replace_body as _namespace_replace_body,
    parse_dps_resource_id as _parse_dps_resource_id,
    parse_hub_resource_id as _parse_hub_resource_id,
    parse_su_resource_id as _parse_su_resource_id,
)
from azext_iot.adr.providers.link_persistence import (
    begin_linked_resource_delete,
    wait_for_linked_resource_deleted,
)


HUB_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)
DPS_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.Devices/provisioningServices/dps"
)
SU_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.DeviceUpdate/updateInstances/su"
)
UAMI_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
)


def _namespace(*, hubs=None, dps=None, su=None):
    return {
        "properties": {
            "messaging": {"endpoints": hubs or {}},
            "provisioning": {"endpoints": dps or {}},
            "updating": {"endpoints": su or {}},
        }
    }


def _endpoint(endpoint_type, resource_id, **extra):
    return {
        "endpointType": endpoint_type,
        "resourceId": resource_id,
        **extra,
    }


def _http_error(status_code):
    error = HttpResponseError(message=f"HTTP {status_code}")
    error.status_code = status_code
    return error


def _namespace_for_delete():
    """A GET response containing writable state and service-generated fields."""
    return {
        "id": "/namespace/id",
        "name": "namespace",
        "type": "Microsoft.DeviceRegistry/namespaces",
        "systemData": {"createdBy": "service"},
        "location": "eastus",
        "tags": {"env": "test"},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "principal",
            "tenantId": "tenant",
            "userAssignedIdentities": {
                UAMI_ID: {"clientId": "client", "principalId": "uami-principal"}
            },
        },
        "properties": {
            "uuid": "read-only",
            "provisioningState": "Succeeded",
            "management": {
                "endpoints": {
                    "generated": {
                        "endpointType": "Microsoft.IoTOperations/instances",
                        "resourceId": "/management",
                        "scopeId": "scope",
                        "address": "https://generated",
                    }
                }
            },
            "outboundIdentity": {"type": "SystemAssigned"},
            "observability": {
                "enabled": True,
                "endpoints": {"metrics": {"resourceId": "/metrics"}},
            },
            "messaging": {
                "endpoints": {
                    "hub": _endpoint(
                        IOT_HUB_ENDPOINT_TYPE,
                        HUB_ID,
                        inboundCallerIdentity={"type": "SystemAssigned"},
                        provisioning={
                            "availability": "Available",
                            "allocationWeight": 10,
                        },
                        address="read-only",
                        deviceAddress="read-only",
                        linkingState="Succeeded",
                        linkingError={"message": "read-only"},
                    ),
                    "other-hub": _endpoint(
                        IOT_HUB_ENDPOINT_TYPE,
                        HUB_ID.replace("/hub", "/other"),
                        address="read-only",
                    ),
                }
            },
            "provisioning": {
                "endpoints": {
                    "dps": _endpoint(
                        DPS_ENDPOINT_TYPE,
                        DPS_ID,
                        inboundCallerIdentity={
                            "type": "UserAssigned",
                            "userAssignedIdentity": UAMI_ID,
                        },
                        linkingState="Succeeded",
                    )
                }
            },
            "updating": {
                "endpoints": {
                    "su": _endpoint(
                        SU_ENDPOINT_TYPE,
                        SU_ID,
                        inboundCallerIdentity={"type": "SystemAssigned"},
                        serviceAddress="read-only",
                        linkingState="Succeeded",
                    ),
                    "empty": None,
                }
            },
        },
    }


def test_link_provider_reuses_injected_namespace_client(mocker):
    fallback_factory = mocker.patch(
        "azext_iot.adr.providers.base.adr_service_factory"
    )
    cmd = Mock(cli_ctx=Mock())
    namespace_client = Mock()

    provider = LinkProvider(cmd, client=namespace_client)

    assert provider.cmd is cmd
    assert provider.client is namespace_client
    fallback_factory.assert_not_called()


def test_identity_body_treats_whitespace_uami_as_unset():
    assert (
        build_mi_body(
            False,
            " ",
            sami_type="SystemAssigned",
            uami_type="UserAssigned",
        )
        is None
    )


def test_su_contract_uses_update_instances():
    assert SU_ENDPOINT_TYPE == "Microsoft.DeviceUpdate/updateInstances"
    assert _parse_su_resource_id(SU_ID) == {
        "subscription_id": "sub",
        "resource_group_name": "rg",
        "name": "su",
    }


def test_hub_parser_accepts_only_iothub_resource_ids():
    assert _parse_hub_resource_id(HUB_ID) == {
        "subscription_id": "sub",
        "resource_group_name": "rg",
        "name": "hub",
    }
    for resource_id in ("", "hub", DPS_ID, f"{HUB_ID}/certificates/cert"):
        with pytest.raises(InvalidArgumentValueError):
            _parse_hub_resource_id(resource_id)


@pytest.mark.parametrize(
    "resource_id",
    [
        "",
        "su",
        "/not/an/arm/id",
        (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/linkedAccounts/su"
        ),
        (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/updateInstances/su/children/child"
        ),
        HUB_ID,
    ],
)
def test_su_parser_rejects_non_update_instance_ids(resource_id):
    with pytest.raises(InvalidArgumentValueError):
        _parse_su_resource_id(resource_id)


@pytest.mark.parametrize(
    "resource_id",
    [
        "",
        "dps",
        "/not/an/arm/id",
        HUB_ID,
        f"{DPS_ID}/certificates/certificate",
    ],
)
def test_dps_parser_rejects_non_dps_ids(resource_id):
    with pytest.raises(InvalidArgumentValueError):
        _parse_dps_resource_id(resource_id)


def test_hub_add_includes_create_only_provisioning_fields(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.hub_add(
        endpoint_name="hub-endpoint",
        namespace_name="namespace",
        resource_group_name="rg",
        hub_resource_id=HUB_ID,
        mi_system_assigned=True,
        availability="Available",
        allocation_weight=10,
    )

    body = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]
    assert body == {
        "properties": {
            "messaging": {
                "endpoints": {
                    "hub-endpoint": {
                        "endpointType": IOT_HUB_ENDPOINT_TYPE,
                        "resourceId": HUB_ID,
                        "inboundCallerIdentity": {"type": "SystemAssigned"},
                        "provisioning": {
                            "availability": "Available",
                            "allocationWeight": 10,
                        },
                    }
                }
            }
        }
    }


def test_hub_add_allows_no_inbound_identity(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.hub_add(
        "hub-endpoint", "namespace", "rg", HUB_ID
    )

    endpoint = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["messaging"]["endpoints"]["hub-endpoint"]
    assert "inboundCallerIdentity" not in endpoint
    assert "provisioning" not in endpoint


def test_hub_add_requires_dps_first(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(ArgumentUsageError, match="DPS link is required"):
        fixture_link_provider.hub_add(
            "hub-endpoint", "namespace", "rg", HUB_ID
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_hub_add_rejects_eleventh_hub_before_preflight(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)},
        hubs={
            f"hub-{index}": _endpoint(IOT_HUB_ENDPOINT_TYPE, HUB_ID)
            for index in range(10)
        },
    )

    with pytest.raises(ArgumentUsageError, match="maximum of 10"):
        fixture_link_provider.hub_add(
            "hub-11", "namespace", "rg", HUB_ID
        )
    fixture_link_provider._preflight_link.assert_not_called()


def test_hub_update_surface_is_identity_only():
    parameters = inspect.signature(LinkProvider.hub_update).parameters
    assert "availability" not in parameters
    assert "allocation_weight" not in parameters


def test_hub_update_rotates_identity_and_preserves_provisioning(
    fixture_link_provider, mock_poller
):
    existing = _endpoint(
        IOT_HUB_ENDPOINT_TYPE,
        HUB_ID,
        inboundCallerIdentity={"type": "SystemAssigned"},
        provisioning={"availability": "Available", "allocationWeight": 50},
        serviceAddress="host.azure-devices.net",
    )
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={"hub-endpoint": existing}
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.hub_update(
        "hub-endpoint",
        "namespace",
        "rg",
        mi_user_assigned=UAMI_ID,
    )

    endpoint = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["messaging"]["endpoints"]["hub-endpoint"]
    assert endpoint == {
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": HUB_ID,
        "inboundCallerIdentity": {
            "type": "UserAssigned",
            "userAssignedIdentity": UAMI_ID,
        },
        "provisioning": {
            "availability": "Available",
            "allocationWeight": 50,
        },
    }
    assert "serviceAddress" not in endpoint


@pytest.mark.parametrize("linking_state", ["Failed", "fAiLeD"])
def test_failed_hub_update_without_dps_is_rejected(
    fixture_link_provider, linking_state
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={
            "hub-endpoint": _endpoint(
                IOT_HUB_ENDPOINT_TYPE,
                HUB_ID,
                linkingState=linking_state,
            )
        }
    )

    with pytest.raises(
        ArgumentUsageError,
        match="before adding a new Hub or retrying a failed Hub",
    ):
        fixture_link_provider.hub_update(
            "hub-endpoint",
            "namespace",
            "rg",
            mi_system_assigned=True,
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_failed_hub_update_with_dps_is_allowed(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={
            "hub-endpoint": _endpoint(
                IOT_HUB_ENDPOINT_TYPE,
                HUB_ID,
                linkingState="Failed",
            )
        },
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)},
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = (
        mock_poller({})
    )

    fixture_link_provider.hub_update(
        "hub-endpoint",
        "namespace",
        "rg",
        mi_system_assigned=True,
    )

    fixture_link_provider.client.namespaces.begin_update.assert_called_once()


def test_succeeded_hub_update_without_dps_is_allowed(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={
            "hub-endpoint": _endpoint(
                IOT_HUB_ENDPOINT_TYPE,
                HUB_ID,
                linkingState="Succeeded",
            )
        }
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = (
        mock_poller({})
    )

    fixture_link_provider.hub_update(
        "hub-endpoint",
        "namespace",
        "rg",
        mi_system_assigned=True,
    )

    fixture_link_provider.client.namespaces.begin_update.assert_called_once()


def test_non_failed_hub_update_without_dps_is_not_over_gated(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={
            "hub-endpoint": _endpoint(
                IOT_HUB_ENDPOINT_TYPE,
                HUB_ID,
                linkingState="Pending",
            )
        }
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = (
        mock_poller({})
    )

    fixture_link_provider.hub_update(
        "hub-endpoint",
        "namespace",
        "rg",
        mi_system_assigned=True,
    )

    fixture_link_provider.client.namespaces.begin_update.assert_called_once()


@pytest.mark.parametrize(
    "kwargs,exception",
    [
        ({}, RequiredArgumentMissingError),
        (
            {"mi_system_assigned": True, "mi_user_assigned": UAMI_ID},
            ArgumentUsageError,
        ),
    ],
)
def test_hub_update_validates_identity(
    fixture_link_provider, kwargs, exception
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={"hub-endpoint": _endpoint(IOT_HUB_ENDPOINT_TYPE, HUB_ID)}
    )

    with pytest.raises(exception):
        fixture_link_provider.hub_update(
            "hub-endpoint", "namespace", "rg", **kwargs
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_hub_update_requires_existing_endpoint(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(ResourceNotFoundError, match="hub-endpoint"):
        fixture_link_provider.hub_update(
            "hub-endpoint",
            "namespace",
            "rg",
            mi_system_assigned=True,
        )


def test_endpoint_update_body_can_preserve_identity_or_omit_it():
    existing = _endpoint(
        IOT_HUB_ENDPOINT_TYPE,
        HUB_ID,
        inboundCallerIdentity={"type": "SystemAssigned"},
    )
    assert _endpoint_update_body(existing) == {
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": HUB_ID,
        "inboundCallerIdentity": {"type": "SystemAssigned"},
    }
    assert _endpoint_update_body(
        _endpoint(IOT_HUB_ENDPOINT_TYPE, HUB_ID)
    ) == {
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": HUB_ID,
    }


def test_hub_show_and_list_include_endpoint_names(fixture_link_provider):
    hub = _endpoint(
        IOT_HUB_ENDPOINT_TYPE, HUB_ID, serviceAddress="hub.azure-devices.net"
    )
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        hubs={
            "primary": hub,
            "future": _endpoint("Future.Type/endpoints", "/future"),
        }
    )

    assert fixture_link_provider.hub_show(
        "primary", "namespace", "rg"
    ) == {"name": "primary", **hub}
    assert fixture_link_provider.hub_list("namespace", "rg") == [
        {"name": "primary", **hub}
    ]


def test_hub_list_empty_is_list(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()
    result = fixture_link_provider.hub_list("namespace", "rg")
    assert result == []
    assert isinstance(result, list)


def test_dps_add_uses_update_body(fixture_link_provider, mock_poller):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.dps_add(
        "dps-endpoint",
        "namespace",
        "rg",
        DPS_ID,
        mi_system_assigned=True,
    )

    endpoint = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["provisioning"]["endpoints"]["dps-endpoint"]
    assert endpoint == {
        "endpointType": DPS_ENDPOINT_TYPE,
        "resourceId": DPS_ID,
        "inboundCallerIdentity": {"type": "SystemAssigned"},
    }


def test_dps_add_requires_identity(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(RequiredArgumentMissingError, match="identity is required"):
        fixture_link_provider.dps_add(
            "dps-endpoint", "namespace", "rg", DPS_ID
        )


def test_dps_add_treats_whitespace_uami_as_missing(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(RequiredArgumentMissingError, match="identity is required"):
        fixture_link_provider.dps_add(
            "dps-endpoint",
            "namespace",
            "rg",
            DPS_ID,
            mi_user_assigned=" ",
        )


def test_dps_add_rejects_second_endpoint(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"existing": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )

    with pytest.raises(ArgumentUsageError, match="already has a linked DPS"):
        fixture_link_provider.dps_add(
            "second",
            "namespace",
            "rg",
            DPS_ID,
            mi_system_assigned=True,
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_dps_update_show_and_list_named_objects(
    fixture_link_provider, mock_poller, mocker
):
    endpoint = _endpoint(
        DPS_ENDPOINT_TYPE,
        DPS_ID,
        inboundCallerIdentity={"type": "SystemAssigned"},
    )
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"primary": endpoint}
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )
    dps_client = mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_service_provisioning_factory"
    ).return_value.iot_dps_resource
    dps_client.get.return_value = {
        "properties": {"iotHubs": [{"name": "brownfield"}]}
    }

    fixture_link_provider.dps_update(
        "primary", "namespace", "rg", mi_user_assigned=UAMI_ID
    )
    updated = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["provisioning"]["endpoints"]["primary"]
    assert updated["inboundCallerIdentity"]["type"] == "UserAssigned"

    shown = fixture_link_provider.dps_show("primary", "namespace", "rg")
    assert shown["name"] == "primary"
    assert shown["brownfieldHubs"] == [{"name": "brownfield"}]
    assert fixture_link_provider.dps_list("namespace", "rg") == [
        {"name": "primary", **endpoint}
    ]
    dps_client.get.assert_called_once_with(
        resource_group_name="rg", provisioning_service_name="dps"
    )


def test_dps_show_without_resource_id_still_returns_named_object(
    fixture_link_provider,
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"primary": {"endpointType": DPS_ENDPOINT_TYPE}}
    )

    assert fixture_link_provider.dps_show("primary", "namespace", "rg") == {
        "name": "primary",
        "endpointType": DPS_ENDPOINT_TYPE,
    }


@pytest.mark.parametrize(
    "kind,section,endpoint_type,resource_id",
    [
        ("dps", "dps", DPS_ENDPOINT_TYPE, DPS_ID),
        ("su", "su", SU_ENDPOINT_TYPE, SU_ID),
    ],
)
@pytest.mark.parametrize(
    "existing,kwargs,exception",
    [
        (True, {}, RequiredArgumentMissingError),
        (
            True,
            {"mi_system_assigned": True, "mi_user_assigned": UAMI_ID},
            ArgumentUsageError,
        ),
        (False, {"mi_system_assigned": True}, ResourceNotFoundError),
    ],
)
def test_dps_and_su_update_validation(
    fixture_link_provider,
    kind,
    section,
    endpoint_type,
    resource_id,
    existing,
    kwargs,
    exception,
):
    endpoints = (
        {"primary": _endpoint(endpoint_type, resource_id)} if existing else {}
    )
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        **{section: endpoints}
    )

    with pytest.raises(exception):
        getattr(fixture_link_provider, f"{kind}_update")(
            "primary", "namespace", "rg", **kwargs
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind,resource_id", [("dps", DPS_ID), ("su", SU_ID)])
def test_dps_and_su_add_reject_mutually_exclusive_identity(
    fixture_link_provider, kind, resource_id
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(ArgumentUsageError):
        getattr(fixture_link_provider, f"{kind}_add")(
            "primary",
            "namespace",
            "rg",
            resource_id,
            mi_system_assigned=True,
            mi_user_assigned=UAMI_ID,
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("resource_id", ["not-an-arm-id", DPS_ID])
def test_dps_show_enrichment_failure_is_non_fatal(
    fixture_link_provider, mocker, resource_id
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"primary": _endpoint(DPS_ENDPOINT_TYPE, resource_id)}
    )
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_service_provisioning_factory",
        side_effect=RuntimeError("unavailable"),
    )

    result = fixture_link_provider.dps_show("primary", "namespace", "rg")

    assert result["name"] == "primary"
    assert result["brownfieldHubs"] == []


def test_su_add_uses_update_instance_endpoint(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.su_add(
        "su-endpoint",
        "namespace",
        "rg",
        SU_ID,
        mi_system_assigned=True,
    )

    endpoint = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["updating"]["endpoints"]["su-endpoint"]
    assert endpoint == {
        "endpointType": "Microsoft.DeviceUpdate/updateInstances",
        "resourceId": SU_ID,
        "inboundCallerIdentity": {"type": "SystemAssigned"},
    }


def test_su_add_requires_identity(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()

    with pytest.raises(RequiredArgumentMissingError, match="identity is required"):
        fixture_link_provider.su_add(
            "su-endpoint", "namespace", "rg", SU_ID
        )


def test_su_add_rejects_duplicate_name(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        su={"su-endpoint": _endpoint(SU_ENDPOINT_TYPE, SU_ID)}
    )

    with pytest.raises(ArgumentUsageError, match="link su update"):
        fixture_link_provider.su_add(
            "su-endpoint",
            "namespace",
            "rg",
            SU_ID,
            mi_system_assigned=True,
        )


@pytest.mark.parametrize(
    "endpoint_type,linking_state",
    [
        (SU_ENDPOINT_TYPE, "Succeeded"),
        (SU_ENDPOINT_TYPE, "Failed"),
        (SU_ENDPOINT_TYPE.swapcase(), "Succeeded"),
    ],
)
def test_su_add_rejects_existing_su_regardless_of_name_state_or_type_casing(
    fixture_link_provider, endpoint_type, linking_state
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        su={
            "existing": _endpoint(
                endpoint_type,
                SU_ID.upper(),
                linkingState=linking_state,
            )
        }
    )

    with pytest.raises(
        ArgumentUsageError,
        match="only one may be linked per namespace",
    ):
        fixture_link_provider.su_add(
            "different-name",
            "namespace",
            "rg",
            SU_ID,
            mi_system_assigned=True,
        )

    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_su_add_ignores_non_su_updating_endpoint(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        su={
            "future": _endpoint(
                "Microsoft.Future/updatingEndpoints",
                "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.Future/updatingEndpoints/future",
                linkingState="Failed",
            ),
            "malformed-service-value": {"endpointType": 1},
        }
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.su_add(
        "su-endpoint",
        "namespace",
        "rg",
        SU_ID,
        mi_system_assigned=True,
    )

    fixture_link_provider.client.namespaces.begin_update.assert_called_once()


def test_su_add_rejects_same_name_non_su_updating_endpoint(
    fixture_link_provider
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        su={
            "same-name": _endpoint(
                "Microsoft.Future/updatingEndpoints",
                "/subscriptions/sub/resourceGroups/rg/providers/"
                "Microsoft.Future/updatingEndpoints/future",
            )
        }
    )

    with pytest.raises(ArgumentUsageError, match="cannot be overwritten"):
        fixture_link_provider.su_add(
            "same-name",
            "namespace",
            "rg",
            SU_ID,
            mi_system_assigned=True,
        )

    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_su_update_show_and_list_named_objects(
    fixture_link_provider, mock_poller
):
    endpoint = _endpoint(
        SU_ENDPOINT_TYPE,
        SU_ID,
        inboundCallerIdentity={"type": "SystemAssigned"},
        serviceAddress="https://su.example",
    )
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        su={"primary": endpoint}
    )
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.su_update(
        "primary", "namespace", "rg", mi_user_assigned=UAMI_ID
    )

    updated = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]["updating"]["endpoints"]["primary"]
    assert updated == {
        "endpointType": SU_ENDPOINT_TYPE,
        "resourceId": SU_ID,
        "inboundCallerIdentity": {
            "type": "UserAssigned",
            "userAssignedIdentity": UAMI_ID,
        },
    }
    assert fixture_link_provider.su_show(
        "primary", "namespace", "rg"
    ) == {"name": "primary", **endpoint}
    assert fixture_link_provider.su_list("namespace", "rg") == [
        {"name": "primary", **endpoint}
    ]


@pytest.mark.parametrize(
    "kind,section,endpoint_type,resource_id,display_name,operation_group,name_parameter",
    [
        (
            "hub",
            "hubs",
            IOT_HUB_ENDPOINT_TYPE,
            HUB_ID,
            "IoT Hub",
            "iot_hub_resource",
            "resource_name",
        ),
        (
            "dps",
            "dps",
            DPS_ENDPOINT_TYPE,
            DPS_ID,
            "DPS",
            "iot_dps_resource",
            "provisioning_service_name",
        ),
        (
            "su",
            "su",
            SU_ENDPOINT_TYPE,
            SU_ID,
            "Software Updates instance",
            "update_instances",
            "update_instance_name",
        ),
    ],
)
def test_link_update_repeats_add_preflight_before_namespace_patch(
    fixture_link_provider,
    mock_poller,
    kind,
    section,
    endpoint_type,
    resource_id,
    display_name,
    operation_group,
    name_parameter,
):
    endpoint = _endpoint(endpoint_type, resource_id)
    namespace = _namespace(**{section: {"primary": endpoint}})
    fixture_link_provider.client.namespaces.get.return_value = namespace
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    getattr(fixture_link_provider, f"{kind}_update")(
        "primary", "namespace", "rg", mi_system_assigned=True
    )

    preflight = fixture_link_provider._preflight_link.call_args
    assert preflight.kwargs["link_type"] == kind
    assert preflight.kwargs["namespace"] == namespace
    assert preflight.kwargs["target_resource_id"] == resource_id
    assert preflight.kwargs["inbound_identity"] == {
        "type": "SystemAssigned"
    }
    strategy = preflight.kwargs["strategy"]
    assert strategy.operation_group_name == operation_group
    assert strategy.name_parameter == name_parameter
    assert strategy.display_name == display_name
    assert strategy.require_standard_hub is (
        kind == "hub"
    )


def test_existing_link_access_delegates_to_atomic_preflight(
    fixture_link_provider,
):
    namespace = _namespace(
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )
    fixture_link_provider.client.namespaces.get.return_value = namespace

    fixture_link_provider.ensure_link_access(
        "dps",
        "namespace",
        "rg",
        DPS_ID,
        mi_system_assigned=True,
    )

    preflight = fixture_link_provider._preflight_link.call_args  # pylint: disable=protected-access
    assert preflight.kwargs["link_type"] == "dps"
    assert preflight.kwargs["namespace"] == namespace
    assert preflight.kwargs["target_resource_id"] == DPS_ID
    assert preflight.kwargs["inbound_identity"] == {
        "type": "SystemAssigned"
    }


@pytest.mark.parametrize(
    "kind,section,endpoint_type,resource_id",
    [
        ("hub", "hubs", IOT_HUB_ENDPOINT_TYPE, HUB_ID),
        ("dps", "dps", DPS_ENDPOINT_TYPE, DPS_ID),
        ("su", "su", SU_ENDPOINT_TYPE, SU_ID),
    ],
)
def test_link_update_preflight_failure_prevents_namespace_patch(
    fixture_link_provider,
    kind,
    section,
    endpoint_type,
    resource_id,
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        **{section: {"primary": _endpoint(endpoint_type, resource_id)}}
    )
    fixture_link_provider._preflight_link.side_effect = AzureResponseError(
        "RBAC assignments are not visible"
    )

    with pytest.raises(AzureResponseError, match="not visible"):
        getattr(fixture_link_provider, f"{kind}_update")(
            "primary", "namespace", "rg", mi_system_assigned=True
        )

    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize(
    "kind,section,wrong_type,resource_id",
    [
        ("hub", "hubs", DPS_ENDPOINT_TYPE, HUB_ID),
        ("dps", "dps", IOT_HUB_ENDPOINT_TYPE, DPS_ID),
        ("su", "su", DPS_ENDPOINT_TYPE, SU_ID),
    ],
)
def test_link_update_rejects_same_name_endpoint_of_wrong_type(
    fixture_link_provider,
    kind,
    section,
    wrong_type,
    resource_id,
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        **{section: {"primary": _endpoint(wrong_type, resource_id)}}
    )

    with pytest.raises(ResourceNotFoundError):
        getattr(fixture_link_provider, f"{kind}_update")(
            "primary", "namespace", "rg", mi_system_assigned=True
        )

    fixture_link_provider._preflight_link.assert_not_called()
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_show_missing_endpoint_raises(
    fixture_link_provider, kind
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()
    with pytest.raises(ResourceNotFoundError):
        getattr(fixture_link_provider, f"{kind}_show")(
            "missing", "namespace", "rg"
        )


def test_bundled_link_add_keeps_create_only_hub_fields(
    fixture_link_provider, mock_poller
):
    fixture_link_provider.client.namespaces.get.return_value = _namespace()
    fixture_link_provider.client.namespaces.begin_update.return_value = mock_poller(
        {}
    )

    fixture_link_provider.link_add(
        namespace_name="namespace",
        resource_group_name="rg",
        hub_endpoint_name="hub",
        hub_resource_id=HUB_ID,
        dps_endpoint_name="dps",
        dps_resource_id=DPS_ID,
        hub_mi_system_assigned=True,
        dps_mi_system_assigned=True,
        hub_availability="Available",
        hub_allocation_weight=25,
    )

    body = fixture_link_provider.client.namespaces.begin_update.call_args.kwargs[
        "properties"
    ]["properties"]
    assert list(body) == ["provisioning", "messaging"]
    assert body["messaging"]["endpoints"]["hub"]["provisioning"] == {
        "availability": "Available",
        "allocationWeight": 25,
    }


def test_bundled_link_add_rejects_existing_dps(fixture_link_provider):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"existing": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )

    with pytest.raises(ArgumentUsageError, match="already has a linked DPS"):
        fixture_link_provider.link_add(
            namespace_name="namespace",
            resource_group_name="rg",
            hub_endpoint_name="hub",
            hub_resource_id=HUB_ID,
            dps_endpoint_name="dps",
            dps_resource_id=DPS_ID,
            dps_mi_system_assigned=True,
        )
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_link_mutation_supports_no_wait(fixture_link_provider, mock_poller):
    fixture_link_provider.client.namespaces.get.return_value = _namespace(
        dps={"dps": _endpoint(DPS_ENDPOINT_TYPE, DPS_ID)}
    )
    poller = mock_poller(None)
    fixture_link_provider.client.namespaces.begin_update.return_value = poller

    result = fixture_link_provider.hub_add(
        "hub", "namespace", "rg", HUB_ID, no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()


@pytest.mark.parametrize(
    "kind,section,endpoint_name,factory_name,operation_group,name_parameter",
    [
        (
            "hub",
            "messaging",
            "hub",
            "adr_iot_hub_service_factory",
            "iot_hub_resource",
            "resource_name",
        ),
        (
            "dps",
            "provisioning",
            "dps",
            "adr_iot_service_provisioning_factory",
            "iot_dps_resource",
            "provisioning_service_name",
        ),
        (
            "su",
            "updating",
            "su",
            "adr_update_instance_service_factory",
            "update_instances",
            "update_instance_name",
        ),
    ],
)
def test_link_delete_waits_and_routes_using_linked_resource_id(
    fixture_link_provider,
    mocker,
    kind,
    section,
    endpoint_name,
    factory_name,
    operation_group,
    name_parameter,
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    namespace_poller = Mock()
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        namespace_poller
    )
    fixture_link_provider._await_terminal = Mock()

    linked_client = Mock()
    operations = getattr(linked_client, operation_group)
    resource_poller = Mock()
    operations.begin_delete.return_value = resource_poller
    operations.get.side_effect = [{}, _http_error(404)]
    lro_adapter = mocker.patch(
        "azext_iot.adr.providers.link_persistence.adapt_modeless_lro_poller",
        side_effect=lambda poller: poller,
    )
    fixture_link_provider._wait_for_linked_resource_deleted = (
        LinkProvider._wait_for_linked_resource_deleted
    )
    factory = mocker.patch(
        f"azext_iot.adr.providers.link.{factory_name}",
        return_value=linked_client,
    )
    endpoint = namespace["properties"][section]["endpoints"][endpoint_name]
    parsed_name = endpoint["resourceId"].split("/")[-1]

    result = getattr(fixture_link_provider, f"{kind}_delete")(
        endpoint_name, "namespace", "namespace-rg", wait_sec=0
    )

    assert result is None
    factory.assert_called_once_with(
        fixture_link_provider.cmd.cli_ctx, subscription_id="sub"
    )
    expected_arguments = {
        "resource_group_name": "rg",
        name_parameter: parsed_name,
    }
    operations.begin_delete.assert_called_once_with(**expected_arguments)
    assert operations.get.call_count == 2
    operations.get.assert_called_with(**expected_arguments)
    fixture_link_provider._await_terminal.assert_called_once_with(
        namespace_poller, wait_sec=0
    )
    resource_poller.result.assert_called_once_with()
    lro_adapter.assert_called_once_with(resource_poller)

    namespace_call = (
        fixture_link_provider.client.namespaces.begin_create_or_replace.call_args
    )
    assert namespace_call.kwargs["resource_group_name"] == "namespace-rg"
    replacement = namespace_call.kwargs["resource"]
    assert endpoint_name not in replacement["properties"][section]["endpoints"]
    # Every other endpoint and writable namespace field survives the full PUT.
    assert replacement["properties"]["outboundIdentity"] == {
        "type": "SystemAssigned"
    }
    assert replacement["properties"]["observability"]["enabled"] is True
    assert replacement["tags"] == {"env": "test"}


def test_namespace_replace_body_preserves_existing_endpoint_state():
    replacement = _namespace_replace_body(_namespace_for_delete())

    assert replacement["location"] == "eastus"
    assert replacement["identity"] == {
        "type": "SystemAssigned,UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}},
    }
    assert {"id", "name", "type", "systemData"}.isdisjoint(replacement)
    assert {"uuid", "provisioningState"}.isdisjoint(replacement["properties"])
    assert replacement["properties"]["management"] == {
        "endpoints": {
            "generated": {
                "endpointType": "Microsoft.IoTOperations/instances",
                "resourceId": "/management",
                "scopeId": "scope",
                "address": "https://generated",
            }
        }
    }
    hub = replacement["properties"]["messaging"]["endpoints"]["hub"]
    assert hub == {
        "address": "read-only",
        "deviceAddress": "read-only",
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "resourceId": HUB_ID,
        "inboundCallerIdentity": {"type": "SystemAssigned"},
        "linkingState": "Succeeded",
        "linkingError": {"message": "read-only"},
        "provisioning": {
            "availability": "Available",
            "allocationWeight": 10,
        },
    }
    su = replacement["properties"]["updating"]["endpoints"]["su"]
    assert su["serviceAddress"] == "read-only"
    assert su["linkingState"] == "Succeeded"
    assert "empty" not in replacement["properties"]["updating"]["endpoints"]


def test_namespace_replace_body_requires_location():
    with pytest.raises(AzureResponseError, match="location"):
        _namespace_replace_body({"properties": {}})


def test_link_delete_retries_cleanup_when_linked_resource_is_already_gone(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    linked_client = Mock()
    linked_client.iot_hub_resource.begin_delete.side_effect = _http_error(404)
    linked_client.iot_hub_resource.get.side_effect = _http_error(404)
    fixture_link_provider._wait_for_linked_resource_deleted = (
        LinkProvider._wait_for_linked_resource_deleted
    )
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    fixture_link_provider.hub_delete(
        "hub", "namespace", "namespace-rg", wait_sec=0
    )

    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_called_once()
    replacement = (
        fixture_link_provider.client.namespaces.begin_create_or_replace.call_args.kwargs[
            "resource"
        ]
    )
    assert "hub" not in replacement["properties"]["messaging"]["endpoints"]
    linked_client.iot_hub_resource.get.assert_called_once()


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_link_delete_missing_typed_endpoint_is_not_found(
    fixture_link_provider, kind
):
    fixture_link_provider.client.namespaces.get.return_value = (
        _namespace_for_delete()
    )
    endpoint_name = {"hub": "dps", "dps": "hub", "su": "hub"}[kind]

    with pytest.raises(ResourceNotFoundError, match=endpoint_name):
        getattr(fixture_link_provider, f"{kind}_delete")(
            endpoint_name, "namespace", "rg"
        )

    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_link_delete_rejects_invalid_resource_id_with_endpoint_context(
    fixture_link_provider
):
    namespace = _namespace_for_delete()
    namespace["properties"]["messaging"]["endpoints"]["hub"]["resourceId"] = DPS_ID
    fixture_link_provider.client.namespaces.get.return_value = namespace

    with pytest.raises(
        InvalidArgumentValueError,
        match="Hub endpoint 'hub'.*invalid linked resource ID",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")


def test_link_delete_does_not_remove_concurrently_replaced_endpoint(
    fixture_link_provider, mocker
):
    initial = _namespace_for_delete()
    latest = _namespace_for_delete()
    latest["properties"]["messaging"]["endpoints"]["hub"]["resourceId"] = (
        HUB_ID.replace("/hub", "/replacement")
    )
    fixture_link_provider.client.namespaces.get.side_effect = [initial, latest]
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="has been deleted",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")

    linked_client.iot_hub_resource.begin_delete.assert_called_once()
    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_link_delete_preserves_state_from_final_namespace_reread(
    fixture_link_provider, mocker
):
    initial = _namespace_for_delete()
    latest = _namespace_for_delete()
    latest["tags"] = {"concurrent": "change"}
    latest["properties"]["observability"]["enabled"] = False
    latest["properties"]["messaging"]["endpoints"]["other-hub"][
        "provisioning"
    ] = {"allocationWeight": 77}
    fixture_link_provider.client.namespaces.get.side_effect = [initial, latest]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    fixture_link_provider.hub_delete("hub", "namespace", "namespace-rg")

    replacement = (
        fixture_link_provider.client.namespaces
        .begin_create_or_replace.call_args.kwargs["resource"]
    )
    assert replacement["tags"] == {"concurrent": "change"}
    assert replacement["properties"]["observability"]["enabled"] is False
    assert replacement["properties"]["messaging"]["endpoints"]["other-hub"][
        "provisioning"
    ] == {"allocationWeight": 77}
    assert "hub" not in replacement["properties"]["messaging"]["endpoints"]


def test_link_delete_reports_namespace_put_submission_failure(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.side_effect = (
        _http_error(409)
    )
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="namespace update could not be submitted",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")

    linked_client.iot_hub_resource.begin_delete.assert_called_once()


def test_link_delete_reports_namespace_reread_failure(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        _http_error(503),
    ]
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="namespace could not be read before cleanup",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")

    linked_client.iot_hub_resource.begin_delete.assert_called_once()


def test_link_delete_reports_incomplete_namespace_body(
    fixture_link_provider, mocker
):
    initial = _namespace_for_delete()
    latest = _namespace_for_delete()
    latest.pop("location")
    fixture_link_provider.client.namespaces.get.side_effect = [initial, latest]
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="replacement body could not be built",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")

    linked_client.iot_hub_resource.begin_delete.assert_called_once()


def test_link_delete_reports_namespace_put_completion_failure(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock(
        side_effect=AzureResponseError("endpoint 'hub' is in a 'Failed' state")
    )
    linked_client = Mock()
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="namespace update did not complete.*endpoint 'hub'.*Failed",
    ):
        fixture_link_provider.hub_delete("hub", "namespace", "rg")

    linked_client.iot_hub_resource.begin_delete.assert_called_once()


def test_linked_resource_polling_reraises_non_404():
    with pytest.raises(HttpResponseError):
        wait_for_linked_resource_deleted(
            Mock(side_effect=_http_error(403)), wait_sec=0
        )


def test_linked_resource_polling_times_out(mocker):
    mocker.patch(
        "azext_iot.adr.providers.link_persistence.LRO_POLL_RETRIES", 1
    )
    with pytest.raises(AzureResponseError, match="Timed out"):
        wait_for_linked_resource_deleted(Mock(), wait_sec=0)


def test_link_delete_reraises_non_404_begin_delete_error():
    with pytest.raises(HttpResponseError):
        begin_linked_resource_delete(
            Mock(side_effect=_http_error(409))
        )


def test_link_delete_tolerates_delete_poller_404(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    resource_poller = Mock()
    resource_poller.result.side_effect = _http_error(404)
    linked_client = Mock()
    linked_client.iot_hub_resource.begin_delete.return_value = resource_poller
    linked_client.iot_hub_resource.get.side_effect = _http_error(404)
    fixture_link_provider._wait_for_linked_resource_deleted = (
        LinkProvider._wait_for_linked_resource_deleted
    )
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    fixture_link_provider.hub_delete(
        "hub", "namespace", "namespace-rg", wait_sec=0
    )

    linked_client.iot_hub_resource.get.assert_called_once()


def test_link_delete_reports_delete_poller_non_404_before_namespace_cleanup(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    resource_poller = Mock()
    resource_poller.result.side_effect = _http_error(500)
    linked_client = Mock()
    linked_client.iot_hub_resource.begin_delete.return_value = resource_poller
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="Failed to delete linked resource.*namespace endpoint was not changed",
    ):
        fixture_link_provider.hub_delete(
            "hub", "namespace", "namespace-rg", wait_sec=0
        )
    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_link_delete_reports_poll_timeout_before_namespace_cleanup(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    linked_client = Mock()
    fixture_link_provider._wait_for_linked_resource_deleted.side_effect = (
        AzureResponseError("Timed out")
    )
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )
    with pytest.raises(
        AzureResponseError,
        match="Timed out confirming deletion.*namespace endpoint was not changed",
    ):
        fixture_link_provider.hub_delete(
            "hub", "namespace", "namespace-rg", wait_sec=0
        )
    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_link_delete_reports_get_failure_before_namespace_cleanup(
    fixture_link_provider, mocker
):
    namespace = _namespace_for_delete()
    fixture_link_provider.client.namespaces.get.side_effect = [
        namespace,
        namespace,
    ]
    fixture_link_provider.client.namespaces.begin_create_or_replace.return_value = (
        Mock()
    )
    fixture_link_provider._await_terminal = Mock()
    linked_client = Mock()
    fixture_link_provider._wait_for_linked_resource_deleted.side_effect = (
        _http_error(403)
    )
    mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_hub_service_factory",
        return_value=linked_client,
    )

    with pytest.raises(
        AzureResponseError,
        match="could not be confirmed deleted.*namespace endpoint was not changed",
    ):
        fixture_link_provider.hub_delete(
            "hub", "namespace", "namespace-rg", wait_sec=0
        )
    fixture_link_provider.client.namespaces.begin_create_or_replace.assert_not_called()


def test_remove_provider_methods_are_absent():
    for method in ("hub_remove", "dps_remove", "su_remove"):
        assert not hasattr(LinkProvider, method)
