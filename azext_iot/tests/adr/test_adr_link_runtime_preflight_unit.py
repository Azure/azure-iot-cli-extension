# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock, patch

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_preflight import (
    TargetLookup,
    get_target,
    validate_target_state,
)
from azext_iot.adr.rbac import LinkRbacManager

HUB_ID = (
    "/subscriptions/target-sub/resourceGroups/target-rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)
NS_ID = (
    "/subscriptions/ns-sub/resourceGroups/ns-rg/providers/"
    "Microsoft.DeviceRegistry/namespaces/ns"
)
UAMI = (
    "/subscriptions/target-sub/resourceGroups/target-rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/link"
)


def _provider():
    cmd = MagicMock()
    with patch(
        "azext_iot.adr.providers.base.adr_service_factory"
    ) as factory:
        provider = LinkProvider(cmd)
        provider.client = factory.return_value
    return provider


def _namespace():
    return {
        "id": NS_ID,
        "location": "centraluseuap",
        "identity": {
            "type": "SystemAssigned",
            "principalId": "namespace-principal",
        },
        "properties": {},
    }


def _hub():
    return {
        "id": HUB_ID,
        "location": "centraluseuap",
        "sku": {"name": "S1"},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "hub-system",
            "userAssignedIdentities": {UAMI: {"principalId": "hub-user"}},
        },
        "properties": {
            "provisioningState": "Succeeded",
            "hostName": "hub.azure-devices.net",
        },
    }


def _http_error(status):
    response = MagicMock(status_code=status)
    error = HttpResponseError(message="failure", response=response)
    error.status_code = status
    return error


def test_target_state_accepts_ready_standard_same_region():
    validate_target_state(
        _namespace(), _hub(), "IoT Hub", require_standard_hub=True
    )


@pytest.mark.parametrize(
    "mutator, error_type, message",
    [
        (
            lambda target: target.update(location="eastus"),
            InvalidArgumentValueError,
            "Cross-region",
        ),
        (
            lambda target: target["properties"].update(
                provisioningState="Updating"
            ),
            InvalidArgumentValueError,
            "Succeeded",
        ),
        (
            lambda target: target["sku"].update(name="F1"),
            InvalidArgumentValueError,
            "S-tier",
        ),
        (
            lambda target: target.pop("location"),
            AzureResponseError,
            "location",
        ),
    ],
)
def test_target_state_rejects_ineligible_resource(mutator, error_type, message):
    target = _hub()
    mutator(target)
    with pytest.raises(error_type, match=message):
        validate_target_state(
            _namespace(), target, "IoT Hub", require_standard_hub=True
        )


def test_get_target_uses_resource_id_subscription_and_maps_not_found():
    provider = _provider()
    factory = MagicMock()
    strategy = TargetLookup(
        factory=factory,
        operation_group_name="iot_hub_resource",
        name_parameter="resource_name",
        display_name="IoT Hub",
        require_standard_hub=True,
    )
    operations = factory.return_value.iot_hub_resource
    operations.get.return_value = _hub()
    parsed = {
        "subscription_id": "target-sub",
        "resource_group_name": "target-rg",
        "name": "hub",
    }

    assert get_target(provider.cmd.cli_ctx, parsed, strategy) == _hub()
    factory.assert_called_once_with(
        provider.cmd.cli_ctx, subscription_id="target-sub"
    )

    factory.reset_mock()
    operations.get.side_effect = None
    assert provider._get_target(
        parsed,
        strategy,
    ) == _hub()

    operations.get.side_effect = _http_error(404)
    with pytest.raises(ResourceNotFoundError, match="target-sub"):
        get_target(provider.cmd.cli_ctx, parsed, strategy)

    operations.get.side_effect = _http_error(403)
    with pytest.raises(HttpResponseError):
        get_target(provider.cmd.cli_ctx, parsed, strategy)


