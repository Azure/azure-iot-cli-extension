# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
from io import StringIO
from contextlib import redirect_stdout
from az_invoker import AzCliCommandInvoker

# Script parser and help
example_text = """Examples:

Dump `az iot hub message-endpoint create eventhub`
    python dump_help.py iot hub message-endpoint create eventhub

Dump everything within `az iot hub message-endpoint create` (will include sub-commands, such as the one above)
    python dump_help.py iot hub message-endpoint create

Dump everything within `az iot hub message-endpoint` (will include sub-group and sub-commands, such as the one above)
    python dump_help.py iot hub message-endpoint

"""
parser = argparse.ArgumentParser(
    description='Prints out the help for the method given and any child method. The contents will be saved in help.md.',
    epilog=example_text,
    formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument('commands', type=str, nargs='+',
                    help='Command you want help to be printed out for.')
args = parser.parse_args()


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
    cli = get_default_cli(invocation_cls=AzCliCommandInvoker)
    arguments = args.commands

    try:
        with redirect_stdout(output_file):
            cli.invoke(arguments, out_file=None)
    except BaseException:
        file_name = "help.md"
        help_contents = output_file.getvalue()
        # Remove special characters with preview commands
        help_contents = help_contents.replace("\x1b[36m", "")
        help_contents = help_contents.replace("\x1b[0m", "")
        help_contents = help_contents.split("\n")

        search_string = "To search AI knowledge base for examples"
        # Remove Search AI knowledge endings
        search_lines = [i for i in range(len(help_contents)) if help_contents[i].startswith(search_string)]
        while search_lines:
            line = search_lines.pop()
            # there may be extra spaces before the To search ...
            start = line - 1
            if help_contents[line - 2] == "":
                start -= 1
            # The command may cut into the next line
            end = line + 2
            if help_contents[line + 1] != "":
                end += 1
            help_contents = help_contents[:start] + help_contents[end:]

        # Remove extra lines around the ``` and make sure there is one line before the header (#)
        header_lines = [i for i in range(len(help_contents)) if help_contents[i].startswith("#")]
        while header_lines:
            line = header_lines.pop()
            help_contents = help_contents[:line + 2] + help_contents[line + 3:]

        # Remove deprecated
        deprecated_lines = [i for i in range(len(help_contents)) if "deprecated" in help_contents[i].lower()]
        while deprecated_lines:
            end = deprecated_lines.pop() + 1
            start = deprecated_lines.pop()
            help_contents = help_contents[:start] + help_contents[end:]

        # Add disclaimer
        command = ' '.join(arguments)
        disclaimer = [
            "# Disclaimer",
            "You can use `-h` with any command to view these help prompts.",
            f"For example, `az {command} -h` will retrieve all the help prompts for `az {command}`.",
            ""
        ]
        help_contents = disclaimer + help_contents

        # Add newlines back in
        help_contents = "\n".join(help_contents)
        print(f"Writing to {file_name}")

        with open(file_name, "w") as f:
            f.write(help_contents)

