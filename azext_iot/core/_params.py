# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.arguments import CLIArgumentType
from azure.cli.core.commands.parameters import (get_location_type,
                                                get_resource_name_completion_list,
                                                get_enum_type,
                                                get_three_state_flag,
                                                tags_type)

from .shared import IotDpsSku


dps_name_type = CLIArgumentType(
    options_list=['--name', '-n'],
    completer=get_resource_name_completion_list('Microsoft.Devices/ProvisioningServices'),
    help='IoT Hub Device Provisioning Service name')


def load_arguments(self, _):
    # Arguments for IoT DPS
    with self.argument_context('iot dps') as c:
        c.argument('tags', tags_type)

    # Direct DPS resource commands use --name -n
    for subgroup in ['create', 'update', 'show', 'delete']:
        with self.argument_context('iot dps {}'.format(subgroup)) as c:
            c.argument('dps_name', dps_name_type, id_part='name')

    with self.argument_context('iot dps create') as c:
        c.argument('location', get_location_type(self.cli_ctx),
                   help='Location of your IoT Hub Device Provisioning Service. '
                   'Default is the location of target resource group.')
        c.argument('sku', arg_type=get_enum_type(IotDpsSku),
                   help='Pricing tier for the IoT Hub Device Provisioning Service.')
        c.argument('unit', help='Units in your IoT Hub Device Provisioning Service.', type=int)
        c.argument('enable_data_residency', arg_type=get_three_state_flag(),
                   options_list=['--enforce-data-residency', '--edr'],
                   help='Enforce data residency for this IoT Hub Device Provisioning Service by disabling '
                   'cross geo-pair disaster recovery. This property is immutable once set on the resource. '
                   'Only available in select regions. Learn more at https://aka.ms/dpsdr')
