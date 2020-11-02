# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands import CliCommandType
from azext_iot._factory import iot_service_provisioning_factory
from azext_iot.constants import VERSION
import azext_iot._help  # noqa: F401
from azext_iot.product.command_map import load_product_commands


iothub_ops = CliCommandType(operations_tmpl="azext_iot.operations.hub#{}")
iotdps_ops = CliCommandType(
    operations_tmpl="azext_iot.operations.dps#{}",
    client_factory=iot_service_provisioning_factory,
)


class IoTExtCommandsLoader(AzCommandsLoader):
    def __init__(self, cli_ctx=None):
        super(IoTExtCommandsLoader, self).__init__(cli_ctx=cli_ctx)

    def load_command_table(self, args):
        from azext_iot.commands import load_command_table
        from azext_iot.iothub.command_map import load_iothub_commands
        from azext_iot.central.command_map import load_central_commands
        from azext_iot.digitaltwins.command_map import load_digitaltwins_commands

        load_command_table(self, args)
        load_iothub_commands(self, args)
        load_central_commands(self, args)
        load_digitaltwins_commands(self, args)
        load_product_commands(self, args)

        return self.command_table

    def load_arguments(self, command):
        from azext_iot._params import load_arguments
        from azext_iot.iothub.params import load_iothub_arguments
        from azext_iot.central.params import load_central_arguments
        from azext_iot.digitaltwins.params import load_digitaltwins_arguments
        from azext_iot.product.params import load_product_params

        load_arguments(self, command)
        load_iothub_arguments(self, command)
        load_central_arguments(self, command)
        load_digitaltwins_arguments(self, command)
        load_product_params(self, command)


COMMAND_LOADER_CLS = IoTExtCommandsLoader

__version__ = VERSION
