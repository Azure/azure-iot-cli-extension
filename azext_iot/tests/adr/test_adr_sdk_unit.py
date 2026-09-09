# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util

import pytest

from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient, operations


@pytest.mark.parametrize(
    "operation_group",
    [
        operations.NamespaceAssetsOperations,
        operations.NamespaceDevicesOperations,
        operations.NamespaceDiscoveredAssetsOperations,
        operations.NamespaceDiscoveredDevicesOperations,
    ],
)
def test_namespace_child_lists_use_namespace_operation_name(operation_group):
    assert hasattr(operation_group, "list_by_namespace")
    assert not hasattr(operation_group, "list_by_resource_group")


def test_adr_sdk_is_modeless_and_synchronous():
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.aio") is None
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.models") is None


def test_adr_client_and_api_version_match_preview_contract():
    client = DeviceRegistryMgmtClient(
        credential=object(),
        subscription_id="00000000-0000-0000-0000-000000000000",
        base_url="https://centraluseuap.management.azure.com",
    )

    assert client._config.api_version == "2026-11-02-preview"
    assert hasattr(client, "namespaces")
    assert hasattr(client, "certificate_authorities")
    assert hasattr(client, "certificate_policies")
