# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests that exercise the extension command loader. Loading the full command
table and the arguments for every command executes the module-level command
registration, parameter registration and help registration code across all
service command groups (command_map.py, params.py, _help.py).
"""

import pytest
from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser


_NAMESPACE_ARGUMENTS = [
    "--namespace",
    "namespace",
    "--resource-group",
    "resource-group",
]
_ENDPOINT_ARGUMENTS = [
    "--endpoint-name",
    "endpoint",
    *_NAMESPACE_ARGUMENTS,
]
_HUB_ID = (
    "/subscriptions/hub-sub/resourceGroups/hub-rg/providers/"
    "Microsoft.Devices/IotHubs/hub"
)
_DPS_ID = (
    "/subscriptions/dps-sub/resourceGroups/dps-rg/providers/"
    "Microsoft.Devices/provisioningServices/dps"
)
_SU_ID = (
    "/subscriptions/su-sub/resourceGroups/su-rg/providers/"
    "Microsoft.DeviceUpdate/updateInstances/su"
)
_LINK_PARSER_CASES = {
    "iot adr ns link add": [
        *_NAMESPACE_ARGUMENTS,
        "--hub-endpoint-name",
        "hub",
        "--hub-resource-id",
        _HUB_ID,
        "--dps-endpoint-name",
        "dps",
        "--dps-resource-id",
        _DPS_ID,
    ],
    "iot adr ns link wait": _NAMESPACE_ARGUMENTS,
}
for _kind, _resource_option, _resource_id in (
    ("hub", "--hub-resource-id", _HUB_ID),
    ("dps", "--dps-resource-id", _DPS_ID),
    ("su", "--su-resource-id", _SU_ID),
):
    _LINK_PARSER_CASES[f"iot adr ns link {_kind} add"] = [
        *_ENDPOINT_ARGUMENTS,
        _resource_option,
        _resource_id,
    ]
    for _action in ("update", "delete", "show", "wait"):
        _LINK_PARSER_CASES[
            f"iot adr ns link {_kind} {_action}"
        ] = _ENDPOINT_ARGUMENTS
    _LINK_PARSER_CASES[
        f"iot adr ns link {_kind} list"
    ] = _NAMESPACE_ARGUMENTS


@pytest.fixture(scope="module")
def loader():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli()
    loader = IoTExtCommandsLoader(cli_ctx=cli_ctx)
    return loader


@pytest.fixture(scope="module")
def command_table(loader):
    table = loader.load_command_table(None)
    return table


@pytest.fixture(scope="module")
def link_command_parser():
    from azext_iot import IoTExtCommandsLoader

    cli_ctx = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli_ctx.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    loader.command_table = {
        name: loader.command_table[name]
        for name in _LINK_PARSER_CASES
    }

    # Azure CLI contributes --subscription as a private global argument before
    # extension signatures and argument overrides are loaded.
    cli_ctx.raise_event(
        EVENT_INVOKER_PRE_LOAD_ARGUMENTS,
        commands_loader=loader,
    )
    for command_name in _LINK_PARSER_CASES:
        loader.load_arguments(command_name)
        AzCommandsLoader.load_arguments(loader, command_name)

    parser = AzCliCommandParser(cli_ctx=cli_ctx)
    parser.load_command_table(loader)
    return parser


def test_command_table_loads(command_table):
    # The extension should register a non-trivial number of commands.
    assert command_table
    assert len(command_table) > 100
    # Spot check a few representative commands across services.
    for expected in [
        "iot du account create",
        "iot du instance create",
        "iot du update list",
        "iot dps enrollment create",
        "iot hub device-identity create",
        "iot device registration create",
        "iot adr ns su software-update operation-status list",
        "iot adr ns su software-update catalog provider list",
        "iot adr ns su software-update catalog name list",
        "iot adr ns su software-update catalog version list",
    ]:
        assert expected in command_table, f"Missing command: {expected}"


def test_load_arguments_for_all_commands(loader, command_table):
    # Loading arguments for every command exercises all params.py modules.
    # skip_applicability avoids the need for a live invocation context.
    loader.skip_applicability = True
    for command_name in command_table:
        loader.load_arguments(command_name)
    # Argument registry should be populated.
    assert loader.command_table

    def scoped_arguments(command_name):
        parts = command_name.split()
        result = {}
        for index in range(1, len(parts) + 1):
            result.update(
                loader.argument_registry.arguments.get(
                    " ".join(parts[:index]), {}
                )
            )
        return result

    for command_name in ("iot hub create", "iot dps create", "iot dps update"):
        arguments = scoped_arguments(command_name)
        assert "adr_ns_id" not in arguments
        assert "adr_ns_identity_id" not in arguments
        options = {
            option
            for argument in arguments.values()
            for option in argument.settings.get("options_list", [])
        }
        assert "--ns-resource-id" not in options
        assert "--ns-identity-id" not in options

    for command_name in ("iot adr ns create", "iot adr ns update"):
        arguments = scoped_arguments(command_name)
        options = {
            option
            for argument in arguments.values()
            for option in argument.settings.get("options_list", [])
        }
        assert {
            "--messaging-endpoints",
            "--provisioning-endpoints",
            "--updating-endpoints",
        }.isdisjoint(options)
        if command_name.endswith(" create"):
            assert "--observability-enabled" not in options
        else:
            assert "--observability-enabled" in options

    for command_name in ("iot hub create", "iot dps create", "iot dps update"):
        arguments = scoped_arguments(command_name)
        system_options = arguments[
            "system_identity"
            if command_name == "iot hub create"
            else "mi_system_assigned"
        ].settings["options_list"]
        user_options = arguments[
            "user_identities"
            if command_name == "iot hub create"
            else "mi_user_assigned"
        ].settings["options_list"]
        assert system_options[0] == "--system-assigned-mi"
        assert user_options[0] == "--user-assigned-mi"
        assert any(
            getattr(option, "target", None) == "--mi-system-assigned"
            and option.hide
            for option in system_options
        )
        assert any(
            getattr(option, "target", None) == "--mi-user-assigned"
            and option.hide
            for option in user_options
        )

    for command_name in (
        "iot dps enrollment create",
        "iot dps enrollment-group create",
    ):
        arguments = scoped_arguments(command_name)
        assert "mi_system_assigned" not in arguments
        assert "mi_user_assigned" not in arguments

    hub_identity = scoped_arguments("iot hub identity assign")
    assert hub_identity["system_identity"].settings["options_list"] == [
        "--system-assigned",
        "--system",
    ]
    assert hub_identity["user_identities"].settings["options_list"] == [
        "--user-assigned",
        "--user",
    ]
    dps_identity = scoped_arguments("iot dps identity assign")
    assert dps_identity["system_assigned"].settings["options_list"] == [
        "--system",
        "--system-assigned",
    ]
    assert dps_identity["user_assigned"].settings["options_list"] == [
        "--user",
        "--user-assigned",
    ]

    bundled = scoped_arguments("iot adr ns link add")
    assert "--hub-endpoint-name" in bundled["hub_endpoint_name"].settings[
        "options_list"
    ]
    assert "--hub-name" in bundled["hub_endpoint_name"].settings[
        "options_list"
    ]
    assert "--dps-endpoint-name" in bundled["dps_endpoint_name"].settings[
        "options_list"
    ]
    assert "--dps-name" in bundled["dps_endpoint_name"].settings[
        "options_list"
    ]

    for command_name in (
        "iot device registration request-software-updates",
        "iot device registration request-onboarding-updates",
        "iot device registration report-update-status",
    ):
        assert command_name not in command_table


@pytest.mark.parametrize("command_name", sorted(_LINK_PARSER_CASES))
def test_all_link_commands_parse_one_global_subscription_without_collision(
    mocker,
    link_command_parser,
    command_name,
):
    subscription = "namespace-sub"
    mocker.patch(
        "azure.cli.core._profile.Profile.load_cached_subscriptions",
        return_value=[{"id": subscription, "name": "namespace-subscription"}],
    )
    parsed = link_command_parser.parse_args(
        [
            *command_name.split(),
            *_LINK_PARSER_CASES[command_name],
            "--subscription",
            subscription,
        ]
    )

    assert parsed._subscription == subscription  # pylint: disable=protected-access
    subscription_actions = [
        action
        for action in link_command_parser.subparser_map[
            command_name
        ]._actions  # pylint: disable=protected-access
        if "--subscription" in action.option_strings
    ]
    assert len(subscription_actions) == 1
    assert subscription_actions[0].dest == "_subscription"


def test_link_command_parser_leaves_subscription_for_current_account_default(
    link_command_parser,
):
    command_name = "iot adr ns link su add"
    parsed = link_command_parser.parse_args(
        [
            *command_name.split(),
            *_LINK_PARSER_CASES[command_name],
        ]
    )

    assert parsed._subscription is None  # pylint: disable=protected-access
