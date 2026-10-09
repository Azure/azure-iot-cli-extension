# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)

from azext_iot.adr.providers.schema import SchemaProvider, SchemaRegistryProvider
from azext_iot.adr import commands_schema
from azext_iot.tests.adr.conftest import _spec_adr_client


RG = "test-rg"
REGISTRY = "test-registry"
SCHEMA = "test-schema"
CONTAINER_URL = "https://teststorage.blob.core.windows.net/schemas"
UAMI_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/test-rg/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/schema-registry"
)


def _completed_poller(result):
    poller = Mock()
    poller.result.return_value = result
    return poller


@pytest.fixture()
def schema_provider():
    client = _spec_adr_client()
    return SchemaProvider(Mock(cli_ctx=Mock()), client=client)


def _registry_provider():
    client = _spec_adr_client()
    return SchemaRegistryProvider(Mock(cli_ctx=Mock()), client=client)


def test_schema_registry_create_builds_direct_contract_body():
    provider = _registry_provider()
    result = {"id": "/schema-registry"}
    provider.client.schema_registries.begin_create_or_replace.return_value = (
        _completed_poller(result)
    )

    assert provider.create(
        schema_registry_name=REGISTRY,
        resource_group_name=RG,
        registry_namespace="site-a",
        storage_account_container_url=CONTAINER_URL,
        location="eastus",
        description="Models",
        display_name="Site A",
        tags={"env": "test"},
        outbound_mi_system_assigned=True,
        outbound_mi_user_assigned="   ",
    ) == result

    provider.client.schema_registries.begin_create_or_replace.assert_called_once_with(
        resource_group_name=RG,
        schema_registry_name=REGISTRY,
        resource={
            "location": "eastus",
            "tags": {"env": "test"},
            "identity": {"type": "SystemAssigned"},
            "properties": {
                "namespace": "site-a",
                "storageAccountContainerUrl": CONTAINER_URL,
                "description": "Models",
                "displayName": "Site A",
                "outboundIdentity": {"type": "SystemAssigned"},
            },
        },
    )


def test_schema_registry_update_maps_patch_body():
    provider = _registry_provider()
    result = {"id": "/schema-registry"}
    provider.client.schema_registries.begin_update.return_value = _completed_poller(
        result
    )
    provider.client.schema_registries.get.return_value = {
        "identity": {
            "type": "SystemAssigned",
            "principalId": "server-principal",
            "tenantId": "server-tenant",
        },
        "properties": {
            "outboundIdentity": {"type": "SystemAssigned"},
        },
    }

    assert provider.update(
        schema_registry_name=REGISTRY,
        resource_group_name=RG,
        description="Updated",
        display_name="Site A",
        tags={"env": "prod"},
        outbound_mi_user_assigned=UAMI_ID,
    ) == result

    provider.client.schema_registries.get.assert_called_once_with(
        resource_group_name=RG,
        schema_registry_name=REGISTRY,
    )
    provider.client.schema_registries.begin_update.assert_called_once_with(
        resource_group_name=RG,
        schema_registry_name=REGISTRY,
        properties={
            "identity": {
                "type": "SystemAssigned,UserAssigned",
                "userAssignedIdentities": {UAMI_ID: {}},
            },
            "properties": {
                "description": "Updated",
                "displayName": "Site A",
                "outboundIdentity": {
                    "type": "UserAssigned",
                    "userAssignedIdentity": UAMI_ID,
                },
            },
            "tags": {"env": "prod"},
        },
    )


def test_schema_registry_update_requires_a_property():
    provider = _registry_provider()

    with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
        provider.update(
            schema_registry_name=REGISTRY,
            resource_group_name=RG,
        )

    provider.client.schema_registries.begin_update.assert_not_called()


def test_schema_registry_rejects_conflicting_outbound_identities():
    provider = _registry_provider()

    with pytest.raises(MutuallyExclusiveArgumentError):
        provider.create(
            schema_registry_name=REGISTRY,
            resource_group_name=RG,
            registry_namespace="site-a",
            storage_account_container_url=CONTAINER_URL,
            location="eastus",
            outbound_mi_system_assigned=True,
            outbound_mi_user_assigned=UAMI_ID,
        )

    provider.client.schema_registries.begin_create_or_replace.assert_not_called()


