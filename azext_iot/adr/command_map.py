# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType

from azext_iot._factory import adr_service_factory

adr_namespace_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_namespace#{}",
    client_factory=adr_service_factory,
)

adr_credential_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_credential#{}",
    client_factory=adr_service_factory,
)

adr_policy_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_policy#{}",
    client_factory=adr_service_factory,
)

adr_device_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_device#{}",
    client_factory=adr_service_factory,
)


def load_adr_commands(self, _):
    # Namespace commands
    with self.command_group(
        "iot adr ns", command_type=adr_namespace_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_namespace_create")
        cmd_group.show_command("show", "adr_namespace_show")
        cmd_group.command("list", "adr_namespace_list")
        cmd_group.command("delete", "adr_namespace_delete", confirmation=True)
        cmd_group.command("update", "adr_namespace_update")

    # Credential commands
    with self.command_group(
        "iot adr ns credential", command_type=adr_credential_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_credential_create")
        cmd_group.show_command("show", "adr_credential_show")
        cmd_group.command("delete", "adr_credential_delete", confirmation=True)
        cmd_group.command("sync", "adr_credential_synchronize")

    # Policy commands
    with self.command_group(
        "iot adr ns policy", command_type=adr_policy_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_policy_create")
        cmd_group.show_command("show", "adr_policy_show")
        cmd_group.command("list", "adr_policy_list")
        cmd_group.command("delete", "adr_policy_delete", confirmation=True)
        cmd_group.command("update", "adr_policy_update")
        cmd_group.command("revoke-issuer", "adr_policy_revoke_issuer", confirmation=True)
        cmd_group.command("activate-byor", "adr_policy_activate_byor")

    # Device commands
    with self.command_group(
        "iot adr ns device", command_type=adr_device_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "adr_device_show")
        cmd_group.command("list", "adr_device_list")
        cmd_group.command("update", "adr_device_update")
        cmd_group.command("revoke", "adr_device_revoke", confirmation=True)
