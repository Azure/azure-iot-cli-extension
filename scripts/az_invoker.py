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
        # tuple structure: (command_name, number of sub_headers for md file)
        command_list = [(command, 1)]

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
                g = 0
                while g < cmd_stub.count(" "):
                    g += 1
                    group_name = " ".join(cmd_stub.split(' ')[:g])
                    sub_group = command + " " + group_name
                    sub_group_tuple = (sub_group, g + 1)
                    if sub_group != cmd_name and sub_group_tuple not in command_list:
                        # import pdb; pdb.set_trace()
                        command_list.append(sub_group_tuple)

                # Add the sub command we are looking at to order help correctly
                command_list.append((cmd_name, cmd_stub.count(" ") + 2))

            self.commands_loader.command_table = cmd_table

        # Load all the arguments to avoid missing argument helps
        self.commands_loader.load_arguments()

        for sub_command, header in command_list:
            print("#" * header + " " + sub_command)
            print("```")
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
                print("```\n")
        # End program (the help usually sends an exit of 0)
        exit(0)
