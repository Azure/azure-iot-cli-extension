# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from inspect import getsource

import pytest

from azext_iot.sdk.deviceregistry.aio import operations as aio_operations
from azext_iot.sdk.deviceregistry import operations


@pytest.mark.parametrize(
    "operation_group",
    [
        operations.NamespaceAssetsOperations,
        operations.NamespaceDevicesOperations,
        operations.NamespaceDiscoveredAssetsOperations,
        operations.NamespaceDiscoveredDevicesOperations,
        aio_operations.NamespaceAssetsOperations,
        aio_operations.NamespaceDevicesOperations,
        aio_operations.NamespaceDiscoveredAssetsOperations,
        aio_operations.NamespaceDiscoveredDevicesOperations,
    ],
)
def test_namespace_child_lists_use_namespace_operation_name(operation_group):
    assert hasattr(operation_group, "list_by_namespace")
    assert not hasattr(operation_group, "list_by_resource_group")


@pytest.mark.parametrize(
    "operation_group",
    [
        operations.NamespacesOperations,
        aio_operations.NamespacesOperations,
    ],
)
@pytest.mark.parametrize(
    "method_name",
    [
        "begin_generate_report",
        "begin_migrate",
    ],
)
def test_namespace_action_lros_use_azure_async_operation(
    operation_group, method_name
):
    source = getsource(getattr(operation_group, method_name))

    assert '"final-state-via": "azure-async-operation"' in source
    assert '"final-state-via": "location"' not in source
