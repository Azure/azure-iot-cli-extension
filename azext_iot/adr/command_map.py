# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType

from azext_iot._factory import (
    adr_service_factory,
    adr_update_instance_service_factory,
)

adr_namespace_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_namespace#{}",
    client_factory=adr_service_factory,
)

adr_ca_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_certificate_authority#{}",
    client_factory=adr_service_factory,
)

adr_ca_policy_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_certificate_policy#{}",
    client_factory=adr_service_factory,
)

adr_registry_device_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_registry_device#{}",
    client_factory=adr_service_factory,
)

adr_link_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_link#{}",
    client_factory=adr_service_factory,
)

adr_group_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_group#{}",
    client_factory=adr_service_factory,
)

adr_job_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_job#{}",
    client_factory=adr_service_factory,
)

adr_job_run_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_job_run#{}",
    client_factory=adr_service_factory,
)

adr_report_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_report#{}",
    client_factory=adr_service_factory,
)

adr_update_instance_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_su#{}",
    client_factory=adr_update_instance_service_factory,
)

adr_software_update_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_su#{}",
)

adr_wait_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_wait#{}",
)

adr_link_wait_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_wait#{}",
    client_factory=adr_service_factory,
)

_HUB_DELETE_CONFIRMATION = (
    "This operation will permanently delete the linked IoT Hub resource and "
    "update the Device Registry namespace. This cannot be undone. Continue?"
)
_DPS_DELETE_CONFIRMATION = (
    "This operation will permanently delete the linked Device Provisioning "
    "Service resource and update the Device Registry namespace. This cannot "
    "be undone. Continue?"
)
_SU_DELETE_CONFIRMATION = (
    "This operation will permanently delete the linked Update Instance "
    "resource and update the Device Registry namespace. This cannot be "
    "undone. Continue?"
)


