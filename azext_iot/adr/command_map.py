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


def load_adr_commands(self, _):
    with self.command_group("iot adr ns", command_type=adr_namespace_ops, is_preview=True) as cmd_group:
        cmd_group.command("create", "adr_namespace_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_namespace_show")
        cmd_group.command("list", "adr_namespace_list")
        cmd_group.command("delete", "adr_namespace_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("update", "adr_namespace_update", supports_no_wait=True)
        cmd_group.command("migrate", "adr_namespace_migrate", supports_no_wait=True)
        cmd_group.wait_command("wait", "adr_namespace_show")

    with self.command_group("iot adr ns identity", command_type=adr_namespace_ops, is_preview=True) as cmd_group:
        cmd_group.show_command("show", "adr_namespace_identity_show")
        cmd_group.command("assign", "adr_namespace_identity_assign", supports_no_wait=True)
        cmd_group.command("remove", "adr_namespace_identity_remove", supports_no_wait=True)
        cmd_group.wait_command("wait", "adr_namespace_show")
