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


# Stale DPS iotHubs / deleted linked resources (ADO 40494597).
_STALE_UAMI = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi"
_STALE_HUB_A = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub-a"
_STALE_HUB_B = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub-b"
_STALE_DPS = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps"


def _stale_target(resource_id, name, **properties):
    return {
        "id": resource_id,
        "location": "centraluseuap",
        "sku": {"name": "S1"},
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": f"{name}-system",
            "userAssignedIdentities": {_STALE_UAMI: {"principalId": f"{name}-user"}},
        },
        "properties": {"provisioningState": "Succeeded", "hostName": f"{name}.azure-devices.net", **properties},
    }


def _stale_namespace(hub_b_state="LinkedResourceDeleted", dps_state="Succeeded"):
    hubs = {"hub-a": {
        "endpointType": "Microsoft.Devices/IotHubs", "resourceId": _STALE_HUB_A,
        "inboundCallerIdentity": {"type": "SystemAssigned"}, "linkingState": "Succeeded",
    }}
    if hub_b_state:
        hubs["hub-b"] = {
            "endpointType": "Microsoft.Devices/IotHubs", "resourceId": _STALE_HUB_B,
            "inboundCallerIdentity": {"type": "SystemAssigned"}, "linkingState": hub_b_state,
        }
    return {
        "id": NS_ID,
        "location": "centraluseuap",
        "identity": {
            "type": "SystemAssigned,UserAssigned",
            "principalId": "namespace-system",
            "userAssignedIdentities": {_STALE_UAMI: {"principalId": "namespace-user"}},
        },
        "properties": {
            "provisioningState": "Succeeded",
            "messaging": {"endpoints": hubs},
            "provisioning": {"endpoints": {"dps": {
                "endpointType": "Microsoft.Devices/provisioningServices", "resourceId": _STALE_DPS,
                "inboundCallerIdentity": {"type": "SystemAssigned"}, "linkingState": dps_state,
            }}},
        },
    }


def _stale_lookup(missing=("hub-b",)):
    def lookup(parsed, _strategy):
        name = parsed["name"]
        if name in missing:
            raise ResourceNotFoundError(f"'{name}' was not found")
        if name == "dps":
            return _stale_target(_STALE_DPS, "dps", iotHubs=[
                {"name": "hub-a.azure-devices.net"}, {"name": "hub-b.azure-devices.net"},
            ])
        return _stale_target(_STALE_HUB_A, name)
    return MagicMock(side_effect=lookup)


def _looked_up(provider):
    return [call.args[0]["name"] for call in provider._get_target.call_args_list]


def _granted_scopes(requests):
    from azext_iot.adr.rbac import required_assignments

    return {scope.lower() for request in requests for _, (_, _, scope) in required_assignments(request)}


