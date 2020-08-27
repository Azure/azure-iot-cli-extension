# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

tests_ops = CliCommandType(operations_tmpl="azext_iot.product.test.command_tests#{}")

test_tasks_ops = CliCommandType(
    operations_tmpl="azext_iot.product.test.command_test_tasks#{}"
)

test_cases_ops = CliCommandType(
    operations_tmpl="azext_iot.product.test.command_test_cases#{}"
)

test_runs_ops = CliCommandType(operations_tmpl="azext_iot.product.test.command_test_runs#{}")


def load_product_test_commands(self, _):
    with self.command_group("iot product test", command_type=tests_ops) as g:
        g.command("create", "create")
        g.command("update", "update")
        g.show_command("show", "show")
        g.command("search", "search")
    with self.command_group("iot product test case", command_type=test_cases_ops) as g:
        g.command("list", "list")
        g.command("update", "update")
    with self.command_group("iot product test task", command_type=test_tasks_ops) as g:
        g.command("create", "create")
        g.command("delete", "delete")
        g.show_command("show", "show")
    with self.command_group("iot product test run", command_type=test_runs_ops) as g:
        g.show_command("show", "show")
        g.command("submit", "submit")
