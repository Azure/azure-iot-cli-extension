# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import inspect
from unittest.mock import Mock

import pytest

from azext_iot.adr import commands_namespace


@pytest.mark.parametrize(
    "operation",
    ["create", "show", "list", "delete", "update", "migrate", "identity_show", "identity_assign", "identity_remove"],
)
@pytest.mark.parametrize("defaults", [False, True])
def test_namespace_commands_delegate(mocker, operation, defaults):
    command = getattr(commands_namespace, "adr_namespace_" + operation)
    values = {
        "namespace_name": "test-ns", "resource_group_name": "test-rg", "location": "centraluseuap",
        "tags": {"env": "test"}, "system_assigned": False, "messaging_endpoints": {"events": {"address": "example"}},
        "no_wait": True, "resource_ids": ["/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/assets/a"],
    }
    arguments = {}
    expected = {}
    for name, parameter in inspect.signature(command).parameters.items():
        if name == "cmd":
            continue
        if defaults and parameter.default is not inspect.Parameter.empty:
            expected[name] = parameter.default
        else:
            arguments[name] = expected[name] = values[name]
    factory = mocker.patch.object(commands_namespace, "NamespaceProvider")
    provider = factory.return_value
    cmd = Mock()

    assert command(cmd, **arguments) is getattr(provider, operation).return_value

    factory.assert_called_once_with(cmd)
    getattr(provider, operation).assert_called_once_with(**expected)
