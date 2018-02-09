# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands import CliCommandType
from azext_iot._factory import iot_hub_service_factory, iot_service_provisioning_factory
import azext_iot._help  # pylint: disable=unused-import


iothub_ops = CliCommandType(
    operations_tmpl='azext_iot.operations.hub#{}',
    client_factory=iot_hub_service_factory
)

iotdps_ops = CliCommandType(
    operations_tmpl='azext_iot.operations.dps#{}',
    client_factory=iot_service_provisioning_factory
)


class IoTExtCommandsLoader(AzCommandsLoader):
    def __init__(self, cli_ctx=None):
        super(IoTExtCommandsLoader, self).__init__(cli_ctx=cli_ctx,
                                                   min_profile='2017-03-10-profile')

    def load_command_table(self, args):
        from azext_iot.commands import load_command_table
        load_command_table(self, args)
        return self.command_table

    def load_arguments(self, command):
        from azext_iot._params import load_arguments
        load_arguments(self, command)


COMMAND_LOADER_CLS = IoTExtCommandsLoader