def test_schema_create_forwards_extensible_metadata(schema_provider):
    schema = {"id": "/schema"}
    schema_provider.client.schemas.create_or_replace.return_value = schema

    assert schema_provider.create(
        schema_name=SCHEMA,
        schema_registry_name=REGISTRY,
        resource_group_name=RG,
        schema_type="FutureSchemaType",
        schema_format="FutureFormat/1.0",
        description="Thing Model",
        display_name="Smart Lamp",
        tags={"site": "west"},
    ) == schema

    schema_provider.client.schemas.create_or_replace.assert_called_once_with(
        resource_group_name=RG,
        schema_registry_name=REGISTRY,
        schema_name=SCHEMA,
        resource={
            "properties": {
                "schemaType": "FutureSchemaType",
                "format": "FutureFormat/1.0",
                "description": "Thing Model",
                "displayName": "Smart Lamp",
                "tags": {"site": "west"},
            }
        },
    )
    schema_provider.client.schema_versions.create_or_replace.assert_not_called()


def test_schema_version_create_forwards_direct_contract_body(schema_provider):
    content = '{"line":1}'
    schema_provider.client.schema_versions.create_or_replace.return_value = {
        "id": "/version/2"
    }

    schema_provider.create_version(
        version_name="2",
        schema_name=SCHEMA,
        schema_registry_name=REGISTRY,
        resource_group_name=RG,
        schema_content=content,
        description="Version 2",
    )

    body = schema_provider.client.schema_versions.create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body == {
        "properties": {
            "schemaContent": content,
            "description": "Version 2",
        }
    }


@pytest.mark.parametrize("version", ["1.0", "12345678901"])
def test_schema_version_rejects_invalid_name(schema_provider, version):
    with pytest.raises(InvalidArgumentValueError, match="1 to 10"):
        schema_provider.create_version(
            version_name=version,
            schema_name=SCHEMA,
            schema_registry_name=REGISTRY,
            resource_group_name=RG,
            schema_content="content",
        )

    schema_provider.client.schema_versions.create_or_replace.assert_not_called()


@pytest.mark.parametrize("no_wait", [False, True])
def test_schema_registry_minimal_create_resolves_location(mocker, no_wait):
    provider = _registry_provider()
    location = mocker.patch.object(provider, "_ensure_location", return_value="westus")
    resource = {"id": "/registry"}
    poller = _completed_poller(resource)
    provider.client.schema_registries.begin_create_or_replace.return_value = poller

    result = provider.create(REGISTRY, RG, "site-a", CONTAINER_URL, no_wait=no_wait)

    assert result is (poller if no_wait else resource)
    assert poller.result.call_count == (0 if no_wait else 1)
    location.assert_called_once_with(provider.cmd.cli_ctx, RG, None)
    provider.client.schema_registries.begin_create_or_replace.assert_called_once_with(
        resource_group_name=RG,
        schema_registry_name=REGISTRY,
        resource={
            "location": "westus",
            "properties": {"namespace": "site-a", "storageAccountContainerUrl": CONTAINER_URL},
        },
    )


@pytest.mark.parametrize("options,identity,outbound", [
    (
        {"outbound_mi_user_assigned": UAMI_ID},
        {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}},
        {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
    ),
    (
        {"mi_system_assigned": True, "outbound_mi_system_assigned": True},
        {"type": "SystemAssigned"},
        {"type": "SystemAssigned"},
    ),
    (
        {"mi_user_assigned": [UAMI_ID], "outbound_mi_user_assigned": UAMI_ID.upper()},
        {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}},
        {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID.upper()},
    ),
])
def test_schema_registry_create_reconciles_attached_and_outbound_identities(options, identity, outbound):
    provider = _registry_provider()
    provider.create(REGISTRY, RG, "site-a", CONTAINER_URL, location="eastus", no_wait=True, **options)
    resource = provider.client.schema_registries.begin_create_or_replace.call_args.kwargs["resource"]
    assert resource["identity"] == identity
    assert resource["properties"]["outboundIdentity"] == outbound
    provider.client.schema_registries.get.assert_not_called()


