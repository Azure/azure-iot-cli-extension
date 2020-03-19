# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""

from azext_iot import iothub_ops_job, iothub_ops_device


def load_iothub_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub job", command_type=iothub_ops_job) as cmd_group:
        cmd_group.command("create", "job_create")
        cmd_group.command("show", "job_show")
        cmd_group.command("list", "job_list")
        cmd_group.command("cancel", "job_cancel")

    with self.command_group("iot hub device-identity", command_type=iothub_ops_device) as cmd_group:
        pass
