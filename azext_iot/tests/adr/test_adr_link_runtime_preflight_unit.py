# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
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
from azext_iot.adr.rbac import HUB_DATA_ROLE, LinkRbacManager

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


@pytest.mark.parametrize("operation", ["dps_add", "hub_add", "link_add", "dps_update", "hub_update"])
@pytest.mark.parametrize("user_assigned", [False, True])
@pytest.mark.parametrize("existing_grant,authorized", [(False, True), (False, False), (True, False)])
def test_link_commands_ensure_dps_hub_grants_before_mutation(
    mocker, operation, user_assigned, existing_grant, authorized,
):
    provider = _provider()
    namespace = _namespace()
    dps_id = HUB_ID.replace("IotHubs/hub", "provisioningServices/dps")
    old_hub = HUB_ID + "-existing"
    selected = {"type": "UserAssigned", "userAssignedIdentity": UAMI} if user_assigned else {"type": "SystemAssigned"}
    dps_endpoint = {
        "endpointType": "Microsoft.Devices/provisioningServices", "resourceId": dps_id,
        "inboundCallerIdentity": selected,
        "linkingState": "Succeeded",
    }
    namespace["properties"]["messaging"] = {"endpoints": {"existing": {
        "endpointType": "Microsoft.Devices/IotHubs", "resourceId": old_hub,
    }}}
    if operation not in ("dps_add", "link_add"):
        namespace["properties"]["provisioning"] = {"endpoints": {"dps": deepcopy(dps_endpoint)}}
    if operation == "dps_update":
        namespace["properties"]["provisioning"]["endpoints"]["dps"]["inboundCallerIdentity"] = (
            {"type": "SystemAssigned"} if user_assigned else {"type": "UserAssigned", "userAssignedIdentity": UAMI}
        )
    if operation == "hub_update":
        namespace["properties"]["messaging"]["endpoints"]["hub"] = {
            "endpointType": "Microsoft.Devices/IotHubs", "resourceId": HUB_ID,
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }
    provider.client.namespaces.get.return_value = namespace
    dps = _hub()
    dps["identity"]["principalId"] = "dps-system"
    dps["identity"]["userAssignedIdentities"][UAMI]["principalId"] = "dps-user"
    provider._get_target = MagicMock(side_effect=lambda _, strategy: dps if strategy.display_name == "DPS" else _hub())
    provider._warn_if_hub_classically_linked = MagicMock()
    manager = provider._rbac = LinkRbacManager(provider.cmd.cli_ctx, cli=MagicMock())
    mocker.patch.object(manager, "_assignment_exists", side_effect=lambda principal, role, _scope:
                        existing_grant or not (principal.startswith("dps-") and role == HUB_DATA_ROLE))
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    permission = mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    mocker.patch.object(manager, "_wait_for_assignments")
    create = mocker.patch.object(manager, "_invoke_json")
    scopes = [HUB_ID] if operation.startswith("hub") else [old_hub]
    if operation == "link_add":
        scopes.append(HUB_ID)
    expected = {
        ("dps-user" if user_assigned else "dps-system", HUB_DATA_ROLE, scope.lower())
        for scope in scopes
    }
    linked = deepcopy(namespace)
    linked["properties"]["provisioning"] = {"endpoints": {"dps": dps_endpoint}}

    def submit(*_, **__):
        assert set(manager.created) == (set() if existing_grant else expected)
        return linked

    mutation = mocker.patch.object(provider, "_patch_link", side_effect=submit)
    kwargs = {"namespace_name": "ns", "resource_group_name": "ns-rg"}
    if operation == "link_add":
        kwargs.update(hub_endpoint_name="hub", hub_resource_id=HUB_ID, dps_endpoint_name="dps", dps_resource_id=dps_id)
        kwargs.update({"dps_mi_user_assigned": UAMI} if user_assigned else {"dps_mi_system_assigned": True})
    else:
        kind, action = operation.split("_")
        kwargs["endpoint_name"] = kind
        if kind == "dps":
            kwargs.update({"mi_user_assigned": UAMI} if user_assigned else {"mi_system_assigned": True})
        elif action == "update":
            kwargs["mi_system_assigned"] = True
        if action == "add":
            kwargs[f"{kind}_resource_id"] = HUB_ID if kind == "hub" else dps_id
    if existing_grant or authorized:
        getattr(provider, operation)(**kwargs)
        assert mutation.call_count == (2 if operation == "link_add" else 1)
        assert set(manager.created) == (set() if existing_grant else expected)
        if existing_grant:
            permission.assert_not_called()
            create.assert_not_called()
        else:
            assert {call.args[1] for call in permission.call_args_list} == {scope.lower() for scope in scopes}
            assert all(call.kwargs["subscription"] == "target-sub" for call in create.call_args_list)
    else:
        with pytest.raises(AzureResponseError, match="No link mutation"):
            getattr(provider, operation)(**kwargs)
        mutation.assert_not_called()
        create.assert_not_called()


