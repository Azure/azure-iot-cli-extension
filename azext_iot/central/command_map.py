# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

central_device_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_device#{}"
)

central_device_templates_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_device_template#{}"
)


# Dev note - think of this as the "router" and all self.command_group as the controllers
def load_central_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group(
        "iot central app device", command_type=central_device_ops, is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "list_devices")
        cmd_group.command("show", "get_device")
        cmd_group.command("create", "create_device")
        cmd_group.command("delete", "delete_device")
        cmd_group.command("registration-info", "registration_info")

    with self.command_group(
        "iot central app device-template",
        command_type=central_device_templates_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "list_device_templates")
        cmd_group.command("map", "map_device_templates")
        cmd_group.command("show", "get_device_template")
        cmd_group.command("create", "create_device_template")
        cmd_group.command("delete", "delete_device_template")
