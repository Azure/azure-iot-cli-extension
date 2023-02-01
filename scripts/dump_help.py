# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
from scripts.az_invoker import AzCliCommandInvoker
from io import StringIO
from contextlib import redirect_stdout

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

        with open(file_name, "w") as f:
            f.write(help_contents)

