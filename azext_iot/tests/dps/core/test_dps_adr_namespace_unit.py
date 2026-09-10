# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""DPS stable management does not expose the removed namespace association."""

from inspect import signature
from unittest.mock import MagicMock

import pytest

from azext_iot.core import custom
from azext_iot.core.command_map import load_core_commands
from azext_iot.core.help import patch_core_help
from azext_iot.core.params import load_core_arguments


@pytest.mark.parametrize("handler", [custom.iot_dps_create, custom.iot_dps_update])
@pytest.mark.parametrize("argument", ["adr_ns_id", "adr_ns_identity_id"])
def test_dps_handlers_reject_namespace_arguments(handler, argument):
    assert argument not in signature(handler).parameters
    kwargs = {
        "client": MagicMock(),
        "dps_name": "test-dps",
        "resource_group_name": "test-rg",
        argument: "/unsupported/namespace",
    }
    if handler is custom.iot_dps_create:
        kwargs["cmd"] = MagicMock()
    else:
        kwargs["parameters"] = {"properties": {}}
    with pytest.raises(TypeError, match=f"unexpected keyword argument '{argument}'"):
        handler(**kwargs)


def test_dps_namespace_arguments_removed_without_changing_hub():
    loader = MagicMock()
    contexts = {}

    def argument_context(scope, **_):
        return contexts.setdefault(scope, MagicMock())

    loader.argument_context.side_effect = argument_context
    load_core_arguments(loader, None)
    dps_calls = contexts["iot dps"].__enter__.return_value.argument.call_args_list
    names = {call.args[0] for call in dps_calls}
    options = {option for call in dps_calls for option in call.kwargs.get("options_list", [])}
    assert {"adr_ns_id", "adr_ns_identity_id"}.isdisjoint(names)
    assert {"--ns-resource-id", "--ns-id", "--ns-identity-id"}.isdisjoint(options)
    assert {"--mi-system-assigned", "--mi-user-assigned"} <= options

    hub_calls = contexts["iot hub"].__enter__.return_value.argument.call_args_list
    hub_options = {option for call in hub_calls for option in call.kwargs.get("options_list", [])}
    assert {"--ns-resource-id", "--ns-identity-id"} <= hub_options


def test_dps_help_preserves_identity_without_namespace(monkeypatch):
    from knack.help_files import helps

    monkeypatch.setitem(helps, "iot dps create", "type: command")
    monkeypatch.setitem(helps, "iot hub create", "type: command")
    patch_core_help()
    assert "--mi-system-assigned" in helps["iot dps create"]
    assert "--mi-user-assigned" in helps["iot dps create"]
    assert "--ns-" not in helps["iot dps create"]
    assert "Device Registry namespace" not in helps["iot dps create"]
    assert "--ns-resource-id" in helps["iot hub create"]
    assert "--ns-identity-id" in helps["iot hub create"]


def test_dps_namespace_helper_removed():
    assert not hasattr(custom, "_build_dps_adr_properties")


@pytest.mark.parametrize("system_assigned", [None, False, True])
def test_dps_create_defaults_do_not_construct_namespace(mocker, system_assigned):
    client = MagicMock()
    client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {"nameAvailable": True}
    mocker.patch("azext_iot.core.custom._ensure_location", return_value="westus2")

    result = custom.iot_dps_create(
        MagicMock(), client, "test-dps", "test-rg", mi_system_assigned=system_assigned
    )

    assert result is client.iot_dps_resource.begin_create_or_update.return_value
    kwargs = client.iot_dps_resource.begin_create_or_update.call_args.kwargs
    assert kwargs["resource_group_name"] == "test-rg"
    assert kwargs["provisioning_service_name"] == "test-dps"
    description = kwargs["iot_dps_description"]
    assert description["properties"] == {}
    assert description["location"] == "westus2"
    assert description["sku"] == {"name": "S1", "capacity": 1}
    if system_assigned is None:
        assert "identity" not in description
    elif system_assigned:
        assert description["identity"] == {"type": "SystemAssigned", "userAssignedIdentities": None}
    else:
        assert description["identity"] is None


@pytest.mark.parametrize("tags", [None, {}])
@pytest.mark.parametrize("system_assigned", [None, True])
def test_dps_update_defaults_preserve_supported_state(tags, system_assigned):
    client = MagicMock()
    parameters = {
        "properties": {"disableLocalAuth": True, "allocationPolicy": "Hashed"},
        "tags": {"existing": "tag"},
        "identity": {"type": "None"},
    }

    result = custom.iot_dps_update(
        client, "test-dps", parameters, "test-rg", tags=tags, mi_system_assigned=system_assigned
    )

    assert result is client.iot_dps_resource.begin_create_or_update.return_value
    description = client.iot_dps_resource.begin_create_or_update.call_args.kwargs["iot_dps_description"]
    assert description is parameters
    assert description["properties"] == {"disableLocalAuth": True, "allocationPolicy": "Hashed"}
    assert description["tags"] == ({"existing": "tag"} if tags is None else {})
    assert description["identity"] == (
        {"type": "None"} if system_assigned is None else {"type": "SystemAssigned", "userAssignedIdentities": None}
    )


def test_dps_command_surface_remains_compatible():
    loader = MagicMock()
    groups = {}

    def command_group(scope, **_):
        return groups.setdefault(scope, MagicMock())

    loader.command_group.side_effect = command_group
    load_core_commands(loader, None)

    assert {scope for scope in groups if scope.startswith("iot dps")} == {
        "iot dps", "iot dps identity", "iot dps linked-hub", "iot dps certificate", "iot dps policy"
    }
    commands = groups["iot dps"].__enter__.return_value
    assert {call.args[0] for call in commands.command.call_args_list} == {"create", "delete", "list"}
    commands.show_command.assert_called_once_with("show", "iot_dps_get")
    assert commands.generic_update_command.call_args.args == ("update",)
    assert commands.generic_update_command.call_args.kwargs["setter_name"] == "iot_dps_update"
    assert not commands.wait_command.called
