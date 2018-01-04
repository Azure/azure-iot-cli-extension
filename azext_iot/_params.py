# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.arguments import CLIArgumentType
from azure.cli.core.commands.parameters import (
    resource_group_name_type,
    get_enum_type,
    get_resource_name_completion_list,
    get_three_state_flag
)
from azext_iot.common.shared import (
    DeviceStatusType,
    SettleType,
    DeviceAuthType,
    KeyType
)

hub_name_type = CLIArgumentType(
    completer=get_resource_name_completion_list('Microsoft.Devices/IotHubs'),
    help='IoT Hub name.')


def load_arguments(self, _):
    with self.argument_context('iot') as c:
        c.argument('resource_group_name', arg_type=resource_group_name_type)
        c.argument('hub_name', options_list=['--hub-name', '-n'], arg_type=hub_name_type)
        c.argument('device_id', options_list=['--device-id', '-d'], help='Target Device.')
        c.argument('module_id', options_list=['--module-id', '-m'], help='Target Module.')
        c.argument('key_type', options_list=['--key-type', '-kt'], arg_type=get_enum_type(KeyType),
                   help='Shared access policy key type for auth.')
        c.argument('policy_name', options_list=['--policy-name', '-po'], help='Shared access policy to use for auth.')
        c.argument('duration', options_list=['--duration', '-du'], help='Valid token duration in seconds.')
        c.argument('etag', options_list=['--etag', '-e'], help='Entity tag value.')

        c.argument('top', type=int, help='Maximum number of elements to return.')
        c.argument('method_name', options_list=['--method-name', '-mn'], help='Target method for invocation.')
        c.argument('method_payload', options_list=['--method-payload', '-mp'],
                   help='Json payload to be passed to method. Must be file path or raw json.')
        c.argument('timeout', options_list=['--timeout', '-to'], type=int,
                   help='Maximum number of seconds to wait for method result.')

        c.argument('auth_method', options_list=['--auth-method', '-am'],
                   arg_type=get_enum_type(DeviceAuthType),
                   help='The authorization type an entity is to be created with.')

        c.argument('content', options_list=['--content', '-k'],
                   help='IoT Edge configuration content json. Provide file path or raw json.')

    with self.argument_context('iot hub') as c:
        c.argument('target_json', options_list=['--json', '-j'],
                   help='Json to replace existing twin with. Provide file path or raw json.')

    with self.argument_context('iot hub device-identity') as c:
        c.argument('edge_enabled', options_list=['--edge-enabled', '-ee'], arg_type=get_three_state_flag(),
                   help='Flag indicating edge enablement.')
        c.argument('status', options_list=['--status', '-sta'], arg_type=get_enum_type(DeviceStatusType),
                   help='Set device status upon creation.')
        c.argument('status_reason', options_list=['--status-reason', '-star'],
                   help='Description for device status.')
        c.argument('primary_thumbprint', arg_group='X.509', options_list=['--primary-thumbprint', '-ptp'],
                   help='Explicit self-signed certificate thumbprint to use for primary key.')
        c.argument('secondary_thumbprint', arg_group='X.509', options_list=['--secondary-thumbprint', '-stp'],
                   help='Explicit self-signed certificate thumbprint to use for secondary key.')
        c.argument('valid_days', arg_group='X.509', options_list=['--valid-days', '-vd'], type=int,
                   help='Generate self-signed cert and use its thumbprint. Valid for specified number of days. Default: 365.')
        c.argument('output_dir', arg_group='X.509', options_list=['--output-dir', '-od'],
                   help='Generate self-signed cert and use its thumbprint. Output to specified target directory')

    with self.argument_context('iot hub device-identity export') as c:
        c.argument('blob_container_uri',
                   options_list=['--blob-container-uri', '-bcu'],
                   help='Blob Shared Access Signature URI with write access to a blob container.'
                        'This is used to output the status of the job and the results.')
        c.argument('include_keys',
                   options_list=['--include-keys', '-ik'],
                   arg_type=get_three_state_flag(),
                   help='If set, keys are exported normally. Otherwise, keys are set to null in '
                        'export output.')

    with self.argument_context('iot hub device-identity import') as c:
        c.argument('input_blob_container_uri',
                   options_list=['--input-blob-container-uri', '-ibcu'],
                   help='Blob Shared Access Signature URI with read access to a blob container.'
                        'This blob contains the operations to be performed on the identity '
                        'registry ')
        c.argument('output_blob_container_uri',
                   options_list=['--output-blob-container-uri', '-obcu'],
                   help='Blob Shared Access Signature URI with write access to a blob container.'
                        'This is used to output the status of the job and the results.')

    with self.argument_context('iot hub query') as c:
        c.argument('query_command', options_list=['--query-command', '-q'], help='User query to be executed.')

    with self.argument_context('iot device') as c:
        c.argument('data', options_list=['--data', '-da'], help='Message body.')
        c.argument('properties', options_list=['--properties', '-props'],
                   help='Message property bag in key-value pairs with the following format: a=b;c=d')
        c.argument('msg_count', options_list=['--msg-count', '-mc'], type=int,
                   help='# of MQTT messages to send to IoT Hub.')
        c.argument('receive_count', options_list=['--receive-count', '-rc'], type=int,
                   help='Number of c2d messages to receive and process. Use -1 for infinity.')
        c.argument('receive_settle', options_list=['--receive-settle', '-rs'],
                   arg_type=get_enum_type(SettleType),
                   help='Indicates how to settle received messages.')

    with self.argument_context('iot device upload-file') as c:
        c.argument('file_path', options_list=['--file-path', '-fp'], help='Path to file for upload.')
        c.argument('content_type', options_list=['--content-type', '-ct'], help='MIME Type of file.')

    with self.argument_context('iot edge') as c:
        c.argument('config_id', options_list=['--config-id', '-c'], help='Target Configuration.')
        c.argument('target_condition', options_list=['--target-condition', '-tc'],
                   help='Target condition in which this Edge configuration applies to.')
        c.argument('priority', options_list=['--priority', '-pri'],
                   help='Weight of configuration in case of competing rules (highest wins).')
        c.argument('labels', options_list=['--labels', '-lab'],
                   help="""Map of labels to be applied to target configuration.
                           Use the following format:'{\"key0\":\"value0\", \"key1\":\"value1\"}'""")
