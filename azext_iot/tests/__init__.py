# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
import io

from azure.cli.core import AzCli
from contextlib import contextmanager


@contextmanager
def capture_output():
    class stream_buffer_tee(object):
        def __init__(self):
            self.stdout = sys.stdout
            self.buffer = io.StringIO()

        def write(self, message):
            self.stdout.write(message)
            self.buffer.write(message)

        def flush(self):
            self.stdout.flush()
            self.buffer.flush()

        def get_output(self):
            return self.buffer.getvalue()

        def close(self):
            self.buffer.close()

    _stdout = sys.stdout
    buffer_tee = stream_buffer_tee()
    sys.stdout = buffer_tee
    try:
        yield buffer_tee
    finally:
        sys.stdout = _stdout
        buffer_tee.close()


class DummyCliOutputProducer(AzCli):
    """A dummy CLI instance can be used to facilitate automation"""
    def __init__(self, commands_loader_cls=None, **kwargs):
        import os

        from azure.cli.core import MainCommandsLoader
        from azure.cli.core.commands import AzCliCommandInvoker
        from azure.cli.core.azlogging import AzCliLogging
        from azure.cli.core.cloud import get_active_cloud
        from azure.cli.core.parser import AzCliCommandParser
        from azure.cli.core._config import GLOBAL_CONFIG_DIR, ENV_VAR_PREFIX
        from azure.cli.core._help import AzCliHelp
        from azure.cli.core._output import AzOutputProducer

        from knack.completion import ARGCOMPLETE_ENV_NAME

        super(DummyCliOutputProducer, self).__init__(
            cli_name='az',
            config_dir=GLOBAL_CONFIG_DIR,
            config_env_var_prefix=ENV_VAR_PREFIX,
            commands_loader_cls=commands_loader_cls or MainCommandsLoader,
            parser_cls=AzCliCommandParser,
            logging_cls=AzCliLogging,
            help_cls=AzCliHelp,
            invocation_cls=AzCliCommandInvoker,
            output_cls=AzOutputProducer)

        self.data['headers'] = {}  # the x-ms-client-request-id is generated before a command is to execute
        self.data['command'] = 'unknown'
        self.data['completer_active'] = ARGCOMPLETE_ENV_NAME in os.environ
        self.data['query_active'] = False

        loader = self.commands_loader_cls(self)
        setattr(self, 'commands_loader', loader)

        self.cloud = get_active_cloud(self)

    def get_cli_version(self):
        from azure.cli.core import __version__ as cli_version
        return cli_version
