# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import sys
import io
import os

from azure.cli.core import AzCli
from azure.cli.testsdk import LiveScenarioTest
from contextlib import contextmanager

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_DEVICE_MODULE = "test-module-"
PREFIX_CONFIG = "test-config-"
PREFIX_EDGE_CONFIG = "test-edgedeploy-"


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
            cli_name="az",
            config_dir=GLOBAL_CONFIG_DIR,
            config_env_var_prefix=ENV_VAR_PREFIX,
            commands_loader_cls=commands_loader_cls or MainCommandsLoader,
            parser_cls=AzCliCommandParser,
            logging_cls=AzCliLogging,
            help_cls=AzCliHelp,
            invocation_cls=AzCliCommandInvoker,
            output_cls=AzOutputProducer,
        )

        self.data[
            "headers"
        ] = {}  # the x-ms-client-request-id is generated before a command is to execute
        self.data["command"] = "unknown"
        self.data["completer_active"] = ARGCOMPLETE_ENV_NAME in os.environ
        self.data["query_active"] = False

        loader = self.commands_loader_cls(self)
        setattr(self, "commands_loader", loader)

        self.cloud = get_active_cloud(self)

    def get_cli_version(self):
        from azure.cli.core import __version__ as cli_version

        return cli_version


class IoTLiveScenarioTest(LiveScenarioTest):
    def __init__(self, test_scenario, entity_name, entity_rg, entity_cs, yaml_output=False):
        assert test_scenario
        assert entity_name
        assert entity_rg
        assert entity_cs

        self.entity_name = entity_name
        self.entity_rg = entity_rg
        self.entity_cs = entity_cs
        self.device_ids = []
        self.config_ids = []

        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"

        super(IoTLiveScenarioTest, self).__init__(test_scenario)

        if yaml_output:
            from . import DummyCliOutputProducer
            self.cli_ctx = DummyCliOutputProducer()

    def generate_device_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_DEVICE if not edge else PREFIX_EDGE_DEVICE, length=32
            )
            for i in range(count)
        ]
        self.device_ids.extend(names)
        return names

    def generate_module_names(self, count=1):
        return [
            self.create_random_name(prefix=PREFIX_DEVICE_MODULE, length=32)
            for i in range(count)
        ]

    def generate_config_names(self, count=1, edge=False):
        names = [
            self.create_random_name(
                prefix=PREFIX_CONFIG if not edge else PREFIX_EDGE_CONFIG, length=32
            )
            for i in range(count)
        ]
        self.config_ids.extend(names)
        return names

    # TODO: @digimaun - Maybe put a helper like this in the shared lib, when you create it?
    def command_execute_assert(self, command, asserts):
        from . import capture_output

        with capture_output() as buffer:
            self.cmd(command, checks=None)
            output = buffer.get_output()

        for a in asserts:
            assert a in output

    def tearDown(self):
        if self.device_ids:
            device = self.device_ids.pop()
            self.cmd(
                "iot hub device-identity delete -d {} --login {}".format(
                    device, self.entity_cs
                ),
                checks=self.is_empty(),
            )

            for device in self.device_ids:
                self.cmd(
                    "iot hub device-identity delete -d {} -n {} -g {}".format(
                        device, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )

        if self.config_ids:
            config = self.config_ids.pop()
            self.cmd(
                "iot hub configuration delete -c {} --login {}".format(
                    config, self.entity_cs
                ),
                checks=self.is_empty(),
            )

            for config in self.config_ids:
                self.cmd(
                    "iot hub configuration delete -c {} -n {} -g {}".format(
                        config, self.entity_name, self.entity_rg
                    ),
                    checks=self.is_empty(),
                )


def disable_telemetry(test_function):
    def wrapper(*args, **kwargs):
        print("Disabling Telemetry.")
        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        test_function(*args, **kwargs)

    return wrapper
