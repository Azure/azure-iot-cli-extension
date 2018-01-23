# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""

from azure.cli.core.commands import CliCommandType
from azext_iot._factory import iot_service_provisioning_factory as dps_factory
from azext_iot import iotext_custom


def load_command_table(self, _):
    """
    Load CLI commands
    """
    with self.command_group('iot hub') as cmd_group:
        cmd_group.custom_command('query', 'iot_query')
        cmd_group.custom_command('invoke-device-method', 'iot_device_method')
        cmd_group.custom_command('invoke-module-method', 'iot_device_module_method')
        cmd_group.custom_command('generate-sas-token', 'iot_get_sas_token')
        cmd_group.custom_command('apply-configuration', 'iot_device_configuration_apply')

        cmd_group.custom_command('show-connection-string', 'iot_get_hub_connection_string')

    with self.command_group('iot hub device-identity') as cmd_group:
        cmd_group.custom_command('create', 'iot_device_create')
        cmd_group.custom_command('show', 'iot_device_show')
        cmd_group.custom_command('list', 'iot_device_list')
        cmd_group.custom_command('delete', 'iot_device_delete')
        cmd_group.generic_update_command('update', getter_name='iot_device_show',
                                         setter_name='iot_device_update',
                                         command_type=iotext_custom)

        cmd_group.custom_command('show-connection-string', 'iot_get_device_connection_string')
        cmd_group.custom_command('import', 'iot_device_import')
        cmd_group.custom_command('export', 'iot_device_export')

    with self.command_group('iot hub module-identity') as cmd_group:
        cmd_group.custom_command('create', 'iot_device_module_create')
        cmd_group.custom_command('show', 'iot_device_module_show')
        cmd_group.custom_command('list', 'iot_device_module_list')
        cmd_group.custom_command('delete', 'iot_device_module_delete')
        cmd_group.generic_update_command('update', getter_name='iot_device_module_show',
                                         setter_name='iot_device_module_update',
                                         command_type=iotext_custom)

        cmd_group.custom_command('show-connection-string', 'iot_get_module_connection_string')

    with self.command_group('iot hub module-twin') as cmd_group:
        cmd_group.custom_command('show', 'iot_device_module_twin_show')
        cmd_group.custom_command('replace', 'iot_device_module_twin_replace')
        cmd_group.generic_update_command('update', getter_name='iot_device_module_twin_show',
                                         setter_name='iot_device_module_twin_update',
                                         command_type=iotext_custom)

    with self.command_group('iot hub device-twin') as cmd_group:
        cmd_group.custom_command('show', 'iot_device_twin_show')
        cmd_group.custom_command('replace', 'iot_device_twin_replace')
        cmd_group.generic_update_command('update', getter_name='iot_device_twin_show',
                                         setter_name='iot_device_twin_update',
                                         command_type=iotext_custom)

    with self.command_group('iot edge deployment') as cmd_group:
        cmd_group.custom_command('create', 'iot_device_configuration_create')
        cmd_group.custom_command('show', 'iot_device_configuration_show')
        cmd_group.custom_command('list', 'iot_device_configuration_list')
        cmd_group.custom_command('delete', 'iot_device_configuration_delete')
        cmd_group.generic_update_command('update', getter_name='iot_device_configuration_show',
                                         setter_name='iot_device_configuration_update',
                                         command_type=iotext_custom)

    with self.command_group('iot device') as cmd_group:
        cmd_group.custom_command('send-d2c-message', 'iot_device_send_message')
        cmd_group.custom_command('simulate', 'iot_simulate_device')
        cmd_group.custom_command('upload-file', 'iot_device_upload_file')

    with self.command_group('iot device c2d-message') as cmd_group:
        cmd_group.custom_command('complete', 'iot_c2d_message_complete')
        cmd_group.custom_command('abandon', 'iot_c2d_message_abandon')
        cmd_group.custom_command('reject', 'iot_c2d_message_reject')
        cmd_group.custom_command('receive', 'iot_c2d_message_receive')

    with self.command_group('iot dps enrollment', client_factory=dps_factory) as cmd_group:
        cmd_group.custom_command('create', 'iot_dps_device_enrollment_create')
        cmd_group.custom_command('list', 'iot_dps_device_enrollment_list')
        cmd_group.custom_command('show', 'iot_dps_device_enrollment_get')
        cmd_group.custom_command('update', 'iot_dps_device_enrollment_update')
        cmd_group.custom_command('delete', 'iot_dps_device_enrollment_delete')

    with self.command_group('iot dps enrollment-group', client_factory=dps_factory) as cmd_group:
        cmd_group.custom_command('create', 'iot_dps_device_enrollment_group_create')
        cmd_group.custom_command('list', 'iot_dps_device_enrollment_group_list')
        cmd_group.custom_command('show', 'iot_dps_device_enrollment_group_get')
        cmd_group.custom_command('update', 'iot_dps_device_enrollment_group_update')
        cmd_group.custom_command('delete', 'iot_dps_device_enrollment_group_delete')

    with self.command_group('iot dps registration', client_factory=dps_factory) as cmd_group:
        cmd_group.custom_command('list', 'iot_dps_registration_list')
        cmd_group.custom_command('show', 'iot_dps_registration_get')
        cmd_group.custom_command('delete', 'iot_dps_registration_delete')
