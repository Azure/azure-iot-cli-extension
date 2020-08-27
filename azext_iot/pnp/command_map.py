# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

pnp_repo_ops = CliCommandType(operations_tmpl="azext_iot.pnp.commands_repository#{}")
pnp_model_ops = CliCommandType(operations_tmpl="azext_iot.pnp.commands_api#{}")


def load_pnp_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group(
        "iot pnp role-assignment", command_type=pnp_repo_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "iot_pnp_role_create")
        cmd_group.command("list", "iot_pnp_role_list")
        cmd_group.command("delete", "iot_pnp_role_delete")

    with self.command_group(
        "iot pnp repo", command_type=pnp_repo_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "iot_pnp_tenant_create")
        cmd_group.command("list", "iot_pnp_tenant_show")

    with self.command_group(
        "iot pnp model", command_type=pnp_model_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "iot_pnp_model_show")
        cmd_group.command("create", "iot_pnp_model_create")
        cmd_group.command("publish", "iot_pnp_model_publish", confirmation=True)
        cmd_group.command("list", "iot_pnp_model_list")
