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
