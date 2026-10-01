# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType

from azext_iot._factory import (
    adr_service_factory,
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

adr_link_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_link#{}",
    client_factory=adr_service_factory,
)

adr_registry_device_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_registry_device#{}",
    client_factory=adr_service_factory,
)


adr_wait_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_wait#{}",
)

adr_link_wait_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.commands_wait#{}",
    client_factory=adr_service_factory,
)

_REGISTRY_DEVICE_TABLE = (
    "{Name:name, ExternalDeviceId:properties.externalDeviceId, "
    "EnablementState:properties.enablementState, ProvisioningState:properties.provisioningState}"
)


def load_adr_commands(self, _):
    # Namespace commands
    with self.command_group(
        "iot adr ns", command_type=adr_namespace_ops, is_preview=False
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
        "iot adr ns ca", command_type=adr_ca_ops, is_preview=False
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
        "iot adr ns ca policy", command_type=adr_ca_policy_ops, is_preview=False
    ) as cmd_group:
        cmd_group.command("create", "adr_ca_policy_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_ca_policy_show")
        cmd_group.command("list", "adr_ca_policy_list")
        cmd_group.command("update", "adr_ca_policy_update", supports_no_wait=True)
        cmd_group.command("delete", "adr_ca_policy_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_ca_policy_wait", command_type=adr_wait_ops
        )

    with self.command_group(
        "iot adr ns device", command_type=adr_registry_device_ops, is_preview=False
    ) as cmd_group:
        cmd_group.command("create", "adr_registry_device_create", supports_no_wait=True)
        cmd_group.show_command("show", "adr_registry_device_show", table_transformer=_REGISTRY_DEVICE_TABLE)
        cmd_group.command("list", "adr_registry_device_list", table_transformer="[]." + _REGISTRY_DEVICE_TABLE)
        cmd_group.command("update", "adr_registry_device_update", supports_no_wait=True)
        cmd_group.command("delete", "adr_registry_device_delete", confirmation=True, supports_no_wait=True)
        cmd_group.command("wait", "adr_registry_device_wait", command_type=adr_wait_ops)

    with self.command_group(
        "iot adr ns identity", command_type=adr_namespace_ops, is_preview=False
    ) as cmd_group:
        cmd_group.show_command("show", "adr_namespace_identity_show")
        cmd_group.command("assign", "adr_namespace_identity_assign", supports_no_wait=True)
        cmd_group.command("remove", "adr_namespace_identity_remove", supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_namespace_wait", command_type=adr_wait_ops
        )

    # Link commands (mutate namespace.properties.messaging.endpoints / provisioning.endpoints)
    with self.command_group(
        "iot adr ns link", command_type=adr_link_ops, is_preview=False
    ) as cmd_group:
        cmd_group.command("add", "adr_link_add", supports_no_wait=True)
        cmd_group.command(
            "wait", "adr_link_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns link hub", command_type=adr_link_ops, is_preview=False
    ) as cmd_group:
        cmd_group.command("add", "adr_link_hub_add", supports_no_wait=True)
        cmd_group.command("update", "adr_link_hub_update", supports_no_wait=True)
        cmd_group.command("remove", "adr_link_hub_remove", confirmation=True)
        cmd_group.show_command("show", "adr_link_hub_show")
        cmd_group.command("list", "adr_link_hub_list")
        cmd_group.command(
            "wait", "adr_link_hub_wait", command_type=adr_link_wait_ops
        )

    with self.command_group(
        "iot adr ns link dps", command_type=adr_link_ops, is_preview=False
    ) as cmd_group:
        cmd_group.command("add", "adr_link_dps_add", supports_no_wait=True)
        cmd_group.command("update", "adr_link_dps_update", supports_no_wait=True)
        cmd_group.command("remove", "adr_link_dps_remove", confirmation=True)
        cmd_group.show_command("show", "adr_link_dps_show")
        cmd_group.command("list", "adr_link_dps_list")
        cmd_group.command(
            "wait", "adr_link_dps_wait", command_type=adr_link_wait_ops
        )
