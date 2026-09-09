# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
import inspect
from textwrap import dedent
from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot import _factory
from azext_iot.adr.common import build_managed_service_identity
from azext_iot.adr.providers.update_instance import UpdateInstanceProvider
from azext_iot.sdk.deviceupdate.duregistry.operations import (
    UpdateInstancesOperations,
)

RG = "test-rg"
INSTANCE = "test-update-instance"
UAMI_ID = (
    "/subscriptions/sub/resourceGroups/rg/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
)


@pytest.fixture()
def update_instance_provider():
    with patch(
        "azext_iot.adr.providers.update_instance."
        "adr_update_instance_service_factory"
    ) as factory:
        client = Mock()
        factory.return_value = client
        provider = UpdateInstanceProvider(Mock(cli_ctx=Mock()))
        yield provider


@pytest.mark.parametrize(
    "system_assigned, user_assigned, expected",
    [
        (None, None, None),
        (False, None, {"type": "None"}),
        (True, None, {"type": "SystemAssigned"}),
        (
            None,
            [UAMI_ID],
            {
                "type": "UserAssigned",
                "userAssignedIdentities": {UAMI_ID: {}},
            },
        ),
        (
            True,
            [UAMI_ID, UAMI_ID.upper()],
            {
                "type": "SystemAssigned,UserAssigned",
                "userAssignedIdentities": {UAMI_ID: {}},
            },
        ),
    ],
)
def test_build_managed_service_identity(system_assigned, user_assigned, expected):
    assert build_managed_service_identity(system_assigned, user_assigned) == expected


@pytest.mark.parametrize(
    "resource_id",
    [
        "not-an-id",
        "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/a",
        f"{UAMI_ID}/children/child",
    ],
)
def test_build_managed_service_identity_rejects_invalid_uami(resource_id):
    with pytest.raises(InvalidArgumentValueError):
        build_managed_service_identity(None, [resource_id])


def test_check_name_uses_update_instance_resource_type(update_instance_provider):
    expected = {"nameAvailable": True}
    operation = update_instance_provider.client.update_instances.check_name_availability
    operation.return_value = expected

    assert update_instance_provider.check_name(INSTANCE) == expected
    operation.assert_called_once_with(
        {
            "name": INSTANCE,
            "type": "Microsoft.DeviceUpdate/updateInstances",
        }
    )


def test_list_selects_subscription_or_resource_group_operation(
    update_instance_provider,
):
    operations = update_instance_provider.client.update_instances
    operations.list_by_subscription.return_value = [{"name": "subscription"}]
    operations.list_by_resource_group.return_value = [{"name": "group"}]

    assert update_instance_provider.list() == [{"name": "subscription"}]
    assert update_instance_provider.list(RG) == [{"name": "group"}]
    operations.list_by_subscription.assert_called_once_with()
    operations.list_by_resource_group.assert_called_once_with(resource_group_name=RG)


def test_show_calls_generated_sdk(update_instance_provider):
    expected = {"name": INSTANCE}
    update_instance_provider.client.update_instances.get.return_value = expected

    assert update_instance_provider.show(INSTANCE, RG) == expected
    update_instance_provider.client.update_instances.get.assert_called_once_with(
        resource_group_name=RG,
        update_instance_name=INSTANCE,
    )


def test_wait_uses_standard_arm_poller(update_instance_provider):
    poller = Mock()
    with patch(
        "azext_iot.adr.providers.update_instance."
        "provider_base.wait_for_terminal_state",
        return_value={"name": INSTANCE},
    ) as wait:
        assert update_instance_provider._await_terminal(poller, wait_sec=0) == {
            "name": INSTANCE
        }

    wait.assert_called_once_with(poller, wait_sec=0)


@pytest.mark.parametrize(
    "method_name,begin_name,kwargs",
    [
        (
            "create",
            "begin_create",
            {"location": "eastus2"},
        ),
        (
            "update",
            "begin_update",
            {"tags": {"env": "test"}},
        ),
        (
            "delete",
            "begin_delete",
            {},
        ),
    ],
)
def test_all_update_instance_mutations_return_adapted_poller_for_no_wait(
    update_instance_provider,
    method_name,
    begin_name,
    kwargs,
):
    raw_poller = object()
    adapted_poller = object()
    begin_operation = getattr(
        update_instance_provider.client.update_instances,
        begin_name,
    )
    begin_operation.return_value = raw_poller

    with patch(
        "azext_iot.adr.providers.update_instance.adapt_modeless_lro_poller",
        return_value=adapted_poller,
    ) as adapter:
        result = getattr(update_instance_provider, method_name)(
            INSTANCE,
            RG,
            no_wait=True,
            **kwargs,
        )

    assert result is adapted_poller
    begin_operation.assert_called_once()
    adapter.assert_called_once_with(raw_poller)


