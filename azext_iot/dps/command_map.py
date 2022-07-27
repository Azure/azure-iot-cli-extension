# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

dps_device_registration_ops = CliCommandType(
    operations_tmpl="azext_iot.dps.commands_device_registration#{}"
)

dps_trust_bundle_ops = CliCommandType(
    operations_tmpl="azext_iot.dps.commands_trust_bundle#{}"
)


def load_dps_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group(
        "iot device registration",
        command_type=dps_device_registration_ops,
        is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "create_device_registration")
    
    with self.command_group(
        "iot dps trust-bundle",
        command_type=dps_trust_bundle_ops,
        is_preview=True,
    ) as cmd_group:
        cmd_group.command("create", "create_trust_bundle")
        cmd_group.command("update", "update_trust_bundle")
        cmd_group.show_command("show", "show_trust_bundle")
        cmd_group.command("list", "list_trust_bundles")
        cmd_group.command("delete", "delete_trust_bundle", confirmation=True)
