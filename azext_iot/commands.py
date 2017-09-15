from azure.cli.core.commands import cli_command
from azure.cli.core.commands.arm import cli_generic_update_command
from azext_iot._factory import iot_hub_service_factory as factory


custom_path = 'azext_iot.custom#{0}'

# IoT SDK extension commands
cli_command(__name__, 'iot device twin show', custom_path.format('iot_twin_show'), factory)
cli_command(__name__, 'iot device twin update', custom_path.format('iot_twin_update'), factory)
cli_command(__name__, 'iot device method', custom_path.format('iot_device_method'), factory)
cli_command(__name__, 'iot device sas', custom_path.format('iot_get_sas_token'), factory)
cli_command(__name__, 'iot device simulate', custom_path.format('iot_simulate_device'), factory)
cli_command(__name__, 'iot hub message send', custom_path.format('iot_hub_message_send'), factory)
cli_command(__name__, 'iot device message send', custom_path.format('iot_device_send_message_ext'), factory)
