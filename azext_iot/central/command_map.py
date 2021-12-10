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

central_device_groups_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_device_group#{}"
)

central_roles_ops = CliCommandType(operations_tmpl="azext_iot.central.commands_role#{}")

central_file_uploads_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_file_upload#{}"
)

central_orgs_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_organization#{}"
)

central_jobs_ops = CliCommandType(operations_tmpl="azext_iot.central.commands_job#{}")

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

central_query_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_query#{}"
)

central_destination_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_destination#{}"
)

central_export_ops = CliCommandType(
    operations_tmpl="azext_iot.central.commands_export#{}"
)


# Dev note - think of this as the "router" and all self.command_group as the controllers
def load_central_commands(self, _):
    """
    Load CLI commands
    """

    with self.command_group("iot central", command_type=central_query_ops) as cmd_group:
        cmd_group.command("query", "query_run", is_preview=True)

    with self.command_group(
        "iot central export destination",
        command_type=central_destination_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "list_destinations")
        cmd_group.show_command("show", "get_destination")
        cmd_group.command("delete", "delete_destination")
        cmd_group.command("create", "add_destination")
        cmd_group.command("update", "update_destination")

    with self.command_group(
        "iot central export", command_type=central_export_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("list", "list_exports")
        cmd_group.show_command("show", "get_export")
        cmd_group.command("delete", "delete_export")
        cmd_group.command("create", "add_export")
        cmd_group.command("update", "update_export")

    with self.command_group(
        "iot central diagnostics", command_type=central_monitor_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("monitor-events", "monitor_events")
        cmd_group.command(
            "validate-messages",
            "validate_messages",
        )
        cmd_group.command(
            "monitor-properties",
            "monitor_properties",
        )
        cmd_group.command(
            "validate-properties",
            "validate_properties",
        )

    with self.command_group(
        "iot central diagnostics", command_type=central_device_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command(
            "registration-summary",
            "registration_summary",
        )

    with self.command_group(
        "iot central user",
        command_type=central_user_ops,
    ) as cmd_group:
        cmd_group.command("create", "add_user")
        cmd_group.command("list", "list_users")
        cmd_group.show_command("show", "get_user")
        cmd_group.command("delete", "delete_user")

    with self.command_group(
        "iot central api-token",
        command_type=central_api_token_ops,
    ) as cmd_group:
        cmd_group.command("create", "add_api_token")
        cmd_group.command("list", "list_api_tokens")
        cmd_group.show_command("show", "get_api_token")
        cmd_group.command("delete", "delete_api_token")

    with self.command_group(
        "iot central device",
        command_type=central_device_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_devices")
        cmd_group.show_command("show", "get_device")
        cmd_group.command("create", "create_device")
        cmd_group.command("delete", "delete_device")
        cmd_group.command("registration-info", "registration_info")
        cmd_group.command("show-credentials", "get_credentials")
        cmd_group.command("compute-device-key", "compute_device_key")
        cmd_group.command("manual-failover", "run_manual_failover")
        cmd_group.command("manual-failback", "run_manual_failback")
        cmd_group.command("purge-messages", "purge_c2d_messages")

    with self.command_group(
        "iot central device command",
        command_type=central_device_ops,
    ) as cmd_group:
        cmd_group.command("run", "run_command")
        cmd_group.command("history", "get_command_history")

    with self.command_group(
        "iot central device-template",
        command_type=central_device_templates_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_device_templates")
        # cmd_group.command("map", "map_device_templates")
        cmd_group.show_command("show", "get_device_template")
        cmd_group.command("create", "create_device_template")
        cmd_group.command("delete", "delete_device_template")

    with self.command_group(
        "iot central device-group",
        command_type=central_device_groups_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "list_device_groups")

    with self.command_group(
        "iot central role", command_type=central_roles_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "get_role")
        cmd_group.command("list", "list_roles")

    with self.command_group(
        "iot central file-upload-config",
        command_type=central_file_uploads_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.show_command("show", "get_fileupload")
        cmd_group.show_command("delete", "delete_fileupload")
        cmd_group.show_command("create", "create_fileupload")

    with self.command_group(
        "iot central organization", command_type=central_orgs_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "get_org")
        cmd_group.command("list", "list_orgs")
        cmd_group.command("create", "create_org")
        cmd_group.command("delete", "delete_org")

    with self.command_group(
        "iot central job", command_type=central_jobs_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "get_job")
        cmd_group.command("list", "list_jobs")
        cmd_group.command("create", "create_job")
        cmd_group.command("stop", "stop_job")
        cmd_group.command("resume", "resume_job")
        cmd_group.command("get-devices", "get_job_devices")
        cmd_group.command("rerun", "rerun_job")

    with self.command_group(
        "iot central device twin",
        command_type=central_device_twin_ops,
    ) as cmd_group:
        cmd_group.show_command(
            "show",
            "device_twin_show",
        )
