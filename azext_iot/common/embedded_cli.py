# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import shlex
from azure.cli.core import get_default_cli
from knack.log import get_logger
from knack.util import CLIError
from io import StringIO

logger = get_logger(__name__)


class EmbeddedCLI(object):
    def __init__(self):
        super(EmbeddedCLI, self).__init__()
        self.output = ""
        self.error_code = 0
        self.az_cli = get_default_cli()

    def invoke(self, command: str, subscription: str = None):
        output_file = StringIO()
        command = self._ensure_json_output(command=command)
        if subscription:
            command = self._ensure_subscription(
                command=command, subscription=subscription
            )
        self.error_code = (
            self.az_cli.invoke(shlex.split(command), out_file=output_file) or 0
        )
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
        except:
            raise CLIError(
                "Issue parsing received payload '{}' as json. Please try again or check resource status.".format(
                    self.output
                )
            )

    def success(self):
        logger.debug("Operation error code: %s", self.error_code)
        return self.error_code == 0

    def _ensure_json_output(self, command: str):
        return "{} -o json".format(command)

    def _ensure_subscription(self, command: str, subscription: str):
        return "{} --subscription '{}'".format(command, subscription)
