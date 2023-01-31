# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.invocation import CommandInvoker
from azure.cli.core.commands import _pre_command_table_create


# pylint: disable=too-few-public-methods
class AzCliCommandInvoker(CommandInvoker):

    # pylint: disable=too-many-statements,too-many-locals,too-many-branches
    def execute(self, args):
        args = _pre_command_table_create(self.cli_ctx, args)

        self.commands_loader.load_command_table(args)
        command = self._rudimentary_get_command(args)
        self.cli_ctx.invocation.data['command_string'] = command

        try:
            self.commands_loader.command_table = {command: self.commands_loader.command_table[command]}
        except KeyError:
            # Trim down the command table to reduce the number of subparsers required to optimize the performance.
            cmd_table = {}
            for cmd_name, cmd in self.commands_loader.command_table.items():
                if command and not cmd_name.startswith(command):
                    continue

                cmd_table[cmd_name] = cmd
            self.commands_loader.command_table = cmd_table

        commands = [command]
        commands.extend([c for c in self.commands_loader.command_table])
        self.commands_loader.load_arguments()

        for sub_command in commands:
            args = sub_command.split() + ["-h"]
            self.commands_loader.command_name = sub_command
            self.parser.cli_ctx = self.cli_ctx
            self.parser.load_command_table(self.commands_loader)
            try:
                self.parser.parse_args(args)
            except BaseException:
                pass
        exit(0)
