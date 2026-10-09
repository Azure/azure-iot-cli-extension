# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands import CliCommandType
from azure.cli.core.commands.command_operation import WaitCommandOperation
from knack.util import CLIError
from azext_iot.constants import VERSION
import azext_iot._help  # noqa: F401

iothub_ops = CliCommandType(operations_tmpl="azext_iot.operations.hub#{}")
iotdps_ops = CliCommandType(operations_tmpl="azext_iot.operations.dps#{}")


class IoTExtCommandsLoader(AzCommandsLoader):
    def __init__(self, cli_ctx=None):
        super(IoTExtCommandsLoader, self).__init__(cli_ctx=cli_ctx)

    def add_cli_command(self, name, command_operation, **kwargs):
        if isinstance(command_operation, WaitCommandOperation):
            original_handler = command_operation.handler

            def wait_handler(command_args):
                result = original_handler(command_args)
                # Some CLI core versions return a timeout exception as successful output.
                if isinstance(result, CLIError):
                    raise result
                return result

            command_operation.handler = wait_handler
        return super().add_cli_command(name, command_operation, **kwargs)

    def load_command_table(self, args):
        from azext_iot.commands import load_command_table
        from azext_iot.iothub.command_map import load_iothub_commands
        from azext_iot.central.command_map import load_central_commands
        from azext_iot.digitaltwins.command_map import load_digitaltwins_commands
        from azext_iot.dps.command_map import load_dps_commands
        from azext_iot.deviceupdate.command_map import load_deviceupdate_commands
        from azext_iot.core.command_map import load_core_commands
        from azext_iot.adr.command_map import load_adr_commands

        load_command_table(self, args)
        load_deviceupdate_commands(self, args)
        load_iothub_commands(self, args)
        load_central_commands(self, args)
        load_digitaltwins_commands(self, args)
        load_dps_commands(self, args)

        load_core_commands(self, args)
        load_adr_commands(self, args)

        return self.command_table

    def load_arguments(self, command):
        from azext_iot._params import load_arguments
        from azext_iot.iothub.params import load_iothub_arguments
        from azext_iot.central.params import load_central_arguments
        from azext_iot.digitaltwins.params import load_digitaltwins_arguments
        from azext_iot.dps.params import load_dps_arguments
        from azext_iot.deviceupdate.params import load_deviceupdate_arguments
        from azext_iot.core.params import load_core_arguments
        from azext_iot.adr.params import load_adr_arguments

        load_arguments(self, command)
        load_iothub_arguments(self, command)
        load_central_arguments(self, command)
        load_digitaltwins_arguments(self, command)
        load_dps_arguments(self, command)
        load_deviceupdate_arguments(self, command)

        load_core_arguments(self, command)
        load_adr_arguments(self, command)


COMMAND_LOADER_CLS = IoTExtCommandsLoader

__version__ = VERSION
