# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands.parameters import (location_type, enum_choice_list,
                                                get_resource_name_completion_list, CliArgumentType)
from azure.cli.core.commands import register_cli_argument
from azext_iot.common.shared import DeviceStatusType, ProtocolType, SettleType, DeviceAuthType
from azext_iot.custom import iot_device_list
from ._factory import iot_hub_service_factory


hub_name_type = CliArgumentType(
    completer=get_resource_name_completion_list('Microsoft.Devices/IotHubs'),
    help='IoT Hub name.')


register_cli_argument('iot', 'device_id',
                      options_list=('--device-id', '-d'), help='Device Id.')
register_cli_argument('iot hub', 'hub_name', hub_name_type,
                      options_list=('--name', '-n'), id_part='name')
register_cli_argument('iot device', 'hub_name', hub_name_type,
                      options_list=('--hub-name', '-n'), id_part='hub-name')

# Arguments for 'iot query'
register_cli_argument('iot query', 'query_command', options_list=('--query-command', '-q'), arg_group="query",
                      help='Query an IoT hub to retrieve device and module twin data using a SQL-like language.')
register_cli_argument('iot query', 'hub_name', hub_name_type, options_list=('--hub-name', '-n'))
register_cli_argument('iot query', 'top', help='Maximum number of query records to return.', type=int)


# Arguments for 'iot device method'
register_cli_argument('iot device method invoke', 'method_name', help="Method to be invoked on device.",
                      arg_group="Method")
register_cli_argument('iot device method invoke', 'method_payload',
                      help='Json payload to be passed to method. Provide file path or raw json.',
                      arg_group="Method")
register_cli_argument('iot device method invoke', 'timeout',
                      arg_group="Method",
                      help='Maximum number of seconds for method result timeout.', type=int)

# Arguments for 'iot device sas'
register_cli_argument('iot sas', 'hub_name', hub_name_type, options_list=('--hub-name', '-n'))
register_cli_argument('iot sas', 'duration',
                      help="Token duration in seconds. Default is 1 hour.")
register_cli_argument('iot sas', 'policy_name',
                      help='Shared access policy to use.')

# Arguments for 'iot simulation'
# register_cli_argument('iot device simulate', 'hub_name', hub_name_type)
register_cli_argument('iot device simulate', 'protocol',
                      help='Protocol used to send and receive messages.',
                      arg_group="simulation", **enum_choice_list(ProtocolType))
register_cli_argument('iot device simulate', 'settle',
                      help='Indicate how the received messages should be settled.',
                      arg_group="simulation", **enum_choice_list(SettleType))
register_cli_argument('iot device simulate', 'receive_count', options_list=('--receive-count', '-rc'),
                      arg_group="simulation", help="Number of messages to receive as device. Use -1 for infinity.",
                      type=int)
register_cli_argument('iot device simulate', 'message_count', options_list=('--message-count', '-mc'),
                      arg_group="simulation", help="Number of messages to send as device.", type=int)
register_cli_argument('iot device simulate', 'message_interval', options_list=('--message-interval', '-mi'),
                      arg_group="simulation", help="Delay between each message sent.", type=int)
register_cli_argument('iot device simulate', 'file_path', options_list=('--upload-file-path'),
                      arg_group="simulation", help='Upload a file from simulated device')

# Arguments for new 'iot device message send'
register_cli_argument('iot device message send', 'data', help='Device-to-cloud message body.',
                      arg_group='Messaging')
register_cli_argument('iot device message send', 'message_id', help='Device-to-cloud message Id.',
                      arg_group='Messaging')
register_cli_argument('iot device message send', 'correlation_id',
                      help='Device-to-cloud message correlation Id.',
                      arg_group='Messaging')
register_cli_argument('iot device message send', 'protocol',
                      help='Device-to-cloud message send protocol.',
                      arg_group='Messaging', **enum_choice_list(ProtocolType))
register_cli_argument('iot device message send', 'user_id',
                      help='Device-to-cloud message user Id appended as property.',
                      arg_group='Messaging')

# Arguments for 'iot device message push'
register_cli_argument('iot hub message send', 'message_id', help='Cloud-to-device message Id.',
                      arg_group='Messaging')
register_cli_argument('iot hub message send', 'correlation_id',
                      help='Cloud-to-device message correlation Id.',
                      arg_group='Messaging')
register_cli_argument('iot hub message send', 'wait_feedback',
                      help='Await device feedback.',
                      arg_group='Messaging')
register_cli_argument('iot hub message send', 'data', help='Cloud-to-device message body.',
                      arg_group='Messaging')

# Arguments for 'iot device create'
register_cli_argument('iot device create', 'auth_method',
                      help="Enumeration determining target device authorization method.",
                      **enum_choice_list(DeviceAuthType))
register_cli_argument('iot device create', 'edge_enabled',
                      help="Switch indicating if device is edge enabled. Default: False")
register_cli_argument('iot device create', 'primary_thumbprint',
                      help='Self-signed certificate thumbprint to use for primary key.')
register_cli_argument('iot device create', 'secondary_thumbprint',
                      help='Self-signed certificate thumbprint to use for secondary key.')
register_cli_argument('iot device create', 'status',
                      help='Create device with target status.',
                      **enum_choice_list(DeviceStatusType))


# Arguments for 'iot device list'
register_cli_argument('iot device list', 'top',
                      help='Maximum number of device twin identities to return.', type=int)


# Modules
register_cli_argument('iot device module', 'module_id', options_list=('--module-id', '-m'), help='Module Id.')

# Arguments for 'iot device module create'
register_cli_argument('iot device module create', 'auth_method',
                      help="Enumeration determining target module authorization method.",
                      **enum_choice_list(DeviceAuthType))

# Arguments for 'iot device module list'
register_cli_argument('iot device module list', 'top',
                      help='Maximum number of module twin identities to return.', type=int)

# Arguments for 'iot device module twin replace'
register_cli_argument('iot device module twin replace', 'target_json',
                      options_list=('--json', '-j'),
                      help='Json to replace existing module twin with. Provide file path or raw json.')


# Configurations
register_cli_argument('iot configuration', 'hub_name', hub_name_type,
                      options_list=('--hub-name', '-n'), id_part='hub-name')
register_cli_argument('iot configuration', 'config_id', options_list=('--config-id', '-c'),
                      help='Configuration Id.', arg_group='Config')

# Arguments for 'iot configuration list'
register_cli_argument('iot configuration list', 'top', help='Maximum number of edge configurations to return.', type=int)

# Arguments for 'iot configuration create'
register_cli_argument('iot configuration', 'content',
                      options_list=('--content', '-k'),
                      help='IoT Edge configuration content.',
                      arg_group='Config')
register_cli_argument('iot configuration create', 'target_condition',
                      help='Target condition in which the provided content applies to.',
                      arg_group='Config')
register_cli_argument('iot configuration create', 'priority',
                      help='Weight of configuration in case of competing rules (highest wins).',
                      arg_group='Config')
register_cli_argument('iot configuration create', 'labels',
                      help='Dictionary of labels to be applied to target configuration.',
                      arg_group='Config')
