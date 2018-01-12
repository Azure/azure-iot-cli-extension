# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import CliCommandType
from azext_iot._factory import iot_hub_service_factory 
from azext_iot._factory import iot_service_provisioning_factory
from azext_iot import iotext_custom


def load_command_table(self, _):
    with self.command_group('iot hub', client_factory=iot_hub_service_factory) as g:
        g.custom_command('query', 'iot_query')
        g.custom_command('invoke-device-method', 'iot_device_method')
        g.custom_command('invoke-module-method', 'iot_device_module_method')
        g.custom_command('generate-sas-token', 'iot_get_sas_token')
        g.custom_command('apply-configuration', 'iot_device_configuration_apply')

        g.custom_command('show-connection-string', 'iot_get_hub_connection_string')

    with self.command_group('iot hub device-identity', client_factory=iot_hub_service_factory) as g:
        g.custom_command('create', 'iot_device_create')
        g.custom_command('show', 'iot_device_show')
        g.custom_command('list', 'iot_device_list')
        g.custom_command('delete', 'iot_device_delete')
        g.generic_update_command('update', getter_name='iot_device_show',
                                 setter_name='iot_device_update', command_type=iotext_custom)

        g.custom_command('show-connection-string', 'iot_get_device_connection_string')
        g.custom_command('import', 'iot_device_import')
        g.custom_command('export', 'iot_device_export')

    with self.command_group('iot hub module-identity', client_factory=iot_hub_service_factory) as g:
        g.custom_command('create', 'iot_device_module_create')
        g.custom_command('show', 'iot_device_module_show')
        g.custom_command('list', 'iot_device_module_list')
        g.custom_command('delete', 'iot_device_module_delete')
        g.generic_update_command('update', getter_name='iot_device_module_show',
                                 setter_name='iot_device_module_update', command_type=iotext_custom)

        g.custom_command('show-connection-string', 'iot_get_module_connection_string')

    with self.command_group('iot hub module-twin', client_factory=iot_hub_service_factory) as g:
        g.custom_command('show', 'iot_device_module_twin_show')
        g.custom_command('replace', 'iot_device_module_twin_replace')
        g.generic_update_command('update', getter_name='iot_device_module_twin_show',
                                 setter_name='iot_device_module_twin_update', command_type=iotext_custom)

    with self.command_group('iot hub device-twin', client_factory=iot_hub_service_factory) as g:
        g.custom_command('show', 'iot_device_twin_show')
        g.custom_command('replace', 'iot_device_twin_replace')
        g.generic_update_command('update', getter_name='iot_device_twin_show',
                                 setter_name='iot_device_twin_update', command_type=iotext_custom)

    with self.command_group('iot edge deployment') as g:
        g.custom_command('create', 'iot_device_configuration_create')
        g.custom_command('show', 'iot_device_configuration_show')
        g.custom_command('list', 'iot_device_configuration_list')
        g.custom_command('delete', 'iot_device_configuration_delete')
        g.generic_update_command('update', getter_name='iot_device_configuration_show',
                                 setter_name='iot_device_configuration_update', command_type=iotext_custom)

    with self.command_group('iot device', client_factory=iot_hub_service_factory) as g:
        g.custom_command('send-d2c-message', 'iot_device_send_message')
        g.custom_command('simulate', 'iot_simulate_device')

    with self.command_group('iot device c2d-message', client_factory=iot_hub_service_factory) as g:
        g.custom_command('complete', 'iot_c2d_message_complete')
        g.custom_command('abandon', 'iot_c2d_message_abandon')
        g.custom_command('reject', 'iot_c2d_message_reject')
        g.custom_command('receive', 'iot_c2d_message_receive')
        g.custom_command('receive-mqtt', 'iot_c2d_message_receive_mqtt')

    with self.command_group('iot dps enrollment' , client_factory=iot_service_provisioning_factory) as g:
        g.custom_command('create', 'iot_dps_device_enrollment_create')
        g.custom_command('list', 'iot_dps_device_enrollment_list')
        g.custom_command('show', 'iot_dps_device_enrollment_get')
        g.custom_command('update', 'iot_dps_device_enrollment_update')
        g.custom_command('delete', 'iot_dps_device_enrollment_delete')

    with self.command_group('iot dps enrollment-group' , client_factory=iot_service_provisioning_factory) as g:
        g.custom_command('create', 'iot_dps_device_enrollment_group_create')
        g.custom_command('list', 'iot_dps_device_enrollment_group_list')
        g.custom_command('show', 'iot_dps_device_enrollment_group_get')
        g.custom_command('update', 'iot_dps_device_enrollment_group_update')
        g.custom_command('delete', 'iot_dps_device_enrollment_group_delete')

    with self.command_group('iot dps registration', client_factory=iot_service_provisioning_factory) as g:
        g.custom_command('list', 'iot_dps_registration_list')
        g.custom_command('show', 'iot_dps_registration_get')
        g.custom_command('delete', 'iot_dps_registration_delete')