def test_preflight_resolves_both_principals_and_runs_authoritative_rbac():
    provider = _provider()
    provider._get_target = MagicMock(return_value=_hub())
    provider._rbac = MagicMock()
    namespace = _namespace()
    inbound = {"type": "UserAssigned", "userAssignedIdentity": UAMI.upper()}
    parsed = {
        "subscription_id": "target-sub",
        "resource_group_name": "target-rg",
        "name": "hub",
    }
    strategy = TargetLookup(
        factory=MagicMock(),
        operation_group_name="iot_hub_resource",
        name_parameter="resource_name",
        display_name="IoT Hub",
        require_standard_hub=True,
    )

    result = provider._preflight_link(
        "hub",
        namespace,
        HUB_ID,
        inbound,
        parsed,
        strategy,
    )

    assert result == _hub()
    provider._rbac.ensure.assert_called_once_with(
        link_type="hub",
        namespace_scope=NS_ID,
        target_scope=HUB_ID,
        namespace_principal_id="namespace-principal",
        linked_principal_id="hub-user",
    )

    requests = []
    provider._preflight_link(
        "hub",
        namespace,
        HUB_ID,
        inbound,
        parsed,
        strategy,
        rbac_requests=requests,
    )
    assert requests == [
        {
            "link_type": "hub",
            "namespace_scope": NS_ID,
            "target_scope": HUB_ID,
            "namespace_principal_id": "namespace-principal",
            "linked_principal_id": "hub-user",
        }
    ]


def test_rbac_manager_is_created_lazily():
    provider = _provider()
    with patch(
        "azext_iot.adr.providers.link.LinkRbacManager"
    ) as manager_type:
        assert provider._rbac_manager() is manager_type.return_value
        assert provider._rbac_manager() is manager_type.return_value
    manager_type.assert_called_once_with(provider.cmd.cli_ctx)


@pytest.mark.parametrize("operation", ["add", "update"])
@pytest.mark.parametrize("outbound_uami", [False, True])
@pytest.mark.parametrize("inbound_uami", [False, True])
@pytest.mark.parametrize("authorized", [False, True])
def test_su_runtime_uses_exact_two_roles_for_selected_identities(
    mocker, operation, outbound_uami, inbound_uami, authorized,
):
    provider = _provider()
    namespace = _namespace()
    namespace["identity"]["type"] = "SystemAssigned,UserAssigned"
    namespace["identity"]["userAssignedIdentities"] = {UAMI: {"principalId": "namespace-user"}}
    if outbound_uami:
        namespace["properties"]["outboundIdentity"] = {
            "type": "UserAssigned", "userAssignedIdentity": UAMI.upper() + "/",
        }
    su_id = HUB_ID.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.DeviceUpdate/updateInstances/su")
    endpoint = {
        "endpointType": "Microsoft.DeviceUpdate/updateInstances",
        "resourceId": su_id, "inboundCallerIdentity": {"type": "SystemAssigned"},
    }
    if operation == "update":
        namespace["properties"]["updating"] = {"endpoints": {"su": endpoint}}
    provider.client.namespaces.get.return_value = namespace
    target = _hub()
    target["id"] = su_id
    provider._get_target = MagicMock(return_value=target)
    provider._wait = MagicMock(return_value={})
    manager = LinkRbacManager(provider.cmd.cli_ctx, cli=MagicMock())
    provider._rbac = manager
    mocker.patch.object(manager, "_assignment_exists", return_value=False)
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    visible = mocker.patch.object(manager, "_wait_for_assignments")
    grants = mocker.patch.object(manager, "_invoke_json", return_value={"id": "assignment"})
    network = mocker.patch("requests.sessions.Session.request", side_effect=AssertionError("Unexpected network/Graph"))
    kwargs = {"mi_user_assigned": UAMI.upper()} if inbound_uami else {"mi_system_assigned": True}
    if operation == "add":
        kwargs["su_resource_id"] = su_id
    invoke = getattr(provider, f"su_{operation}")
    if not authorized:
        with pytest.raises(AzureResponseError, match="No link mutation"):
            invoke("su", "ns", "ns-rg", **kwargs)
        grants.assert_not_called()
        visible.assert_not_called()
        provider.client.namespaces.begin_update.assert_not_called()
    else:
        # This test isolates RBAC and submission. Waited readback/recovery has
        # deterministic service-state coverage in test_adr_link_propagation_unit.
        invoke("su", "ns", "ns-rg", no_wait=True, **kwargs)
        ns_principal = "namespace-user" if outbound_uami else "namespace-principal"
        su_principal = "hub-user" if inbound_uami else "hub-system"
        assert [call.args[0] for call in grants.call_args_list] == [
            f"role assignment create --assignee-object-id '{ns_principal}' "
            f"--assignee-principal-type ServicePrincipal --role 'Contributor' --scope '{su_id}'",
            f"role assignment create --assignee-object-id '{su_principal}' "
            f"--assignee-principal-type ServicePrincipal --role 'Azure Device Registry Contributor' --scope '{NS_ID}'",
        ]
        assert [call.kwargs["subscription"] for call in grants.call_args_list] == ["target-sub", "ns-sub"]
        visible.assert_called_once_with([
            (ns_principal, "Contributor", su_id),
            (su_principal, "Azure Device Registry Contributor", NS_ID),
        ])
        provider.client.namespaces.begin_update.assert_called_once()
        written = provider.client.namespaces.begin_update.call_args.kwargs["properties"]["properties"]
        assert set(written) == {"updating"}
        written_endpoint = written["updating"]["endpoints"]["su"]
        assert written_endpoint["resourceId"] == su_id
        expected_identity = (
            {"type": "UserAssigned", "userAssignedIdentity": UAMI.upper()}
            if inbound_uami else {"type": "SystemAssigned"}
        )
        assert written_endpoint["inboundCallerIdentity"] == expected_identity
    network.assert_not_called()