def test_every_update_instance_begin_call_is_wrapped_by_modeless_adapter():
    import azext_iot.adr.providers.update_instance as module

    tree = ast.parse(inspect.getsource(module))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    begin_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"begin_create", "begin_update", "begin_delete"}
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "update_instances"
    ]

    assert {node.func.attr for node in begin_calls} == {
        "begin_create",
        "begin_update",
        "begin_delete",
    }
    assert all(
        isinstance(parents.get(node), ast.Call)
        and isinstance(parents[node].func, ast.Name)
        and parents[node].func.id == "adapt_modeless_lro_poller"
        for node in begin_calls
    )


def test_generated_update_instance_callbacks_remain_unpatched():
    """Keep the temporary repair at CLI call sites, outside generated SDK code."""
    tree = ast.parse(dedent(inspect.getsource(UpdateInstancesOperations)))
    operation_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef)
    )
    callbacks = {}
    for method in operation_class.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if method.name not in {"begin_create", "begin_update", "begin_delete"}:
            continue
        callbacks[method.name] = next(
            node
            for node in method.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_long_running_output"
        )

    assert set(callbacks) == {
        "begin_create",
        "begin_update",
        "begin_delete",
    }
    for callback in callbacks.values():
        assert [argument.arg for argument in callback.args.args] == [
            "pipeline_response"
        ]
    for operation_name in ("begin_create", "begin_update"):
        assert any(
            isinstance(node, ast.Name)
            and node.id == "response"
            and isinstance(node.ctx, ast.Load)
            for node in ast.walk(callbacks[operation_name])
        )
    assert not any(
        isinstance(node, ast.Name)
        and node.id == "adapt_modeless_lro_poller"
        for node in ast.walk(operation_class)
    )


def test_create_builds_complete_resource_and_waits(update_instance_provider):
    expected = {"name": INSTANCE}
    poller = Mock()
    poller.result.return_value = expected
    operations = update_instance_provider.client.update_instances
    operations.begin_create.return_value = poller

    result = update_instance_provider.create(
        update_instance_name=INSTANCE,
        resource_group_name=RG,
        location="eastus2",
        tags={"env": "test"},
        mi_system_assigned=True,
        mi_user_assigned=[UAMI_ID],
    )

    assert result == expected
    operations.begin_create.assert_called_once_with(
        resource_group_name=RG,
        update_instance_name=INSTANCE,
        resource={
            "location": "eastus2",
            "properties": {},
            "tags": {"env": "test"},
            "identity": {
                "type": "SystemAssigned,UserAssigned",
                "userAssignedIdentities": {UAMI_ID: {}},
            },
        },
    )
    poller.result.assert_called_once_with()


def test_create_resolves_location_and_supports_no_wait(
    update_instance_provider,
):
    poller = Mock()
    operations = update_instance_provider.client.update_instances
    operations.begin_create.return_value = poller
    update_instance_provider._ensure_location = Mock(return_value="westus2")

    result = update_instance_provider.create(
        update_instance_name=INSTANCE,
        resource_group_name=RG,
        no_wait=True,
    )

    assert result is poller
    update_instance_provider._ensure_location.assert_called_once_with(
        update_instance_provider.cmd.cli_ctx, RG, None
    )
    assert operations.begin_create.call_args.kwargs["resource"] == {
        "location": "westus2",
        "properties": {},
    }
    poller.result.assert_not_called()


def test_create_propagates_existing_instance_lookup_error(
    update_instance_provider,
):
    error = HttpResponseError(message="service unavailable")
    error.status_code = 503
    operations = update_instance_provider.client.update_instances
    operations.check_name_availability.return_value = {
        "nameAvailable": False
    }
    operations.get.side_effect = error

    with pytest.raises(HttpResponseError, match="service unavailable"):
        update_instance_provider.create(INSTANCE, RG)

    operations.begin_create.assert_not_called()


