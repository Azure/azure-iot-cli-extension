from azure.cli.core.commands import cli_command
from azure.cli.core.commands.arm import cli_generic_update_command
from azext_iot._factory import iot_hub_service_factory as factory


custom_path = 'azext_iot.custom#{0}'

# Query
cli_command(__name__, 'iot query', custom_path.format('iot_query'), factory)

# Simulation
cli_command(__name__, 'iot device simulate', custom_path.format('iot_simulate_device'), factory)

# Messaging
cli_command(__name__, 'iot hub message send', custom_path.format('iot_hub_message_send'), factory)
cli_command(__name__, 'iot device message send', custom_path.format('iot_device_send_message_ext'), factory)

# Utility
cli_command(__name__, 'iot sas', custom_path.format('iot_get_sas_token'), factory)

# Module Ops
cli_command(__name__, 'iot device module show', custom_path.format('iot_device_module_show'), factory)
cli_command(__name__, 'iot device module create', custom_path.format('iot_device_module_create'), factory)
cli_command(__name__, 'iot device module list', custom_path.format('iot_device_module_list'), factory)
cli_command(__name__, 'iot device module delete', custom_path.format('iot_device_module_delete'), factory)
cli_generic_update_command(__name__, 'iot device module update', custom_path.format(
    'iot_device_module_show'), custom_path.format('iot_device_module_update'), factory)

# Module Twin Ops
cli_command(__name__, 'iot device module twin show', custom_path.format('iot_device_module_twin_show'), factory)
cli_generic_update_command(__name__, 'iot device module twin update', custom_path.format(
    'iot_device_module_twin_show'), custom_path.format('iot_device_module_twin_update'), factory)
cli_command(__name__, 'iot device module twin replace', custom_path.format('iot_device_module_twin_replace'), factory)

# Configuration Ops
cli_command(__name__, 'iot configuration apply', custom_path.format('iot_device_configuration_apply'), factory)

cli_command(__name__, 'iot configuration create', custom_path.format('iot_device_configuration_create'), factory)
cli_command(__name__, 'iot configuration show', custom_path.format('iot_device_configuration_show'), factory)
cli_command(__name__, 'iot configuration list', custom_path.format('iot_device_configuration_list'), factory)
cli_command(__name__, 'iot configuration delete', custom_path.format('iot_device_configuration_delete'), factory)
cli_generic_update_command(__name__, 'iot configuration update', custom_path.format(
    'iot_device_configuration_show'), custom_path.format('iot_device_configuration_update'), factory)

# Device Ops
cli_command(__name__, 'iot device create', custom_path.format('iot_device_create'), factory)
cli_command(__name__, 'iot device list', custom_path.format('iot_device_list'), factory)
cli_command(__name__, 'iot device show', custom_path.format('iot_device_show'), factory)
cli_command(__name__, 'iot device delete', custom_path.format('iot_device_delete'), factory)
cli_generic_update_command(__name__, 'iot device update', custom_path.format(
    'iot_device_show'), custom_path.format('iot_device_update'), factory)

# Method Invoke
cli_command(__name__, 'iot device method invoke', custom_path.format('iot_device_method'), factory)

# Device Twin Ops
cli_command(__name__, 'iot device twin show', custom_path.format('iot_device_twin_show'), factory)
cli_generic_update_command(__name__, 'iot device twin update', custom_path.format(
    'iot_device_twin_show'), custom_path.format('iot_device_twin_update'), factory)
