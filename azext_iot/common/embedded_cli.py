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
        The cli that will be used for invoking commands. Should be the default CLI
    user_subscription : Optional[str]
        The invoker's subscription.
    capture_stderr : bool
        Flag for capturing the stderr during the invocation of the command.
    """
    def __init__(self, cli_ctx=None, capture_stderr: bool = False):
        super(EmbeddedCLI, self).__init__()
        self.output = ""
        self.error_code = 0
        self.az_cli = get_default_cli()
        self.user_subscription = cli_ctx.data.get('subscription_id') if cli_ctx else None
        self.capture_stderr = capture_stderr

    def invoke(
        self, command: str, subscription: Optional[str] = None, capture_stderr: Optional[bool] = None
    ):
        """
        Run a given command.

        Note that if capture_stderr is False, any error will print out to console and the error will
        propogate again when running the command self.as_json. Please ensure that the error
        is printed once in the console by setting capture_stderr to True if as_json will be called
        and False if as_json will not be called. Best practice for the future would be to set
        capture_stderr to True and handle the error from as_json.

        Parameters
        ----------
        command : str
            The command to invoke. Note that the command should omit the `az` from the command.
        subscription : Optional[str]
            Subscription for when it needs to be different from the self.user_subscription. Takes
            precedence over self.user_subscription.
        capture_stderr : Optional[bool]
            Flag for capturing the stderr during the invocation of the command. Takes
            precedence over self.capture_stderr.
        """
        output_file = StringIO()
        old_exception_handler = None

        # if capture_stderr is defined, use that, otherwise default to self.capture_stderr
        if (capture_stderr is None and self.capture_stderr) or capture_stderr:
            # Stop exception from being logged
            old_exception_handler = self.az_cli.exception_handler
            self.az_cli.exception_handler = lambda _: None

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

        if old_exception_handler:
            self.az_cli.exception_handler = old_exception_handler

        output_file.close()

        return self

    def as_json(self):
        """
        Try to parse the result of the last invoked cli command as a json.

        If the json cannot be parsed, the last invoked cli command must have failed. This will raise the error
        for easier handling.
        """
        try:
            return json.loads(self.output)
        except Exception:
            if self.get_error():
                raise self.get_error()
            # incase there is no error and no json response
            raise CLIInternalError(
                "Issue parsing received payload '{}' as json. Please try again or check resource status.".format(
                    self.output
                )
            )

    def success(self) -> bool:
        """Return if last invoked cli command was a success."""
        logger.debug("Operation error code: %s", self.error_code)
        return self.error_code == 0

    def get_error(self) -> Optional[Exception]:
        """Return error from last invoked cli command."""
        return self.az_cli.result.error

    def _ensure_json_output(self, command: str) -> str:
        """Force invoked cli command to return a json."""
        return "{} -o json".format(command)

    def _ensure_subscription(self, command: str, subscription: str) -> str:
        """Add subscription to invoked cli command."""
        return "{} --subscription '{}'".format(command, subscription)