@pytest.mark.parametrize(
    "identity",
    [
        {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                UAMI_ID: {
                    "principalId": "principal",
                    "clientId": "client",
                }
            },
        },
        {"type": "SystemAssigned", "principalId": "principal"},
        {"type": "None"},
        None,
    ],
)
def test_create_upsert_preserves_unspecified_identity_tags_and_state(
    update_instance_provider, identity
):
    current = {
        "id": (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/updateInstances/test-update-instance"
        ),
        "location": "centraluseuap",
        "tags": {"existing": "tag"},
        "properties": {
            "provisioningState": "Succeeded",
            "serviceAddress": "https://service",
            "linking": {"state": "Succeeded"},
        },
    }
    if identity is not None:
        current["identity"] = identity
    operations = update_instance_provider.client.update_instances
    operations.check_name_availability.return_value = {
        "nameAvailable": False
    }
    operations.get.return_value = current
    operations.begin_create.return_value.result.return_value = {
        "name": INSTANCE
    }
    update_instance_provider._ensure_location = Mock()

    update_instance_provider.create(INSTANCE, RG)

    body = operations.begin_create.call_args.kwargs["resource"]
    assert body["location"] == "centraluseuap"
    assert body["tags"] == {"existing": "tag"}
    assert body["properties"] == {}
    if identity is None:
        assert "identity" not in body
    elif identity["type"] == "UserAssigned":
        assert body["identity"] == {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        }
    else:
        assert body["identity"] == {"type": identity["type"]}
    update_instance_provider._ensure_location.assert_not_called()


def test_create_upsert_blocks_replacing_active_identity(
    update_instance_provider,
):
    namespace_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/namespaces/ns"
    )
    instance_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceUpdate/updateInstances/test-update-instance"
    )
    operations = update_instance_provider.client.update_instances
    operations.check_name_availability.return_value = {
        "nameAvailable": False
    }
    operations.get.return_value = {
        "id": instance_id,
        "location": "centraluseuap",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {UAMI_ID: {}},
        },
        "properties": {
            "linking": {"namespaceResourceId": namespace_id}
        },
    }
    registry = Mock()
    registry.namespaces.get.return_value = {
        "properties": {
            "updating": {
                "endpoints": {
                    "su": {
                        "resourceId": instance_id,
                        "inboundCallerIdentity": {
                            "type": "UserAssigned",
                            "userAssignedIdentity": UAMI_ID,
                        },
                    }
                }
            }
        }
    }
    replacement = UAMI_ID.replace("identity", "replacement")

    with patch(
        "azext_iot.adr.providers.update_instance.adr_service_factory",
        return_value=registry,
    ), pytest.raises(ArgumentUsageError, match="active ADR link"):
        update_instance_provider.create(
            INSTANCE,
            RG,
            mi_user_assigned=[replacement],
        )

    operations.begin_create.assert_not_called()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"tags": {}}, {"tags": {}}),
        (
            {"mi_system_assigned": False},
            {"identity": {"type": "None"}},
        ),
        (
            {"mi_user_assigned": [UAMI_ID]},
            {
                "identity": {
                    "type": "UserAssigned",
                    "userAssignedIdentities": {UAMI_ID: {}},
                }
            },
        ),
    ],
)
def test_update_builds_patch_and_waits(update_instance_provider, kwargs, expected):
    poller = Mock()
    poller.result.return_value = {"name": INSTANCE}
    operations = update_instance_provider.client.update_instances
    operations.begin_update.return_value = poller
    operations.get.return_value = {
        "id": (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DeviceUpdate/updateInstances/test-update-instance"
        ),
        "properties": {},
    }

    assert update_instance_provider.update(INSTANCE, RG, **kwargs) == {"name": INSTANCE}
    operations.begin_update.assert_called_once_with(
        resource_group_name=RG,
        update_instance_name=INSTANCE,
        properties=expected,
    )


def test_update_rejects_empty_patch(update_instance_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
        update_instance_provider.update(INSTANCE, RG)
    update_instance_provider.client.update_instances.begin_update.assert_not_called()


def test_update_supports_no_wait(update_instance_provider):
    poller = Mock()
    update_instance_provider.client.update_instances.begin_update.return_value = poller

    result = update_instance_provider.update(
        INSTANCE, RG, tags={"env": "test"}, no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()


def test_delete_waits_and_supports_no_wait(update_instance_provider):
    first_poller = Mock()
    first_poller.result.return_value = None
    second_poller = Mock()
    operation = update_instance_provider.client.update_instances.begin_delete
    operation.side_effect = [first_poller, second_poller]

    assert update_instance_provider.delete(INSTANCE, RG) is None
    assert update_instance_provider.delete(INSTANCE, RG, no_wait=True) is second_poller
    assert operation.call_count == 2
    first_poller.result.assert_called_once_with()
    second_poller.result.assert_not_called()


def test_update_instance_factory_uses_generated_sdk_and_canary_arm_endpoint():
    cli_ctx = Mock()
    client_path = (
        "azext_iot.sdk.deviceupdate.duregistry.DeviceUpdateClient"
    )
    with patch(
        "azure.cli.core.commands.client_factory.get_subscription_id",
        return_value="subscription",
    ), patch(
        "azext_iot._factory._get_credential_scopes",
        return_value=["scope"],
    ), patch(
        client_path
    ) as client_type:
        assert (
            _factory.adr_update_instance_service_factory(cli_ctx)
            is client_type.return_value
        )

    assert client_type.call_args.kwargs["subscription_id"] == "subscription"
    assert (
        client_type.call_args.kwargs["base_url"]
        == "https://centraluseuap.management.azure.com"
    )
    assert client_type.call_args.kwargs["credential_scopes"] == ["scope"]


@pytest.mark.parametrize(
    "selected, desired",
    [
        (
            {"type": "SystemAssigned"},
            {"type": "None"},
        ),
        (
            {
                "type": "UserAssigned",
                "userAssignedIdentity": UAMI_ID,
            },
            {"type": "SystemAssigned"},
        ),
    ],
)
def test_update_protects_identity_selected_by_active_link(
    update_instance_provider, selected, desired
):
    namespace_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/namespaces/ns"
    )
    instance_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceUpdate/updateInstances/su"
    )
    instance = {
        "id": instance_id,
        "properties": {"linking": {"namespaceResourceId": namespace_id}},
    }
    registry = Mock()
    registry.namespaces.get.return_value = {
        "properties": {
            "updating": {
                "endpoints": {
                    "su": {
                        "resourceId": instance_id,
                        "inboundCallerIdentity": selected,
                    }
                }
            }
        }
    }
    with patch(
        "azext_iot.adr.providers.update_instance.adr_service_factory",
        return_value=registry,
    ), pytest.raises(ArgumentUsageError, match="link su update"):
        update_instance_provider._protect_link_identity(instance, desired)