@pytest.mark.parametrize(
    "endpoint, expected",
    [
        ({"linkingState": "LinkedResourceDeleted"}, True),
        ({"linkingState": "linkedresourcedeleted"}, True),
        ({"provisioningStatus": {"status": "LinkedResourceDeleted"}}, True),
        ({"status": {"status": "LinkedResourceDeleted"}}, True),
        ({"linkingState": "Succeeded", "status": {"status": "LinkedResourceDeleted"}}, False),
        ({"linkingState": "Failed"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_is_linked_resource_deleted(endpoint, expected):
    from azext_iot.adr.topology import is_linked_resource_deleted

    assert is_linked_resource_deleted(endpoint) is expected


# "Succeeded": ADR has not yet reported the deleted Hub, so only its 404 identifies it.
@pytest.mark.parametrize("hub_b_state", ["LinkedResourceDeleted", None, "Succeeded"])
@pytest.mark.parametrize("identity", [{"mi_user_assigned": _STALE_UAMI}, {"mi_system_assigned": True}])
def test_dps_update_ignores_stale_classic_hubs_and_deleted_hub_links(hub_b_state, identity):
    provider = _provider()
    provider.client.namespaces.get.return_value = _stale_namespace(hub_b_state)
    provider._get_target = _stale_lookup()
    provider._rbac = MagicMock()
    provider._patch_link = MagicMock(return_value="SUBMITTED")

    assert provider.dps_update("dps", "ns", "rg", no_wait=True, **identity) == "SUBMITTED"

    provider._patch_link.assert_called_once()
    assert _looked_up(provider).count("hub-b") == (1 if hub_b_state == "Succeeded" else 0)
    request = provider._rbac.ensure.call_args.kwargs
    assert request["hub_scopes"] == (_STALE_HUB_A.lower(),)
    assert _STALE_HUB_B.lower() not in _granted_scopes([request])


@pytest.mark.parametrize("hub_b_state", ["LinkedResourceDeleted", None])
def test_failed_dps_update_still_requires_classic_hubs_to_be_linked(hub_b_state):
    provider = _provider()
    provider.client.namespaces.get.return_value = _stale_namespace(hub_b_state, dps_state="Failed")
    provider._get_target = _stale_lookup()
    provider._rbac = MagicMock()
    provider._patch_link = MagicMock()

    with pytest.raises(InvalidArgumentValueError, match="hub-b"):
        provider.dps_update("dps", "ns", "rg", mi_system_assigned=True, no_wait=True)

    provider._patch_link.assert_not_called()
    provider._rbac.ensure.assert_not_called()


def test_dps_add_still_requires_classic_hubs_to_be_linked():
    provider = _provider()
    namespace = _stale_namespace(None)
    namespace["properties"]["provisioning"] = {"endpoints": {}}
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = _stale_lookup()
    provider._rbac = MagicMock()
    provider._patch_link = MagicMock()

    with pytest.raises(InvalidArgumentValueError, match="hub-b"):
        provider.dps_add("dps", "ns", "rg", _STALE_DPS, mi_system_assigned=True, no_wait=True)

    provider._patch_link.assert_not_called()


def _run_outbound_preflight(mocker, namespace, lookup, outbound=None):
    from azext_iot.adr.providers.namespace import NamespaceProvider

    provider = _provider()
    provider._get_target = lookup
    provider._rbac = MagicMock()
    mocker.patch("azext_iot.adr.providers.link.LinkProvider", return_value=provider)
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=provider.client)
    warning = mocker.patch("azext_iot.adr.providers.namespace.logger.warning")
    original = deepcopy(namespace)
    NamespaceProvider(provider.cmd)._preflight_outbound_identity_change(
        namespace, outbound or {"type": "UserAssigned", "userAssignedIdentity": _STALE_UAMI},
    )
    assert namespace == original
    return provider, provider._rbac.ensure_many.call_args.args[0], warning


@pytest.mark.parametrize(
    "hub_b_state, missing, expect_get, expect_warning",
    [
        ("LinkedResourceDeleted", ("hub-b",), False, True),
        ("Succeeded", ("hub-b",), True, True),
        (None, ("hub-b",), False, False),
    ],
)
@pytest.mark.parametrize("outbound", [
    {"type": "UserAssigned", "userAssignedIdentity": _STALE_UAMI}, {"type": "SystemAssigned"},
])
def test_outbound_identity_preflight_skips_deleted_hubs_and_stale_classic_hubs(
    mocker, hub_b_state, missing, expect_get, expect_warning, outbound,
):
    provider, requests, warning = _run_outbound_preflight(
        mocker, _stale_namespace(hub_b_state), _stale_lookup(missing), outbound,
    )

    assert _looked_up(provider).count("hub-b") == (1 if expect_get else 0)
    assert {(request["link_type"], request["target_scope"]) for request in requests} == {
        ("dps", _STALE_DPS), ("hub", _STALE_HUB_A),
    }
    principal = "namespace-user" if outbound["type"] == "UserAssigned" else "namespace-system"
    assert all(request["namespace_principal_id"] == principal for request in requests)
    assert all(request["hub_scopes"] == (_STALE_HUB_A.lower(),) for request in requests)
    assert _STALE_HUB_B.lower() not in _granted_scopes(requests)
    assert warning.called is expect_warning
    if expect_warning:
        assert "messaging/hub-b" in warning.call_args.args[1]


def test_outbound_identity_preflight_fetches_each_linked_target_once(mocker):
    provider, requests, _ = _run_outbound_preflight(mocker, _stale_namespace("Succeeded"), _stale_lookup(()))

    assert sorted(_looked_up(provider)) == ["dps", "hub-a", "hub-b"]
    assert all(request["dps_principal_id"] for request in requests if request["link_type"] == "hub")


def test_outbound_identity_preflight_skips_deleted_dps_without_dps_hub_grants(mocker):
    namespace = _stale_namespace(None, dps_state="LinkedResourceDeleted")
    provider, requests, warning = _run_outbound_preflight(mocker, namespace, _stale_lookup(("dps",)))

    assert "dps" not in _looked_up(provider)
    assert [(request["link_type"], request["target_scope"]) for request in requests] == [("hub", _STALE_HUB_A)]
    assert "dps_principal_id" not in requests[0]
    assert "provisioning/dps" in warning.call_args.args[1]


def test_outbound_identity_preflight_propagates_non_404_target_errors(mocker):
    from azext_iot.adr.providers.namespace import NamespaceProvider

    provider = _provider()
    provider._get_target = MagicMock(side_effect=_http_error(403))
    provider._rbac = MagicMock()
    mocker.patch("azext_iot.adr.providers.link.LinkProvider", return_value=provider)
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=provider.client)
    with pytest.raises(HttpResponseError):
        NamespaceProvider(provider.cmd)._preflight_outbound_identity_change(
            _stale_namespace("Succeeded"), {"type": "SystemAssigned"},
        )
    provider._rbac.ensure_many.assert_not_called()


def test_dps_update_recovery_recomputes_the_same_grants_without_the_missing_hub(mocker):
    provider = _provider()
    namespace = _stale_namespace("Succeeded")
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = _stale_lookup()
    provider._rbac = MagicMock()
    recovery = mocker.patch("azext_iot.adr.providers.link.LinkRecovery")

    provider.dps_update("dps", "ns", "rg", mi_system_assigned=True)

    stored = provider._link_requests[("dps", _STALE_DPS.casefold())]
    assert stored[0]["hub_scopes"] == (_STALE_HUB_A.lower(),)
    verify = recovery.call_args.args[6]
    deadline = MagicMock(call=lambda fn, *args: fn(*args), remaining=MagicMock(return_value=60))
    verify(namespace, deadline)
    provider._rbac.verify_many.assert_called_once()
    assert provider._rbac.verify_many.call_args.args[0] == stored


def test_dps_update_propagates_non_404_hub_errors():
    provider = _provider()
    provider.client.namespaces.get.return_value = _stale_namespace("Succeeded")
    lookup = _stale_lookup(())

    def failing(parsed, strategy):
        if parsed["name"] == "hub-b":
            raise _http_error(403)
        return lookup(parsed, strategy)

    provider._get_target = MagicMock(side_effect=failing)
    provider._rbac = MagicMock()
    provider._patch_link = MagicMock()
    with pytest.raises(HttpResponseError):
        provider.dps_update("dps", "ns", "rg", mi_system_assigned=True, no_wait=True)
    provider._patch_link.assert_not_called()


def test_combined_batch_add_keeps_missing_existing_hub_out_of_dps_grants(mocker):
    provider = _provider()
    namespace = _stale_namespace("Succeeded")
    namespace["properties"]["provisioning"] = {"endpoints": {}}
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = _stale_lookup()
    provider._rbac = MagicMock()
    batch = mocker.patch.object(provider, "_patch_link_batch", return_value="SUBMITTED")
    hub_c = _STALE_HUB_A.replace("hub-a", "hub-c")

    provider.link_add("ns", "rg", "hub-c", hub_c, "dps", _STALE_DPS, dps_mi_system_assigned=True)

    batch.assert_called_once()
    assert _looked_up(provider).count("hub-b") == 1
    requests = provider._rbac.ensure_many.call_args.args[0]
    dps_request = next(request for request in requests if request["link_type"] == "dps")
    assert dps_request["hub_scopes"] == tuple(sorted({_STALE_HUB_A.lower(), hub_c.lower()}))
    assert _STALE_HUB_B.lower() not in _granted_scopes(requests)


def _verify_recovery(recovery, namespace):
    deadline = MagicMock(call=lambda fn, *args: fn(*args), remaining=MagicMock(return_value=60))
    recovery.call_args.args[6](namespace, deadline)


# None: no DPS link. A recovery PATCH retries the then-Failed Hub, which ADR rejects without a linked DPS.
@pytest.mark.parametrize("dps_state", ["LinkedResourceDeleted", "Succeeded", "Failed", None])
def test_hub_identity_change_is_not_blocked_by_a_deleted_dps(mocker, dps_state):
    provider = _provider()
    namespace = _stale_namespace(None, dps_state=dps_state)
    if dps_state is None:
        namespace["properties"]["provisioning"] = {"endpoints": {}}
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = _stale_lookup(("dps",))
    provider._rbac = MagicMock()
    provider._side_get_dps_resource = MagicMock(return_value=None)
    recovery = mocker.patch("azext_iot.adr.providers.link.LinkRecovery")

    provider.hub_update("hub-a", "ns", "rg", mi_user_assigned=_STALE_UAMI)

    looked_up = dps_state in ("Succeeded", "Failed")
    assert ("dps" in _looked_up(provider)) is looked_up
    assert provider._side_get_dps_resource.called is looked_up
    stored = provider._link_requests[("hub", _STALE_HUB_A.casefold())]
    assert "dps_principal_id" not in stored[0]
    recovery.return_value.run.assert_called_once()
    if dps_state in ("Failed", None):
        with pytest.raises(AzureResponseError, match="no Hub recovery PATCH"):
            _verify_recovery(recovery, namespace)
        provider._rbac.verify_many.assert_not_called()
        return
    _verify_recovery(recovery, namespace)
    assert provider._rbac.verify_many.call_args.args[0] == stored


def test_hub_add_with_a_deleted_dps_is_allowed_with_guidance(mocker):
    provider = _provider()
    namespace = _stale_namespace(None, dps_state="LinkedResourceDeleted")
    provider.client.namespaces.get.return_value = namespace
    provider._get_target = _stale_lookup(("dps",))
    provider._rbac = MagicMock()
    recovery = mocker.patch("azext_iot.adr.providers.link.LinkRecovery")
    warning = mocker.patch("azext_iot.adr.providers.link.logger.warning")

    provider.hub_add("hub-b", "ns", "rg", _STALE_HUB_B, mi_user_assigned=_STALE_UAMI)

    assert "dps" not in _looked_up(provider)
    assert any("link dps remove" in call.args[0] for call in warning.call_args_list)
    recovery.return_value.run.assert_called_once()
    _verify_recovery(recovery, namespace)


@pytest.mark.parametrize("dps_state, allowed", [("LinkedResourceDeleted", True), ("Failed", False)])
@pytest.mark.parametrize("command", ["hub update", "link update"])
def test_failed_hub_retry_follows_the_adr_dps_dependency(mocker, dps_state, allowed, command):
    provider = _provider()
    provider.client.namespaces.get.return_value = _stale_namespace("Failed", dps_state=dps_state)
    provider._get_target = _stale_lookup(("dps",))
    provider._rbac = MagicMock()
    recovery = mocker.patch("azext_iot.adr.providers.link.LinkRecovery")
    batch = mocker.patch.object(provider, "_patch_link_batch")
    retry = (
        (lambda: provider.hub_update("hub-b", "ns", "rg")) if command == "hub update"
        else (lambda: provider.link_update("ns", "rg", hub_endpoint_names=["hub-b"]))
    )

    if not allowed:
        with pytest.raises(ArgumentUsageError):
            retry()
        provider._rbac.ensure.assert_not_called()
        return
    retry()
    assert "dps" not in _looked_up(provider)
    assert recovery.return_value.run.called or batch.called