def load_adr_commands(self, _):
    # Namespace commands
    with self.command_group(
        "iot adr ns", command_type=adr_namespace_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_namespace_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_namespace_show")
        cmd_group.command("list", "adr_namespace_list")
        cmd_group.command("delete", "adr_namespace_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("migrate", "adr_namespace_migrate", supports_no_wait=True)
        cmd_group.command("update", "adr_namespace_update", supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_namespace_wait", command_type=adr_wait_ops
        )

    # Certificate Authority commands
    with self.command_group(
        "iot adr ns ca", command_type=adr_ca_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_ca_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_ca_show")
        cmd_group.command("list", "adr_ca_list")
        cmd_group.command("update", "adr_ca_update", supports_no_wait=True)
        cmd_group.command("delete", "adr_ca_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("activate", "adr_ca_activate", supports_no_wait=True)
        cmd_group.command("revoke", "adr_ca_revoke", confirmation=True, supports_no_wait=True)
        cmd_group.command("wait", "adr_ca_wait", command_type=adr_wait_ops)

    # Certificate Policy commands (nested under a certificate authority)
    with self.command_group(
        "iot adr ns ca policy", command_type=adr_ca_policy_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_ca_policy_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_ca_policy_show")
        cmd_group.command("list", "adr_ca_policy_list")
        cmd_group.command("update", "adr_ca_policy_update", supports_no_wait=True)
        cmd_group.command("delete", "adr_ca_policy_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_ca_policy_wait", command_type=adr_wait_ops
        )

    # Registry Device commands
    with self.command_group(
        "iot adr ns registry-device",
        command_type=adr_registry_device_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("create", "adr_registry_device_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_registry_device_show")
        cmd_group.command("list", "adr_registry_device_list")
        cmd_group.command("update", "adr_registry_device_update", supports_no_wait=True)
        cmd_group.command(
            "delete",
            "adr_registry_device_delete",
            confirmation=True,
            supports_no_wait=True,
        )
        cmd_group.command(
            "wait", "adr_registry_device_wait", command_type=adr_wait_ops
        )

    with self.command_group(
        "iot adr ns registry-device auth",
        command_type=adr_registry_device_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_registry_device_auth_list")
        cmd_group.show_command("show", "adr_registry_device_auth_show")
        cmd_group.command("show-keys", "adr_registry_device_auth_show_keys")
        cmd_group.command(
            "revoke-certs",
            "adr_registry_device_auth_revoke_certs",
            confirmation=True,
            supports_no_wait=True,
        )
        cmd_group.command(
            "wait",
            "adr_registry_device_auth_wait",
            command_type=adr_wait_ops,
        )

    with self.command_group(
        "iot adr ns registry-device attribute",
        command_type=adr_registry_device_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("create", "adr_registry_device_attribute_create")
        cmd_group.command("list", "adr_registry_device_attribute_list")
        cmd_group.show_command("show", "adr_registry_device_attribute_show")
        cmd_group.command(
            "delete",
            "adr_registry_device_attribute_delete",
            confirmation=True,
        )

    with self.command_group(
        "iot adr ns registry-device capability",
        command_type=adr_registry_device_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_registry_device_capability_list")
        cmd_group.show_command("show", "adr_registry_device_capability_show")

    with self.command_group(
        "iot adr ns identity", command_type=adr_namespace_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "adr_namespace_identity_show")
        cmd_group.command("assign", "adr_namespace_identity_assign", supports_no_wait=True)
        cmd_group.command("remove", "adr_namespace_identity_remove", supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_namespace_wait", command_type=adr_wait_ops
        )

    # Link commands (mutate namespace.properties.messaging.endpoints / provisioning.endpoints)
    with self.command_group(
        "iot adr ns link", command_type=adr_link_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("add", "adr_link_add", supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_link_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns link hub", command_type=adr_link_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("add", "adr_link_hub_add", supports_no_wait=True)
        cmd_group.command("update", "adr_link_hub_update", supports_no_wait=True)
        cmd_group.command(
            "delete",
            "adr_link_hub_delete",
            confirmation=_HUB_DELETE_CONFIRMATION,
        )
        cmd_group.show_command("show", "adr_link_hub_show")
        cmd_group.command("list", "adr_link_hub_list")
        cmd_group.command(
            "wait", "adr_link_hub_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns link dps", command_type=adr_link_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("add", "adr_link_dps_add", supports_no_wait=True)
        cmd_group.command("update", "adr_link_dps_update", supports_no_wait=True)
        cmd_group.command(
            "delete",
            "adr_link_dps_delete",
            confirmation=_DPS_DELETE_CONFIRMATION,
        )
        cmd_group.show_command("show", "adr_link_dps_show")
        cmd_group.command("list", "adr_link_dps_list")
        cmd_group.command(
            "wait", "adr_link_dps_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns link su", command_type=adr_link_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("add", "adr_link_su_add", supports_no_wait=True)
        cmd_group.command("update", "adr_link_su_update", supports_no_wait=True)
        cmd_group.command(
            "delete",
            "adr_link_su_delete",
            confirmation=_SU_DELETE_CONFIRMATION,
        )
        cmd_group.show_command("show", "adr_link_su_show")
        cmd_group.command("list", "adr_link_su_list")
        cmd_group.command(
            "wait", "adr_link_su_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns su instance",
        command_type=adr_update_instance_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("check-name", "adr_su_instance_check_name")
        cmd_group.command(
            "create", "adr_su_instance_create", supports_no_wait=True
        )
        cmd_group.show_command("show", "adr_su_instance_show")
        cmd_group.command("list", "adr_su_instance_list")
        cmd_group.command(
            "update", "adr_su_instance_update", supports_no_wait=True
        )
        cmd_group.command(
            "delete",
            "adr_su_instance_delete",
            confirmation=True,
            supports_no_wait=True,
        )
        cmd_group.command(
            "wait", "adr_su_instance_wait", command_type=adr_wait_ops
        )

    with self.command_group(
        "iot adr ns su software-update",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command(
            "import",
            "adr_su_software_update_import",
            supports_no_wait=True,
        )
        cmd_group.command(
            "stage",
            "adr_su_software_update_stage",
            supports_no_wait=True,
        )
        cmd_group.command(
            "list",
            "adr_su_software_update_list",
            table_transformer=(
                "[*].{UpdateProvider:updateId.provider,UpdateName:updateId.name,"
                "UpdateVersion:updateId.version,FriendlyName:friendlyName,"
                "IsDeployable:isDeployable,ManifestVersion:manifestVersion,"
                "ImportedDateTime:importedDateTime}"
            ),
        )
        cmd_group.show_command("show", "adr_su_software_update_show")
        cmd_group.command(
            "delete",
            "adr_su_software_update_delete",
            confirmation=True,
            supports_no_wait=True,
        )
        cmd_group.show_command(
            "calculate-hash", "adr_su_software_update_calculate_hash"
        )
        cmd_group.command(
            "wait", "adr_su_software_update_wait", command_type=adr_wait_ops
        )

    with self.command_group(
        "iot adr ns su software-update file",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_su_software_update_file_list")
        cmd_group.show_command("show", "adr_su_software_update_file_show")

    with self.command_group(
        "iot adr ns su software-update operation-status",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command(
            "list", "adr_su_software_update_operation_status_list"
        )
        cmd_group.show_command(
            "show", "adr_su_software_update_operation_status_show"
        )

    with self.command_group(
        "iot adr ns su software-update catalog provider",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_su_software_update_provider_list")

    with self.command_group(
        "iot adr ns su software-update catalog name",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_su_software_update_name_list")

    with self.command_group(
        "iot adr ns su software-update catalog version",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_su_software_update_version_list")

    with self.command_group(
        "iot adr ns su software-update init",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("v5", "adr_su_software_update_manifest_init_v5")

    with self.command_group(
        "iot adr ns su device-class",
        command_type=adr_software_update_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("list", "adr_su_device_class_list")
        cmd_group.show_command("show", "adr_su_device_class_show")
        cmd_group.command(
            "delete",
            "adr_su_device_class_delete",
            confirmation=True,
        )

    # Group commands
    with self.command_group(
        "iot adr ns group", command_type=adr_group_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_group_create")
        cmd_group.command("update", "adr_group_update")
        cmd_group.show_command("show", "adr_group_show")
        cmd_group.command("list", "adr_group_list")
        cmd_group.command("delete", "adr_group_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("refresh", "adr_group_refresh", supports_no_wait=True)
        cmd_group.command("list-members", "adr_group_list_members")
        cmd_group.command("count", "adr_group_count")
        cmd_group.command("wait", "adr_group_wait", command_type=adr_wait_ops)

    # Job commands
    with self.command_group(
        "iot adr ns job", command_type=adr_job_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "adr_job_create", supports_no_wait=True)
        cmd_group.command("update", "adr_job_update")
        cmd_group.show_command("show", "adr_job_show")
        cmd_group.command("list", "adr_job_list")
        cmd_group.command("delete", "adr_job_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("schedule", "adr_job_schedule", supports_no_wait=True)
        cmd_group.command("wait", "adr_job_wait", command_type=adr_wait_ops)

    # Job run commands
    with self.command_group(
        "iot adr ns job run", command_type=adr_job_run_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "adr_job_run_show")
        cmd_group.command("list", "adr_job_run_list")
        cmd_group.command("results", "adr_job_run_results")
        cmd_group.command("summary", "adr_job_run_summary")
        cmd_group.command(
            "delete", "adr_job_run_delete", confirmation=True, supports_no_wait=True
        )
        cmd_group.command(
            "cancel", "adr_job_run_cancel", confirmation=True, supports_no_wait=True
        )
        cmd_group.command(
            "wait", "adr_job_run_wait", command_type=adr_wait_ops
        )

    with self.command_group(
        "iot adr ns report", command_type=adr_report_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("generate", "adr_report_generate", supports_no_wait=True)
        cmd_group.command("latest", "adr_report_latest")
