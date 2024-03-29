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
