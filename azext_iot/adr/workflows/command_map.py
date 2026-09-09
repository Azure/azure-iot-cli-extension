# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType


adr_workflow_ops = CliCommandType(
    operations_tmpl="azext_iot.adr.workflows.commands#{}"
)


def load_adr_workflow_commands(self, _):
    with self.command_group(
        "iot adr ns", command_type=adr_workflow_ops, is_preview=True
    ) as group:
        group.command("check", "adr_namespace_check")
        group.command("setup", "adr_namespace_setup")
