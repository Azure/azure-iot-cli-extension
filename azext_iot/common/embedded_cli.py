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
    def __init__(self, cli_ctx=None):
        super(EmbeddedCLI, self).__init__()
        self.output = ""
        self.error_code = 0
        self.az_cli = get_default_cli()
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

    def success(self) -> bool:
        logger.debug("Operation error code: %s", self.error_code)
        return self.error_code == 0

    def get_error(self) -> Optional[Exception]:
        return self.az_cli.result.error

    def _ensure_json_output(self, command: str) -> str:
        return "{} -o json".format(command)

    def _ensure_subscription(self, command: str, subscription: str) -> str:
        return "{} --subscription '{}'".format(command, subscription)