def test_namespace_outbound_rotation_does_not_retarget_dps_hub_grants(mocker):
    from azext_iot.adr.providers.namespace import NamespaceProvider
    from azext_iot.adr.rbac import required_assignments

    provider = _provider()
    namespace = _namespace()
    namespace["identity"]["userAssignedIdentities"] = {UAMI: {"principalId": "new-namespace"}}
    namespace["identity"]["type"] = "SystemAssigned,UserAssigned"
    dps_id = HUB_ID.replace("IotHubs/hub", "provisioningServices/dps")
    namespace["properties"] = {
        "provisioning": {"endpoints": {"dps": {
            "endpointType": "Microsoft.Devices/provisioningServices", "resourceId": dps_id,
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}},
        "messaging": {"endpoints": {"hub": {
            "endpointType": "Microsoft.Devices/IotHubs", "resourceId": HUB_ID,
        }}},
    }
    dps = _hub()
    dps["identity"]["principalId"] = "selected-dps"
    provider._get_target = MagicMock(side_effect=lambda _, strategy: dps if strategy.display_name == "DPS" else _hub())
    provider._rbac = MagicMock()
    mocker.patch("azext_iot.adr.providers.link.LinkProvider", return_value=provider)
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=provider.client)
    NamespaceProvider(provider.cmd)._preflight_outbound_identity_change(
        namespace, {"type": "UserAssigned", "userAssignedIdentity": UAMI},
    )
    requests = provider._rbac.ensure_many.call_args.args[0]
    grants = {assignment for request in requests for _, assignment in required_assignments(request)}
    assert ("selected-dps", HUB_DATA_ROLE, HUB_ID.lower()) in grants
    assert ("new-namespace", HUB_DATA_ROLE, HUB_ID) in grants
    assert not any(principal == "namespace-principal" for principal, _, _ in grants)


@pytest.mark.parametrize("properties", [None, {}, {"provisioning": None}, {"provisioning": {"endpoints": None}}])
def test_combined_add_accepts_null_provisioning_without_mutating_snapshot(fixture_link_provider, mocker, properties):
    namespace = {**_namespace(), "properties": properties}
    original = deepcopy(namespace)
    fixture_link_provider.client.namespaces.get.return_value = namespace
    mocker.patch.object(fixture_link_provider, "_patch_link", return_value=_namespace())
    dps_id = HUB_ID.replace("IotHubs/hub", "provisioningServices/dps")
    fixture_link_provider.link_add("ns", "ns-rg", "hub", HUB_ID, "dps", dps_id, dps_mi_system_assigned=True)
    plan = fixture_link_provider._preflight_link.call_args_list[1].kwargs["namespace"]
    assert plan["properties"]["provisioning"]["endpoints"]["dps"]["resourceId"] == dps_id
    assert namespace == original


def test_hub_preflight_rejects_unattached_dps_identity_before_any_grant():
    provider = _provider()
    namespace = _namespace()
    namespace["properties"]["provisioning"] = {"endpoints": {"dps": {
        "endpointType": "Microsoft.Devices/provisioningServices",
        "linkingState": "Succeeded",
        "resourceId": HUB_ID.replace("IotHubs/hub", "provisioningServices/dps"),
        "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI + "-unattached"},
    }}}
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = MagicMock(return_value=_hub())
    provider._rbac = MagicMock()
    with pytest.raises(InvalidArgumentValueError, match="not attached to DPS"):
        provider.hub_add("hub", "ns", "ns-rg", HUB_ID, no_wait=True)
    provider._rbac.ensure.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


