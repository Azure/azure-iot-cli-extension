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
from azure.cli.core.mock import DummyCli


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
        "iot device registration operation-status",
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

    for command_name in (
        "iot dps enrollment create",
        "iot dps enrollment update",
        "iot dps enrollment-group create",
        "iot dps enrollment-group update",
    ):
        arguments = scoped_arguments(command_name)
        assert {
            "adr_namespace",
            "adr_ca_name",
            "adr_certificate_policy_name",
        } <= set(arguments)

        policy_options = arguments[
            "adr_certificate_policy_name"
        ].settings["options_list"]
        assert policy_options[0] == "--adr-cert-policy-name"
        assert any(
            getattr(option, "target", None)
            == "--adr-certificate-policy-name"
            and option.hide
            for option in policy_options
        )
        credential_alias = arguments["credential_policy_name"].settings
        assert credential_alias["options_list"] == [
            "--credential-policy-name",
            "--cpn",
        ]
        assert credential_alias["deprecate_info"].hide is True
        assert (
            credential_alias["deprecate_info"].redirect
            == "--adr-cert-policy-name"
        )

    device_auth_arguments = {
        "enrollment_group_id",
        "device_symmetric_key",
        "compute_key",
        "certificate_file",
        "key_file",
        "passphrase",
    }
    for command_name in (
        "iot device registration create",
        "iot device registration operation-status",
    ):
        arguments = scoped_arguments(command_name)
        assert device_auth_arguments <= set(arguments)

    create_arguments = scoped_arguments("iot device registration create")
    assert {
        "csr",
        "endorsement_key",
        "storage_root_key",
    } <= set(create_arguments)
    assert {"cert_output", "certificate_output_file"}.isdisjoint(
        create_arguments
    )
    create_options = {
        option
        for argument in create_arguments.values()
        for option in argument.settings.get("options_list", [])
        if isinstance(option, str)
    }
    assert {"--cert-output", "--certificate-output-file"}.isdisjoint(
        create_options
    )

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
