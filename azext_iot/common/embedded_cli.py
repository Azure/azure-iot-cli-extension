# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import shlex
# from azure.cli.core import get_default_cli
from azure.cli.core.azclierror import CLIInternalError
from knack.log import get_logger
from io import StringIO

logger = get_logger(__name__)


def get_default_cli(help_cls=None):
    from azure.cli.core import AzCli, MainCommandsLoader
    from azure.cli.core.azlogging import AzCliLogging
    from azure.cli.core.commands import AzCliCommandInvoker
    from azure.cli.core.parser import AzCliCommandParser
    from azure.cli.core._config import GLOBAL_CONFIG_DIR, ENV_VAR_PREFIX
    from azure.cli.core._help import AzCliHelp
    from azure.cli.core._output import AzOutputProducer

    return AzCli(cli_name='az',
                 config_dir=GLOBAL_CONFIG_DIR,
                 config_env_var_prefix=ENV_VAR_PREFIX,
                 commands_loader_cls=MainCommandsLoader,
                 invocation_cls=AzCliCommandInvoker,
                 parser_cls=AzCliCommandParser,
                 logging_cls=AzCliLogging,
                 output_cls=AzOutputProducer,
                 help_cls=help_cls or AzCliHelp)


class EmbeddedCLI(object):
    def __init__(self, cli_ctx=None, help_cls=None):
        super(EmbeddedCLI, self).__init__()
        self.output = ""
        self.error_code = 0
        self.az_cli = get_default_cli(help_cls)
        self.user_subscription = cli_ctx.data.get('subscription_id') if cli_ctx else None

    def invoke(self, command: str, subscription: str = None):
        output_file = StringIO()

        command = self._ensure_json_output(command=command)
        # prioritize subscription passed into invoke
        if subscription:
            command = self._ensure_subscription(
                command=command, subscription=subscription
            )
        elif self.user_subscription:
            command = self._ensure_subscription(
                command=command, subscription=self.user_subscription
            )

        # TODO: Capture stderr?
        try:
            self.error_code = (
                self.az_cli.invoke(shlex.split(command), out_file=output_file) or 0
            )
        except SystemExit as se:
            # Support caller error handling
            self.error_code = se.code

        self.output = output_file.getvalue()
        logger.debug(
            "Embedded CLI received error code: %s, output: '%s'",
            self.error_code,
            self.output,
        )
        output_file.close()

        return self

    def as_json(self):
        try:
            return json.loads(self.output)
        except Exception:
            raise CLIInternalError(
                "Issue parsing received payload '{}' as json. Please try again or check resource status.".format(
                    self.output
                )
            )

    def get_help(self, command: str):
        output_file = StringIO()
        command = "{} -h".format(command)
        self.az_cli.help_cls
        self.az_cli.invoke(shlex.split(command), out_file=output_file)

        # TODO: Capture stderr?
        try:
            self.error_code = (
                self.az_cli.invoke(shlex.split(command), out_file=output_file) or 0
            )
        except SystemExit as se:
            # Support caller error handling
            self.error_code = se.code

        self.output = output_file.getvalue()
        logger.debug(
            "Embedded CLI received error code: %s, output: '%s'",
            self.error_code,
            self.output,
        )
        output_file.close()

        return self

    def success(self) -> bool:
        logger.debug("Operation error code: %s", self.error_code)
        return self.error_code == 0

    def _ensure_json_output(self, command: str) -> str:
        return "{} -o json".format(command)

    def _ensure_subscription(self, command: str, subscription: str) -> str:
        return "{} --subscription '{}'".format(command, subscription)
