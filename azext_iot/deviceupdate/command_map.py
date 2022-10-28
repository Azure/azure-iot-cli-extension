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

deviceupdate_account_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_account#{}")
deviceupdate_instance_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_instance#{}")
deviceupdate_update_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_update#{}")
deviceupdate_device_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_device#{}")
deviceupdate_device_class_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_device_class#{}")
deviceupdate_log_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_log#{}")
deviceupdate_deployment_ops = CliCommandType(operations_tmpl="azext_iot.deviceupdate.commands_deployment#{}")


def load_deviceupdate_commands(self, _):
    """
    Load CLI commands
    """

    with self.command_group(
        "iot du",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        pass

    with self.command_group(
        "iot du account",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_account", supports_no_wait=True)
        cmd_group.command("list", "list_accounts")
        cmd_group.show_command("show", "show_account")
        cmd_group.command("delete", "delete_account", confirmation=True, supports_no_wait=True)
        cmd_group.generic_update_command(
            "update",
            getter_name="show_account",
            setter_name="update_account",
            supports_no_wait=True,
        )
        cmd_group.wait_command("wait", getter_name="wait_on_account")

    with self.command_group(
        "iot du account private-endpoint-connection",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_account_private_connections")
        cmd_group.show_command("show", "show_account_private_connection")
        cmd_group.command("set", "set_account_private_connection")
        cmd_group.command("delete", "delete_account_private_connection", confirmation=True)

    with self.command_group(
        "iot du account private-link-resource",
        command_type=deviceupdate_account_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_account_private_links")

    with self.command_group(
        "iot du instance",
        command_type=deviceupdate_instance_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_instance", supports_no_wait=True)
        cmd_group.command("list", "list_instances")
        cmd_group.show_command("show", "show_instance")
        cmd_group.command("delete", "delete_instance", confirmation=True, supports_no_wait=True)
        cmd_group.generic_update_command(
            "update",
            getter_name="show_instance",
            setter_name="update_instance",
            supports_no_wait=True,
        )
        cmd_group.wait_command("wait", getter_name="wait_on_instance")

    with self.command_group(
        "iot du update",
        command_type=deviceupdate_update_ops,
    ) as cmd_group:
        cmd_group.command("import", "import_update", supports_no_wait=True, supports_local_cache=True)
        cmd_group.command("delete", "delete_update", supports_no_wait=True, confirmation=True)
        cmd_group.command(
            "list",
            "list_updates",
            table_transformer=(
                "[*].{UpdateProvider:updateId.provider,UpdateName:updateId.name,UpdateVersion:updateId.version,"
                "FriendlyName:friendlyName,IsDeployable:isDeployable,ManifestVersion:manifestVersion,"
                "ImportedDateTime:importedDateTime}"
            ),
        )
        cmd_group.show_command("show", "show_update")
        cmd_group.show_command("calculate-hash", "calculate_hash")
        cmd_group.show_command("stage", "stage_update", is_preview=True)  # Is preview independent of root command group.

    with self.command_group(
        "iot du update file",
        command_type=deviceupdate_update_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_update_files")
        cmd_group.show_command("show", "show_update_file")

    with self.command_group(
        "iot du update init",
        command_type=deviceupdate_update_ops,
        is_preview=True,  # Is preview independent of root command group.
    ) as cmd_group:
        cmd_group.command("v5", "manifest_init_v5")

    with self.command_group(
        "iot du device",
        command_type=deviceupdate_device_ops,
    ) as cmd_group:
        cmd_group.command("import", "import_devices")
        cmd_group.command("list", "list_devices")
        cmd_group.show_command("show", "show_device")

    with self.command_group(
        "iot du device module",
        command_type=deviceupdate_device_ops,
    ) as cmd_group:
        cmd_group.show_command("show", "show_device_module")

    with self.command_group(
        "iot du device compliance",
        command_type=deviceupdate_device_ops,
    ) as cmd_group:
        cmd_group.show_command("show", "show_update_compliance")

    with self.command_group(
        "iot du device group",
        command_type=deviceupdate_device_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_device_groups")
        cmd_group.show_command("show", "show_device_group")
        cmd_group.command("delete", "delete_device_group", confirmation=True)

    with self.command_group(
        "iot du device class",
        command_type=deviceupdate_device_class_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_device_classes")
        cmd_group.show_command("show", "show_device_class")
        cmd_group.command("update", "update_device_class")
        cmd_group.command("delete", "delete_device_class", confirmation=True)

    with self.command_group(
        "iot du device health",
        command_type=deviceupdate_device_ops,
    ) as cmd_group:
        cmd_group.command("list", "list_device_health")

    with self.command_group(
        "iot du device deployment",
        command_type=deviceupdate_deployment_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_deployment")
        cmd_group.show_command("show", "show_deployment")
        cmd_group.command("list", "list_deployments")
        cmd_group.command("delete", "delete_deployment", confirmation=True)
        cmd_group.command("retry", "retry_deployment_for_class")
        cmd_group.command("cancel", "cancel_deployment_for_class")
        cmd_group.command("list-devices", "list_devices_for_deployment")

    with self.command_group(
        "iot du device log",
        command_type=deviceupdate_log_ops,
    ) as cmd_group:
        cmd_group.command("collect", "collect_logs")
        cmd_group.command("list", "list_log_collections")
        cmd_group.show_command("show", "show_log_collection")
