# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType
from azext_iot.deviceupdate._help import load_deviceupdate_help

load_deviceupdate_help()

deviceupdate_account_ops = CliCommandType(
    operations_tmpl="azext_iot.deviceupdate.commands_account#{}"
)
deviceupdate_instance_ops = CliCommandType(
    operations_tmpl="azext_iot.deviceupdate.commands_instance#{}"
)


def load_deviceupdate_commands(self, _):
    """
    Load CLI commands
    """

    with self.command_group(
        "iot device-update",
        command_type=deviceupdate_account_ops,
        is_preview=True,
    ) as cmd_group:
        pass

    with self.command_group(
        "iot device-update account",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_account", supports_no_wait=True)
        cmd_group.command("list", "list_accounts")
        cmd_group.show_command("show", "show_account")
        cmd_group.command(
            "delete", "delete_account", confirmation=True, supports_no_wait=True
        )
        cmd_group.generic_update_command(
            "update",
            getter_name="show_account",
            setter_name="update_account",
            supports_no_wait=True,
        )
        cmd_group.wait_command("wait", getter_name="wait_on_account")

    with self.command_group(
        "iot device-update account private-endpoint-connection",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_account_private_connections")
        cmd_group.show_command("show", "show_account_private_connection")
        cmd_group.command("set", "set_account_private_connection")
        cmd_group.command("delete", "delete_account_private_connection", confirmation=True)

    with self.command_group(
        "iot device-update account private-link-resource",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_account_private_links")

    with self.command_group(
        "iot device-update instance",
        command_type=deviceupdate_instance_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_instance", supports_no_wait=True)
        cmd_group.command("list", "list_instances")
        cmd_group.show_command("show", "show_instance")
        cmd_group.command(
            "delete", "delete_instance", confirmation=True, supports_no_wait=True
        )
        cmd_group.generic_update_command(
            "update",
            getter_name="show_instance",
            setter_name="update_instance",
            supports_no_wait=True,
        )
        cmd_group.wait_command("wait", getter_name="wait_on_instance")