@pytest.mark.parametrize("options", [
    {"mi_system_assigned": False, "outbound_mi_system_assigned": True},
    {"mi_system_assigned": True, "outbound_mi_user_assigned": UAMI_ID},
    {"outbound_mi_user_assigned": "not-an-arm-id"},
])
def test_schema_registry_create_rejects_inconsistent_or_invalid_identity(options):
    provider = _registry_provider()
    with pytest.raises(InvalidArgumentValueError):
        provider.create(REGISTRY, RG, "site-a", CONTAINER_URL, location="eastus", **options)
    provider.client.schema_registries.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("no_wait", [False, True])
def test_schema_registry_metadata_update_does_not_read_or_modify_identities(no_wait):
    provider = _registry_provider()
    resource = {"id": "/registry"}
    poller = _completed_poller(resource)
    provider.client.schema_registries.begin_update.return_value = poller
    assert provider.update(REGISTRY, RG, description="", display_name="", tags={}, no_wait=no_wait) is (
        poller if no_wait else resource
    )
    provider.client.schema_registries.get.assert_not_called()
    provider.client.schema_registries.begin_update.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY,
        properties={"properties": {"description": "", "displayName": ""}, "tags": {}},
    )
    assert poller.result.call_count == (0 if no_wait else 1)


@pytest.mark.parametrize("current,options,patch", [
    (
        {"identity": {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {"principalId": "readonly"}}}},
        {"outbound_mi_system_assigned": True},
        {
            "identity": {"type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}},
            "properties": {"outboundIdentity": {"type": "SystemAssigned"}},
        },
    ),
    (
        {"identity": {"type": "SystemAssigned", "principalId": "readonly", "tenantId": "readonly"}},
        {"outbound_mi_system_assigned": True},
        {"properties": {"outboundIdentity": {"type": "SystemAssigned"}}},
    ),
    (
        {"identity": {"type": "SystemAssigned"}, "properties": {"outboundIdentity": {"type": "SystemAssigned"}}},
        {"outbound_mi_system_assigned": False},
        {"properties": {"outboundIdentity": None}},
    ),
    (
        None,
        {"mi_system_assigned": False, "outbound_mi_system_assigned": False},
        {"identity": {"type": "None"}, "properties": {"outboundIdentity": None}},
    ),
    (
        {"properties": {"outboundIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}}},
        {"mi_user_assigned": [UAMI_ID]},
        {"identity": {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}}},
    ),
    (
        None,
        {"mi_system_assigned": True, "outbound_mi_system_assigned": True},
        {"identity": {"type": "SystemAssigned"}, "properties": {"outboundIdentity": {"type": "SystemAssigned"}}},
    ),
])
def test_schema_registry_update_identity_state(current, options, patch):
    provider = _registry_provider()
    provider.client.schema_registries.get.return_value = current
    provider.update(REGISTRY, RG, no_wait=True, **options)
    provider.client.schema_registries.begin_update.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY, properties=patch,
    )
    if current is None:
        provider.client.schema_registries.get.assert_not_called()
    else:
        provider.client.schema_registries.get.assert_called_once_with(
            resource_group_name=RG, schema_registry_name=REGISTRY,
        )