def test_update_identity_guard_ignores_unlinked_instance(
    update_instance_provider,
):
    update_instance_provider._protect_link_identity(
        {"id": "/updateInstances/unlinked", "properties": {}},
        {"type": "None"},
    )


def test_update_identity_guard_rejects_invalid_or_unreadable_namespace(
    update_instance_provider,
):
    invalid = {
        "id": "/updateInstances/instance",
        "properties": {
            "linking": {"namespaceResourceId": "not-an-arm-id"}
        }
    }
    with pytest.raises(ArgumentUsageError, match="could not be validated"):
        update_instance_provider._protect_link_identity(
            invalid, {"type": "None"}
        )

    linked = {
        "id": "/updateInstances/instance",
        "properties": {
            "linking": {
                "namespaceResourceId": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.DeviceRegistry/namespaces/ns"
                )
            }
        }
    }
    with patch(
        "azext_iot.adr.providers.update_instance.adr_service_factory",
        side_effect=RuntimeError("forbidden"),
    ), pytest.raises(ArgumentUsageError, match="could not be read"):
        update_instance_provider._protect_link_identity(
            linked, {"type": "None"}
        )


def test_update_identity_guard_fails_closed_when_instance_id_is_omitted(
    update_instance_provider,
):
    linked = {
        "properties": {
            "linking": {
                "namespaceResourceId": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.DeviceRegistry/namespaces/ns"
                )
            }
        }
    }
    with pytest.raises(
        AzureResponseError, match="omitted its resource ID"
    ) as raised:
        update_instance_provider._protect_link_identity(
            linked, {"type": "None"}
        )

    assert "No identity update was submitted" in str(raised.value)

    # An identity-less, unlinked response does not require an ARM ID.
    update_instance_provider._protect_link_identity(None, {"type": "None"})


def test_update_with_missing_instance_id_fails_before_patch(
    update_instance_provider,
):
    operations = update_instance_provider.client.update_instances
    operations.get.return_value = {
        "properties": {
            "linking": {
                "namespaceResourceId": (
                    "/subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.DeviceRegistry/namespaces/ns"
                )
            }
        }
    }

    with pytest.raises(AzureResponseError, match="omitted its resource ID"):
        update_instance_provider.update(
            INSTANCE, RG, mi_system_assigned=False
        )

    operations.begin_update.assert_not_called()


def test_update_identity_guard_ignores_other_update_instance(
    update_instance_provider,
):
    namespace_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.DeviceRegistry/namespaces/ns"
    )
    instance = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceUpdate/updateInstances/current",
        "properties": {"linking": {"namespaceResourceId": namespace_id}},
    }
    registry = Mock()
    registry.namespaces.get.return_value = {
        "properties": {
            "updating": {
                "endpoints": {
                    "other": {
                        "resourceId": (
                            "/subscriptions/sub/resourceGroups/rg/providers/"
                            "Microsoft.DeviceUpdate/updateInstances/other"
                        )
                    }
                }
            }
        }
    }
    with patch(
        "azext_iot.adr.providers.update_instance.adr_service_factory",
        return_value=registry,
    ):
        update_instance_provider._protect_link_identity(
            instance, {"type": "None"}
        )
