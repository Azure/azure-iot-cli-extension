# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core import AzCommandsLoader
from azext_iot._factory import iot_hub_service_factory
from azure.cli.core.commands import CliCommandType
import azext_iot._help  # pylint: disable=unused-import


iotext_custom = CliCommandType(
    operations_tmpl='azext_iot.custom#{}',
    client_factory=iot_hub_service_factory
)


class IoTExtCommandsLoader(AzCommandsLoader):
    def __init__(self, cli_ctx=None):
        super(IoTExtCommandsLoader, self).__init__(cli_ctx=cli_ctx,
                                                   min_profile='2017-03-10-profile',
                                                   custom_command_type=iotext_custom)

    def load_command_table(self, args):
        from azext_iot.commands import load_command_table
        load_command_table(self, args)
        return self.command_table

    def load_arguments(self, command):
        from azext_iot._params import load_arguments
        load_arguments(self, command)


COMMAND_LOADER_CLS = IoTExtCommandsLoader