@pytest.mark.parametrize("outbound,message", [
    ({"type": "SystemAssigned"}, "not included in the requested managed identity state"),
    ({"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}, "not included in --user-assigned-mi"),
    ({"type": "UserAssigned"}, "missing its resource ID"),
    ({"type": "FutureIdentity"}, "unsupported outbound identity type"),
])
def test_schema_registry_update_rejects_invalid_persisted_outbound_identity(outbound, message):
    provider = _registry_provider()
    provider.client.schema_registries.get.return_value = {"properties": {"outboundIdentity": outbound}}
    with pytest.raises(InvalidArgumentValueError, match=message):
        provider.update(REGISTRY, RG, mi_system_assigned=False)
    provider.client.schema_registries.begin_update.assert_not_called()


def test_schema_registry_show_and_list_scopes():
    provider = _registry_provider()
    resource = {"name": REGISTRY}
    provider.client.schema_registries.get.return_value = resource
    assert provider.show(REGISTRY, RG) is resource
    provider.client.schema_registries.get.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY,
    )
    provider.client.schema_registries.list_by_resource_group.return_value = iter([resource])
    provider.client.schema_registries.list_by_subscription.return_value = iter([resource, {"name": "another"}])
    assert provider.list(RG) == [resource]
    assert provider.list() == [resource, {"name": "another"}]
    provider.client.schema_registries.list_by_resource_group.assert_called_once_with(resource_group_name=RG)
    provider.client.schema_registries.list_by_subscription.assert_called_once_with()


def test_schema_minimal_create_show_and_list(schema_provider):
    resource = {"name": SCHEMA}
    schema_provider.client.schemas.create_or_replace.return_value = resource
    assert schema_provider.create(SCHEMA, REGISTRY, RG, "MessageSchema", "JsonSchema/draft-07") is resource
    schema_provider.client.schemas.create_or_replace.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY, schema_name=SCHEMA,
        resource={"properties": {"schemaType": "MessageSchema", "format": "JsonSchema/draft-07"}},
    )
    schema_provider.client.schemas.get.return_value = resource
    assert schema_provider.show(SCHEMA, REGISTRY, RG) is resource
    schema_provider.client.schemas.get.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY, schema_name=SCHEMA,
    )
    schema_provider.client.schemas.list_by_schema_registry.return_value = iter([resource, {"name": "another"}])
    assert schema_provider.list(REGISTRY, RG) == [resource, {"name": "another"}]
    schema_provider.client.schemas.list_by_schema_registry.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY,
    )


@pytest.mark.parametrize("version", ["0", "01", "1234567890"])
def test_schema_version_create_and_show_preserve_numeric_name(schema_provider, version):
    resource = {"name": version}
    arguments = {
        "resource_group_name": RG, "schema_registry_name": REGISTRY,
        "schema_name": SCHEMA, "schema_version_name": version,
    }
    schema_provider.client.schema_versions.create_or_replace.return_value = resource
    assert schema_provider.create_version(version, SCHEMA, REGISTRY, RG, "content") is resource
    schema_provider.client.schema_versions.create_or_replace.assert_called_once_with(
        **arguments, resource={"properties": {"schemaContent": "content"}},
    )
    schema_provider.client.schema_versions.get.return_value = resource
    assert schema_provider.show_version(version, SCHEMA, REGISTRY, RG) is resource
    schema_provider.client.schema_versions.get.assert_called_once_with(**arguments)


def test_schema_version_list(schema_provider):
    resources = [{"name": "1"}, {"name": "2"}]
    schema_provider.client.schema_versions.list_by_schema.return_value = iter(resources)
    assert schema_provider.list_versions(SCHEMA, REGISTRY, RG) == resources
    schema_provider.client.schema_versions.list_by_schema.assert_called_once_with(
        resource_group_name=RG, schema_registry_name=REGISTRY, schema_name=SCHEMA,
    )


