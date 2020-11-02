# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

pnp_runtime_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_pnp_runtime#{}"
)
iothub_job_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_job#{}")


def load_iothub_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub job", command_type=iothub_job_ops) as cmd_group:
        cmd_group.command("create", "job_create")
        cmd_group.show_command("show", "job_show")
        cmd_group.command("list", "job_list")
        cmd_group.command("cancel", "job_cancel")

    '''
    with self.command_group("iot pnp twin", command_type=pnp_runtime_ops) as cmd_group:
        cmd_group.command("invoke-command", "invoke_device_command")
        cmd_group.show_command("show", "get_digital_twin")
        cmd_group.command("update", "patch_digital_twin")
    '''
