# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import shlex
from typing import Optional
from azure.cli.core import get_default_cli
from azure.cli.core.azclierror import CLIInternalError
from knack.log import get_logger
from io import StringIO

logger = get_logger(__name__)


class EmbeddedCLI(object):
    """
    An embedded CLI wrapper for easily invoking commands.

    ...

    Attributes
    ----------
    output : str
        The output of the last invoked cli command. If the last command failed or there were no runs,
        will return ""
    error_code : int
        Error code of the last invoked cli command. If no runs, will be 0.
    az_cli : AzCli
        The cli that will be used for invoking commands. Should be the default CLI.
    user_subscription : Optional[str]
        The invoker's subscription.
    capture_stderr : bool
        Flag to determine whether we capture (don't print) output from invoked commands, but raise errors
        when they occur.
    """
    def __init__(self, cli_ctx=None, capture_stderr: bool = False):
        super(EmbeddedCLI, self).__init__()
        self.output = ""
        self.error_code = 0
        self.az_cli = get_default_cli()
        self.user_subscription = cli_ctx.data.get('subscription_id') if cli_ctx else None
        self.capture_stderr = capture_stderr

    def invoke(
        self, command: str, subscription: str = None, capture_stderr: Optional[bool] = None
    ):
        """
        Run a given command.

        Note that if capture_stderr is True, any error during invocation will be raised.

        Parameters
        ----------
        command : str
            The command to invoke. Note that the command should omit the `az` from the command.
        subscription : Optional[str]
            Subscription for when it needs to be different from the self.user_subscription. Takes
            precedence over self.user_subscription.
        capture_stderr : Optional[bool]
            Flag to determine whether we capture (don't print) output from invoked commands, but raise errors
            when they occur. Takes precedence over self.capture_stderr.
        """
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

        args = shlex.split(command)
        capture = self.capture_stderr if capture_stderr is None else capture_stderr
        old_exception_handler = self.az_cli.exception_handler
        self.output = ""
        self.error_code = 0
        self.az_cli.result = None
        if capture:
            self.az_cli.exception_handler = lambda _: 1

        with StringIO() as output_file:
            try:
                self.error_code = self.az_cli.invoke(args, out_file=output_file) or 0
            except SystemExit as error:
                self.error_code = error.code or 0
            finally:
                self.output = output_file.getvalue()
                self.az_cli.exception_handler = old_exception_handler

        logger.debug(
            "Embedded CLI received error code: %s, output: '%s'",
            self.error_code,
            self.output,
        )

        if capture:
            self.raise_for_error()

        return self

    def raise_for_error(self):
        """Preserve the command failure before consuming its output."""
        if not self.success():
            error = self.get_error()
            if isinstance(error, BaseException):
                raise error
            raise CLIInternalError(f"Embedded CLI command failed with exit code {self.error_code}.")
        return self

    def as_json(self):
        """
        Parse successful command output, preserving command errors before decoding.
        """
        self.raise_for_error()
        try:
            return json.loads(self.output)
        except json.JSONDecodeError as error:
            raise CLIInternalError(
                "Issue parsing received payload as json. Please try again or check resource status."
            ) from error

    def success(self) -> bool:
        """Return if last invoked cli command was a success."""
        logger.debug("Operation error code: %s", self.error_code)
        return self.error_code == 0

    def get_error(self) -> Optional[BaseException]:
        """Return error from last invoked cli command."""
        result = self.az_cli.result
        return result.error if result is not None else None

    def _ensure_json_output(self, command: str) -> str:
        """Force invoked cli command to return a json."""
        return "{} -o json".format(command)

    def _ensure_subscription(self, command: str, subscription: str) -> str:
        """Add subscription to invoked cli command."""
        command_group = command.lstrip().split(maxsplit=1)[0]
        if command_group in {"account", "ad", "extension"}:
            return command
        return "{} --subscription '{}'".format(command, subscription)
