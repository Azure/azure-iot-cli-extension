# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands.parameters import (location_type, enum_choice_list,
                                                get_resource_name_completion_list, CliArgumentType)
from azure.cli.core.commands import register_cli_argument
from azext_iot._factory import iot_hub_service_factory
from azext_iot.custom import ProtocolType, SettleType


hub_name_type = CliArgumentType(
    completer=get_resource_name_completion_list('Microsoft.Devices/IotHubs'),
    help='IoT Hub name.')

register_cli_argument('iot hub', 'hub_name', hub_name_type, options_list=('--name', '-n'),
                      id_part='name')
register_cli_argument('iot device', 'hub_name', hub_name_type)
register_cli_argument('iot', 'device_id', options_list=('--device-id', '-d'), help='Device Id.')

# IoT Extensions
# Arguments for 'iot twin update'
register_cli_argument('iot device twin update', 'update_json', options_list=('--json', '-j'),
                      arg_group="twin", help='Json to update device twin with. Provide file path or raw json.')
register_cli_argument('iot device twin', 'hub_name', hub_name_type)

# Arguments for 'iot device method'
register_cli_argument('iot device method', 'hub_name', hub_name_type)
register_cli_argument('iot device method', 'method_name', help="Method to be invoked on device.",
                      arg_group="method")
register_cli_argument('iot device method', 'method_payload', help="Payload to be passed to method.",
                      arg_group="method")

# Arguments for 'iot device sas'
register_cli_argument('iot sas', 'hub_name', hub_name_type)
register_cli_argument('iot sas', 'duration',
                      help="Token duration in seconds. Default is 1 hour.")
register_cli_argument('iot sas', 'policy_name',
                      help='Shared access policy to use.')

# Arguments for 'iot simulation'
register_cli_argument('iot device simulate', 'hub_name', hub_name_type)
register_cli_argument('iot device simulate', 'protocol',
                      help='Protocol used to send and receive messages.',
                      arg_group="simulation", **enum_choice_list(ProtocolType))
register_cli_argument('iot device simulate', 'settle',
                      help='Indicate how the received messages should be settled.',
                      arg_group="simulation", **enum_choice_list(SettleType))
register_cli_argument('iot device simulate', 'receive_count', options_list=('--receive-count, -rc'),
                      arg_group="simulation", help="Number of messages to receive as device. Use -1 for infinity.",
                      type=int)
register_cli_argument('iot device simulate', 'message_count', options_list=('--message-count, -mc'),
                      arg_group="simulation", help="Number of messages to send as device.", type=int)
register_cli_argument('iot device simulate', 'message_interval', options_list=('--message-interval, -mi'),
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