@pytest.mark.parametrize("version", ["", "1.0", "12345678901", "-1", "1\n", " 1", "١"])
@pytest.mark.parametrize("method", ["create_version", "show_version", "delete_version"])
def test_schema_version_all_operations_reject_invalid_names_before_sdk(schema_provider, version, method):
    kwargs = {"schema_content": "content"} if method == "create_version" else {}
    with pytest.raises(InvalidArgumentValueError, match="1 to 10 numeric characters"):
        getattr(schema_provider, method)(version, SCHEMA, REGISTRY, RG, **kwargs)
    assert not schema_provider.client.schema_versions.mock_calls


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("provider_type,operation_group,method,args,kwargs", [
    (SchemaRegistryProvider, "schema_registries", "delete", (REGISTRY, RG), {}),
    (SchemaProvider, "schemas", "delete", (SCHEMA, REGISTRY, RG), {"schema_name": SCHEMA}),
    (
        SchemaProvider, "schema_versions", "delete_version", ("01", SCHEMA, REGISTRY, RG),
        {"schema_name": SCHEMA, "schema_version_name": "01"},
    ),
])
def test_schema_deletes_wait_only_when_requested(provider_type, operation_group, method, args, kwargs, no_wait):
    client = _spec_adr_client()
    provider = provider_type(Mock(cli_ctx=Mock()), client=client)
    operation = getattr(client, operation_group).begin_delete
    poller = _completed_poller(None)
    operation.return_value = poller
    assert getattr(provider, method)(*args, no_wait=no_wait) is (poller if no_wait else None)
    operation.assert_called_once_with(resource_group_name=RG, schema_registry_name=REGISTRY, **kwargs)
    assert poller.result.call_count == (0 if no_wait else 1)


_REGISTRY_ARGS = {"schema_registry_name": REGISTRY, "resource_group_name": RG}
_SCHEMA_ARGS = {**_REGISTRY_ARGS, "schema_name": SCHEMA}
_VERSION_ARGS = {**_SCHEMA_ARGS, "version_name": "01"}
_REGISTRY_METADATA = {
    "description": "Models", "display_name": "Site A", "tags": {"env": "test"},
    "mi_system_assigned": True, "mi_user_assigned": [UAMI_ID],
    "outbound_mi_system_assigned": False, "outbound_mi_user_assigned": UAMI_ID,
    "no_wait": True,
}


@pytest.mark.parametrize("command,provider_type,method,kwargs", [
    ("registry_create", "SchemaRegistryProvider", "create", {
        **_REGISTRY_ARGS, **_REGISTRY_METADATA, "registry_namespace": "site-a",
        "storage_account_container_url": CONTAINER_URL, "location": "eastus",
    }),
    ("registry_update", "SchemaRegistryProvider", "update", {**_REGISTRY_ARGS, **_REGISTRY_METADATA}),
    ("registry_show", "SchemaRegistryProvider", "show", _REGISTRY_ARGS),
    ("registry_list", "SchemaRegistryProvider", "list", {"resource_group_name": RG}),
    ("registry_delete", "SchemaRegistryProvider", "delete", {**_REGISTRY_ARGS, "no_wait": True}),
    ("create", "SchemaProvider", "create", {
        **_SCHEMA_ARGS, "schema_type": "ThingModel", "schema_format": "JsonLD/1.1",
        "description": "Lamp", "display_name": "Smart Lamp", "tags": {"site": "west"},
    }),
    ("show", "SchemaProvider", "show", _SCHEMA_ARGS),
    ("list", "SchemaProvider", "list", _REGISTRY_ARGS),
    ("delete", "SchemaProvider", "delete", {**_SCHEMA_ARGS, "no_wait": True}),
    ("version_create", "SchemaProvider", "create_version", {
        **_VERSION_ARGS, "schema_content": '{"type":"object"}', "description": "Version 01",
    }),
    ("version_show", "SchemaProvider", "show_version", _VERSION_ARGS),
    ("version_list", "SchemaProvider", "list_versions", _SCHEMA_ARGS),
    ("version_delete", "SchemaProvider", "delete_version", {**_VERSION_ARGS, "no_wait": True}),
])
def test_schema_commands_delegate_all_arguments(mocker, command, provider_type, method, kwargs):
    factory = mocker.patch.object(commands_schema, provider_type, autospec=True)
    cmd = Mock()
    operation = getattr(factory.return_value, method)
    assert getattr(commands_schema, f"adr_schema_{command}")(cmd, **kwargs) is operation.return_value
    factory.assert_called_once_with(cmd)
    operation.assert_called_once_with(**kwargs)
