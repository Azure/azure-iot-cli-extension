# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
from io import StringIO
from contextlib import redirect_stdout
from knack.invocation import CommandInvoker
from azure.cli.core.commands import _pre_command_table_create

# Script parser and help
example_text = """Examples:

Dump `az iot hub message-endpoint create eventhub`
    python dump_help.py iot hub message-endpoint create eventhub

Dump everything within `az iot hub message-endpoint create` (will include sub-commands, such as the one above)
    python dump_help.py iot hub message-endpoint create

Dump everything within `az iot hub message-endpoint` (will include sub-group and sub-commands, such as the one above)
    python dump_help.py iot hub message-endpoint

To save to a file, use > as so:
    python dump_help.py iot hub message-endpoint > help_dump.txt

"""
parser = argparse.ArgumentParser(
    description='Prints out the help for the method given and any child method.',
    epilog=example_text,
    formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument('commands', type=str, nargs='+',
                    help='Command you want help to be printed out for.')
args = parser.parse_args()


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


def get_default_cli(**kwargs):
    from azure.cli.core import AzCli, MainCommandsLoader
    from azure.cli.core.azlogging import AzCliLogging
    from azure.cli.core.commands import AzCliCommandInvoker
    from azure.cli.core.parser import AzCliCommandParser
    from azure.cli.core._config import GLOBAL_CONFIG_DIR, ENV_VAR_PREFIX
    from azure.cli.core._help import AzCliHelp
    from azure.cli.core._output import AzOutputProducer

    commands_loader_cls = kwargs.get("commands_loader_cls", MainCommandsLoader)
    invocation_cls = kwargs.get("invocation_cls", AzCliCommandInvoker)
    parser_cls = kwargs.get("parser_cls", AzCliCommandParser)
    logging_cls = kwargs.get("logging_cls", AzCliLogging)
    output_cls = kwargs.get("output_cls", AzOutputProducer)
    help_cls = kwargs.get("help_cls", AzCliHelp)

    return AzCli(cli_name='az',
                 config_dir=GLOBAL_CONFIG_DIR,
                 config_env_var_prefix=ENV_VAR_PREFIX,
                 commands_loader_cls=commands_loader_cls,
                 invocation_cls=invocation_cls,
                 parser_cls=parser_cls,
                 logging_cls=logging_cls,
                 output_cls=output_cls,
                 help_cls=help_cls)


if __name__ == "__main__":
    output_file = StringIO()
    print(args.commands)
    cli = get_default_cli(invocation_cls=AzCliCommandInvoker)
    print(cli)
    arguments = args.commands

    try:
        # with redirect_stdout(output_file):
            cli.invoke(arguments, out_file=None)
    except BaseException:
        file_name = "help_" + "_".join(args.commands) + ".md"

        # Remove special characters with preview commands
        help_contents = output_file.getvalue().replace("\x1b[36m", "")
        help_contents = help_contents.replace("\x1b[0m", "")

        # Remove deprecated
        deprecated_lines = [i for i in range(len(help_contents)) if "deprecated" in help_contents[i].lower()]
        while deprecated_lines:
            start = deprecated_lines.pop(0)
            end = deprecated_lines.pop(0) + 1
            help_contents = help_contents[:start] + help_contents[end:]

        print(help_contents)
        print(f"Writing to {file_name}")

        with open(file_name, "w") as f:
            f.write(help_contents)

