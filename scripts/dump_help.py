# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import argparse
from scripts.az_invoker import AzCliCommandInvoker
from io import StringIO

parser = argparse.ArgumentParser(description='Prints out the help for the method given and any child method.')
parser.add_argument('commands', type=str, nargs='+',
                    help='command you want help to be printed out for')
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
    arguments = args.commands + ["-h"]
    # arguments = shlex.split(args.command)
    # import pdb; pdb.set_trace()
    cli.invoke(arguments, out_file=output_file)

    # cli.get_help("iot hub message-endpoint")
