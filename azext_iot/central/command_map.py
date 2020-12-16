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

central_device_twin_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_device_twin#{}"
)

central_monitor_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_monitor#{}"
)

central_user_ops = CliCommandType(operations_tmpl="azext_iot.central.commands_user#{}")

central_api_token_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_api_token#{}"
)


# Dev note - think of this as the "router" and all self.command_group as the controllers
def load_central_commands(self, _):
    """
    Load CLI commands
    """

    with self.command_group(
        "iot central diagnostics", command_type=central_monitor_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("monitor-events", "monitor_events")
        cmd_group.command(
            "validate-messages", "validate_messages",
        )
        cmd_group.command(
            "monitor-properties", "monitor_properties",
        )
        cmd_group.command(
            "validate-properties", "validate_properties",
        )

    with self.command_group(
        "iot central diagnostics", command_type=central_device_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command(
            "registration-summary", "registration_summary",
        )

    with self.command_group(
        "iot central user", command_type=central_user_ops, is_preview=True,
    ) as cmd_group:
        cmd_group.command("create", "add_user")
        cmd_group.command("list", "list_users")
        cmd_group.show_command("show", "get_user")
        cmd_group.command("delete", "delete_user")

    with self.command_group(
        "iot central api-token", command_type=central_api_token_ops, is_preview=True,
    ) as cmd_group:
        cmd_group.command("create", "add_api_token")
        cmd_group.command("list", "list_api_tokens")
        cmd_group.show_command("show", "get_api_token")
        cmd_group.command("delete", "delete_api_token")

    with self.command_group(
        "iot central device", command_type=central_device_ops, is_preview=True,
    ) as cmd_group:
        # cmd_group.command("list", "list_devices")
        cmd_group.show_command("show", "get_device")
        cmd_group.command("create", "create_device")
        cmd_group.command("delete", "delete_device")
        cmd_group.command("registration-info", "registration_info")
        cmd_group.command("show-credentials", "get_credentials")
        cmd_group.command("compute-device-key", "compute_device_key")

    with self.command_group(
        "iot central device command", command_type=central_device_ops, is_preview=True,
    ) as cmd_group:
        cmd_group.command("run", "run_command")
        cmd_group.command("history", "get_command_history")

    with self.command_group(
        "iot central device-template",
        command_type=central_device_templates_ops,
        is_preview=True,
    ) as cmd_group:
        # cmd_group.command("list", "list_device_templates")
        # cmd_group.command("map", "map_device_templates")
        cmd_group.show_command("show", "get_device_template")
        cmd_group.command("create", "create_device_template")
        cmd_group.command("delete", "delete_device_template")

    with self.command_group(
        "iot central device twin", command_type=central_device_twin_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command(
            "show", "device_twin_show",
        )
