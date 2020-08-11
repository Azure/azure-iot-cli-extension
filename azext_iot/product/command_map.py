# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

product_ops = CliCommandType(
    operations_tmpl="azext_iot.product.command_product#{}"
)

requirements_ops = CliCommandType(
    operations_tmpl="azext_iot.product.command_requirements#{}"
)


def load_product_commands(self, _):
    with self.command_group(
        "iot product requirement", command_type=requirements_ops
    ) as g:
        g.command("list", "list")

    from azext_iot.product.test.command_map import load_product_test_commands
    load_product_test_commands(self, _)