@pytest.mark.parametrize("operation", ["add", "update"])
@pytest.mark.parametrize("outbound_uami", [False, True])
@pytest.mark.parametrize("inbound_uami", [False, True])
@pytest.mark.parametrize("authorized", [False, True])
def test_dps_runtime_grants_self_access_to_selected_outbound_identity(
    mocker, operation, outbound_uami, inbound_uami, authorized,
):
    provider = _provider()
    namespace = _namespace()
    namespace["identity"]["type"] = "SystemAssigned,UserAssigned"
    namespace["identity"]["userAssignedIdentities"] = {UAMI: {"principalId": "namespace-user"}}
    if outbound_uami:
        namespace["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI}
    dps_id = HUB_ID.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.Devices/provisioningServices/dps")
    if operation == "update":
        namespace["properties"]["provisioning"] = {"endpoints": {"dps": {
            "endpointType": "Microsoft.Devices/provisioningServices", "resourceId": dps_id,
            "inboundCallerIdentity": {"type": "SystemAssigned"},
        }}}
    provider.client.namespaces.get.return_value = namespace
    target = _hub()
    target["id"] = dps_id
    provider._get_target = MagicMock(return_value=target)
    manager = LinkRbacManager(provider.cmd.cli_ctx, cli=MagicMock())
    provider._rbac = manager
    mocker.patch.object(manager, "_assignment_exists", return_value=False)
    mocker.patch.object(manager, "_current_assignee_object_id", return_value="caller")
    mocker.patch.object(manager, "_caller_can_assign", return_value=authorized)
    visible = mocker.patch.object(manager, "_wait_for_assignments")
    grants = mocker.patch.object(manager, "_invoke_json")
    kwargs = {"mi_user_assigned": UAMI} if inbound_uami else {"mi_system_assigned": True}
    if operation == "add":
        kwargs["dps_resource_id"] = dps_id
    invoke = getattr(provider, f"dps_{operation}")
    if not authorized:
        with pytest.raises(AzureResponseError, match="No link mutation"):
            invoke("dps", "ns", "ns-rg", **kwargs)
        grants.assert_not_called()
        visible.assert_not_called()
        provider.client.namespaces.begin_update.assert_not_called()
        return
    invoke("dps", "ns", "ns-rg", no_wait=True, **kwargs)
    outbound = "namespace-user" if outbound_uami else "namespace-principal"
    inbound = "hub-user" if inbound_uami else "hub-system"
    expected = [
        (outbound, "Contributor", dps_id),
        (inbound, "Azure Device Registry Contributor", NS_ID),
        (inbound, "Reader", NS_ID),
        (outbound, "Azure Device Registry Administrator", NS_ID),
        (outbound, "Reader", "/subscriptions/ns-sub/resourceGroups/ns-rg"),
        (outbound, "Reader", "/subscriptions/target-sub/resourceGroups/target-rg"),
    ]
    assert [call.args[0] for call in grants.call_args_list] == [
        f"role assignment create --assignee-object-id '{principal}' "
        f"--assignee-principal-type ServicePrincipal --role '{role}' --scope '{scope}'"
        for principal, role, scope in expected
    ]
    assert [call.kwargs["subscription"] for call in grants.call_args_list] == [
        "target-sub", "ns-sub", "ns-sub", "ns-sub", "ns-sub", "target-sub",
    ]
    visible.assert_called_once_with(expected, strict=False)
    provider.client.namespaces.begin_update.assert_called_once()


@pytest.mark.parametrize("missing", ["system-type", "system-principal"])
def test_dps_outbound_uami_cannot_hide_missing_namespace_system_identity(missing):
    provider = _provider()
    namespace = _namespace()
    namespace["identity"]["type"] = "SystemAssigned,UserAssigned"
    namespace["identity"]["userAssignedIdentities"] = {UAMI: {"principalId": "namespace-user"}}
    namespace["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI}
    if missing == "system-type":
        namespace["identity"]["type"] = "UserAssigned"
    else:
        namespace["identity"].pop("principalId")
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = MagicMock(return_value=_hub())
    provider._rbac = MagicMock()
    dps_id = HUB_ID.replace("Microsoft.Devices/IotHubs/hub", "Microsoft.Devices/provisioningServices/dps")
    error_type = InvalidArgumentValueError if missing == "system-type" else AzureResponseError
    with pytest.raises(error_type, match="system-assigned identity"):
        provider.dps_add("dps", "ns", "ns-rg", dps_id, mi_system_assigned=True)
    provider._rbac.ensure.assert_not_called()
    provider.client.namespaces.begin_update.assert_not_called()


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
                "linkingState": "Succeeded",
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
                        "endpointType": "Microsoft.Devices/provisioningServices",
                        "linkingState": "Succeeded",
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
