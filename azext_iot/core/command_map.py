# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""

from azure.cli.core.commands import CliCommandType

from azext_iot._factory import iot_dps_resource_factory

core_ops = CliCommandType(operations_tmpl="azext_iot.core.custom#{}")


def load_core_commands(self, _):
    """
    Load CLI commands
    """
    # iot dps commands
    with self.command_group(
        "iot dps", command_type=core_ops, client_factory=iot_dps_resource_factory
    ) as cmd_group:
        cmd_group.command("create", "iot_dps_create")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_dps_get",
            setter_name="iot_dps_update",
            custom_func_type=core_ops,
        )
        cmd_group.show_command("show", "iot_dps_get")