def test_preflight_requires_namespace_resource_id():
    provider = _provider()
    provider._get_target = MagicMock(return_value=_hub())
    namespace = _namespace()
    namespace.pop("id")

    with pytest.raises(AzureResponseError, match="resource ID"):
        provider._preflight_link(
            "hub",
            namespace,
            HUB_ID,
            None,
            {
                "subscription_id": "target-sub",
                "resource_group_name": "target-rg",
                "name": "hub",
            },
            TargetLookup(
                factory=MagicMock(),
                operation_group_name="iot_hub_resource",
                name_parameter="resource_name",
                display_name="IoT Hub",
                require_standard_hub=True,
            ),
        )


def test_rbac_failure_prevents_namespace_mutation(fixture_link_provider):
    namespace = _namespace()
    namespace["properties"]["provisioning"] = {
        "endpoints": {
            "dps": {
                "endpointType": "Microsoft.Devices/provisioningServices",
                "resourceId": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps",
            }
        }
    }
    fixture_link_provider.client.namespaces.get.return_value = namespace
    fixture_link_provider._preflight_link.side_effect = AzureResponseError(
        "No link mutation was submitted"
    )

    with pytest.raises(AzureResponseError, match="No link mutation"):
        fixture_link_provider.hub_add(
            "hub", "ns", "ns-rg", HUB_ID, mi_system_assigned=True
        )

    fixture_link_provider.client.namespaces.begin_update.assert_not_called()


def test_hub_add_rejects_existing_logical_endpoint_before_preflight(
    fixture_link_provider,
):
    namespace = _namespace()
    namespace["properties"].update(
        {
            "provisioning": {
                "endpoints": {
                    "dps": {
                        "endpointType": "Microsoft.Devices/provisioningServices"
                    }
                }
            },
            "messaging": {
                "endpoints": {
                    "hub": {
                        "endpointType": "Microsoft.Devices/IotHubs",
                        "resourceId": HUB_ID.replace("/hub", "/old"),
                    }
                }
            },
        }
    )
    fixture_link_provider.client.namespaces.get.return_value = namespace

    with pytest.raises(ArgumentUsageError, match="cannot be repointed"):
        fixture_link_provider.hub_add("hub", "ns", "rg", HUB_ID)

    fixture_link_provider._preflight_link.assert_not_called()


def test_dps_projection_uses_subscription_from_linked_resource_id(
    fixture_link_provider, mocker
):
    dps_id = (
        "/subscriptions/other-sub/resourceGroups/dps-rg/providers/"
        "Microsoft.Devices/provisioningServices/dps"
    )
    client = MagicMock()
    client.iot_dps_resource.get.return_value = {
        "properties": {"iotHubs": []}
    }
    factory = mocker.patch(
        "azext_iot.adr.providers.link.adr_iot_service_provisioning_factory",
        return_value=client,
    )

    fixture_link_provider._side_get_dps_resource(dps_id)

    factory.assert_called_once_with(
        fixture_link_provider.cmd.cli_ctx, subscription_id="other-sub"
    )


