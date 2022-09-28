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
device_messaging_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_device_messaging#{}"
)
device_identity_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_device_identity#{}"
)


def load_iothub_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub job", command_type=iothub_job_ops) as cmd_group:
        cmd_group.command("create", "job_create")
        cmd_group.show_command("show", "job_show")
        cmd_group.command("list", "job_list")
        cmd_group.command("cancel", "job_cancel")

    with self.command_group(
        "iot hub digital-twin", command_type=pnp_runtime_ops
    ) as cmd_group:
        cmd_group.command("invoke-command", "invoke_device_command")
        cmd_group.show_command("show", "get_digital_twin")
        cmd_group.command("update", "patch_digital_twin")

    with self.command_group(
        "iot device", command_type=device_messaging_ops
    ) as cmd_group:
        cmd_group.command("send-d2c-message", "iot_device_send_message")
        cmd_group.command("simulate", "iot_simulate_device", is_experimental=True)
        cmd_group.command("upload-file", "iot_device_upload_file")

    with self.command_group(
        "iot device c2d-message", command_type=device_messaging_ops
    ) as cmd_group:
        cmd_group.command("complete", "iot_c2d_message_complete")
        cmd_group.command("abandon", "iot_c2d_message_abandon")
        cmd_group.command("reject", "iot_c2d_message_reject")
        cmd_group.command("receive", "iot_c2d_message_receive")
        cmd_group.command("send", "iot_c2d_message_send")
        cmd_group.command("purge", "iot_c2d_message_purge")

    with self.command_group(
        "iot edge hierarchy", command_type=device_identity_ops
    ) as cmd_group:
        cmd_group.command("create", "iot_edge_hierarchy_create")

    # with self.command_group(
    #     "iot hub device-identity", command_type=device_identity_ops
    # ) as cmd_group:
    #     cmd_group.command("create", "iot_device_create")
    #     cmd_group.show_command("show", "iot_device_show")
    #     cmd_group.command("list", "iot_device_list")
    #     cmd_group.command("delete", "iot_device_delete")
    #     cmd_group.generic_update_command(
    #         "update",
    #         getter_name="iot_device_show",
    #         custom_func_type=device_identity_ops,
    #         setter_name="iot_device_update",
    #         custom_func_name="update_iot_device_custom"
    #     )
    #     cmd_group.command("renew-key", "iot_device_key_regenerate")
    #     cmd_group.command("import", "iot_device_import")
    #     cmd_group.command("export", "iot_device_export")

    # with self.command_group(
    #     "iot hub device-identity children", command_type=device_identity_ops
    # ) as cmd_group:
    #     cmd_group.show_command("add", "iot_device_children_add")
    #     cmd_group.show_command("remove", "iot_device_children_remove")
    #     cmd_group.show_command("list", "iot_device_children_list")

    # with self.command_group(
    #     "iot hub device-identity parent", command_type=device_identity_ops
    # ) as cmd_group:
    #     cmd_group.show_command("show", "iot_device_get_parent")
    #     cmd_group.show_command("set", "iot_device_set_parent")

    # with self.command_group(
    #     "iot hub device-identity connection-string", command_type=device_identity_ops
    # ) as cmd_group:
    #     cmd_group.show_command("show", "iot_get_device_connection_string")
