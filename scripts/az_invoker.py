# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.invocation import CommandInvoker
from azure.cli.core.commands import _pre_command_table_create


class AzCliCommandInvoker(CommandInvoker):
    def execute(self, args):
        """
        Hacked execute so it prints out helps for this command and sub commands.
        """
        args = _pre_command_table_create(self.cli_ctx, args)

        self.commands_loader.load_command_table(args)
        command = self._rudimentary_get_command(args)
        self.cli_ctx.invocation.data['command_string'] = command
        # store the commands and sub commands to be printed out
        commands = [command]

        try:
            # The command is a non group command
            self.commands_loader.command_table = {command: self.commands_loader.command_table[command]}
        except KeyError:
            # The command is a group command - build up the list of sub-groups and sub-commands while
            # also clearing out the command table to only have the sub-commands
            cmd_table = {}
            for cmd_name, cmd in self.commands_loader.command_table.items():
                if command and not cmd_name.startswith(command):
                    continue

                cmd_table[cmd_name] = cmd

                # See if there is a sub group (within this sub command) that was not accounted for yet.
                cmd_stub = cmd_name[len(command):].strip()
                group_name = cmd_stub.split(' ', 1)[0]
                sub_group = command + " " + group_name
                if sub_group != cmd_name and sub_group not in commands:
                    commands.append(sub_group)

                # Add the sub command we are looking at to order help correctly
                commands.append(cmd_name)

            self.commands_loader.command_table = cmd_table

        # Load all the arguments to avoid missing argument helps
        self.commands_loader.load_arguments()

        for sub_command in commands:
            # Ensure that there is a help in the args
            args = sub_command.split() + ["-h"]
            # The usual prep the command loader and parser
            self.commands_loader.command_name = sub_command
            self.parser.cli_ctx = self.cli_ctx
            self.parser.load_command_table(self.commands_loader)
            try:
                # This will print out the help messages
                self.parser.parse_args(args)
            except BaseException:
                # Don't want to end before getting through everything
                pass
        # End program (the help usually sends an exit of 0)
        exit(0)