def test_hub_link_warns_when_classic_dps_allocation_duplicates_target(
    fixture_link_provider, caplog
):
    namespace = _namespace()
    namespace["properties"]["provisioning"] = {
        "endpoints": {
            "dps": {
                "endpointType": "Microsoft.Devices/provisioningServices",
                "resourceId": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.Devices/provisioningServices/dps"
                ),
            }
        }
    }
    fixture_link_provider._side_get_dps_resource = MagicMock(
        return_value={
            "properties": {
                "iotHubs": [{"hostName": "hub.azure-devices.net"}]
            }
        }
    )

    # The shared fixture mocks warning projection for endpoint-shape tests;
    # invoke the implementation explicitly here.
    LinkProvider._warn_if_hub_classically_linked(
        fixture_link_provider,
        namespace,
        {
            "name": "hub",
            "subscription_id": "sub",
            "resource_group_name": "rg",
        },
        _hub(),
    )

    assert "authoritative ADR relationship" in caplog.text


def test_hub_duplicate_warning_ignores_non_dps_endpoint(
    fixture_link_provider, caplog
):
    fixture_link_provider._side_get_dps_resource = MagicMock()
    namespace = _namespace()
    namespace["properties"]["provisioning"] = {
        "endpoints": {
            "future": {
                "endpointType": "Microsoft.Example/futureService",
                "resourceId": "/future",
            }
        }
    }
    LinkProvider._warn_if_hub_classically_linked(
        fixture_link_provider,
        namespace,
        {
            "name": "hub",
            "subscription_id": "sub",
            "resource_group_name": "rg",
        },
        _hub(),
    )
    fixture_link_provider._side_get_dps_resource.assert_not_called()
    assert not caplog.text


def test_dps_add_rejects_occupied_non_dps_endpoint_name(
    fixture_link_provider,
):
    namespace = _namespace()
    namespace["properties"]["provisioning"] = {
        "endpoints": {
            "occupied": {
                "endpointType": "Microsoft.Example/futureService"
            }
        }
    }
    fixture_link_provider.client.namespaces.get.return_value = namespace
    dps_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.Devices/provisioningServices/dps"
    )
    with pytest.raises(ArgumentUsageError, match="already exists"):
        fixture_link_provider.dps_add(
            "occupied", "ns", "rg", dps_id, mi_system_assigned=True
        )


@pytest.mark.parametrize(
    "properties, message",
    [
        (
            {
                "messaging": {
                    "endpoints": {
                        f"hub-{index}": {
                            "endpointType": "Microsoft.Devices/IotHubs"
                        }
                        for index in range(10)
                    }
                }
            },
            "maximum of 10",
        ),
        (
            {
                "provisioning": {
                    "endpoints": {
                        "dps": {
                            "endpointType": "Microsoft.Example/future"
                        }
                    }
                }
            },
            "Provisioning endpoint",
        ),
        (
            {
                "messaging": {
                    "endpoints": {
                        "hub": {
                            "endpointType": "Microsoft.Example/future"
                        }
                    }
                }
            },
            "Messaging endpoint",
        ),
    ],
)
def test_combined_add_rejects_topology_and_name_collisions(
    fixture_link_provider, properties, message
):
    namespace = _namespace()
    namespace["properties"].update(properties)
    fixture_link_provider.client.namespaces.get.return_value = namespace
    dps_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.Devices/provisioningServices/dps"
    )
    with pytest.raises(ArgumentUsageError, match=message):
        fixture_link_provider.link_add(
            "ns",
            "rg",
            "hub",
            HUB_ID,
            "dps",
            dps_id,
            dps_mi_system_assigned=True,
        )
    fixture_link_provider._preflight_link.assert_not_called()
    fixture_link_provider._rbac.ensure_many.assert_not_called()
    fixture_link_provider.client.namespaces.begin_update.assert_not_called()
