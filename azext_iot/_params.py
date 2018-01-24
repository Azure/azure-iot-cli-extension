# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from knack.arguments import CLIArgumentType
from azure.cli.core.commands.parameters import (
    resource_group_name_type,
    get_enum_type,
    get_resource_name_completion_list,
    get_three_state_flag
)
from azext_iot.common.shared import (
    EntityStatusType,
    SettleType,
    DeviceAuthType,
    KeyType,
    AttestationType
)

hub_name_type = CLIArgumentType(
    completer=get_resource_name_completion_list('Microsoft.Devices/IotHubs'),
    help='IoT Hub name.')

# pylint: disable=too-many-statements
def load_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context('iot') as context:
        context.argument('resource_group_name', arg_type=resource_group_name_type)
        context.argument('hub_name', options_list=['--hub-name', '-n'], arg_type=hub_name_type)
        context.argument('device_id', options_list=['--device-id', '-d'], help='Target Device.')
        context.argument('module_id', options_list=['--module-id', '-m'], help='Target Module.')
        context.argument('key_type', options_list=['--key-type', '-kt'],
                         arg_type=get_enum_type(KeyType),
                         help='Shared access policy key type for auth.')
        context.argument('policy_name', options_list=['--policy-name', '-po'],
                         help='Shared access policy to use for auth.')
        context.argument('duration', options_list=['--duration', '-du'],
                         help='Valid token duration in seconds.')
        context.argument('etag', options_list=['--etag', '-e'], help='Entity tag value.')
        context.argument('top', type=int, help='Maximum number of elements to return.')
        context.argument('method_name', options_list=['--method-name', '-mn'],
                         help='Target method for invocation.')
        context.argument('method_payload', options_list=['--method-payload', '-mp'],
                         help='Json payload to be passed to method. Must be file path or raw json.')
        context.argument('timeout', options_list=['--timeout', '-to'], type=int,
                         help='Maximum number of seconds to wait for method result.')
        context.argument('auth_method', options_list=['--auth-method', '-am'],
                         arg_type=get_enum_type(DeviceAuthType),
                         help='The authorization type an entity is to be created with.')
        context.argument('content', options_list=['--content', '-k'],
                         help='IoT Edge configuration content json. Provide file path or raw json.')

    with self.argument_context('iot hub') as context:
        context.argument('target_json', options_list=['--json', '-j'],
                         help='Json to replace existing twin with. Provide file path or raw json.')

    with self.argument_context('iot hub device-identity') as context:
        context.argument('edge_enabled', options_list=['--edge-enabled', '-ee'],
                         arg_type=get_three_state_flag(),
                         help='Flag indicating edge enablement.')
        context.argument('status', options_list=['--status', '-sta'],
                         arg_type=get_enum_type(EntityStatusType),
                         help='Set device status upon creation.')
        context.argument('status_reason', options_list=['--status-reason', '-star'],
                         help='Description for device status.')
        context.argument('primary_thumbprint', arg_group='X.509',
                         options_list=['--primary-thumbprint', '-ptp'],
                         help='Explicit self-signed certificate thumbprint to use for primary key.')
        context.argument('secondary_thumbprint', arg_group='X.509',
                         options_list=['--secondary-thumbprint', '-stp'],
                         help='Explicit self-signed certificate thumbprint to '
                         'use for secondary key.')
        context.argument('valid_days', arg_group='X.509', options_list=['--valid-days', '-vd'],
                         type=int,
                         help='Generate self-signed cert and use its thumbprint. Valid '
                         'for specified number of days. Default: 365.')
        context.argument('output_dir', arg_group='X.509', options_list=['--output-dir', '-od'],
                         help='Generate self-signed cert and use its thumbprint. '
                         'Output to specified target directory')

    with self.argument_context('iot hub device-identity export') as context:
        context.argument('blob_container_uri',
                         options_list=['--blob-container-uri', '-bcu'],
                         help='Blob Shared Access Signature URI with write access to '
                         'a blob container. This is used to output the status of the '
                         'job and the results.')
        context.argument('include_keys',
                         options_list=['--include-keys', '-ik'],
                         arg_type=get_three_state_flag(),
                         help='If set, keys are exported normally. Otherwise, keys are '
                         'set to null in export output.')

    with self.argument_context('iot hub device-identity import') as context:
        context.argument('input_blob_container_uri',
                         options_list=['--input-blob-container-uri', '-ibcu'],
                         help='Blob Shared Access Signature URI with read access to a blob '
                         'container. This blob contains the operations to be performed on '
                         'the identity registry ')
        context.argument('output_blob_container_uri',
                         options_list=['--output-blob-container-uri', '-obcu'],
                         help='Blob Shared Access Signature URI with write access '
                         'to a blob container. This is used to output the status of '
                         'the job and the results.')

    with self.argument_context('iot hub query') as context:
        context.argument('query_command', options_list=['--query-command', '-q'],
                         help='User query to be executed.')

    with self.argument_context('iot device') as context:
        context.argument('data', options_list=['--data', '-da'], help='Message body.')
        context.argument('properties', options_list=['--properties', '-props'],
                         help='Message property bag in key-value pairs with the '
                         'following format: a=b;c=d')
        context.argument('msg_count', options_list=['--msg-count', '-mc'], type=int,
                         help='# of MQTT messages to send to IoT Hub.')
        context.argument('receive_count', options_list=['--receive-count', '-rc'], type=int,
                         help='Number of c2d messages to receive and process. Use -1 for infinity.')
        context.argument('receive_settle', options_list=['--receive-settle', '-rs'],
                         arg_type=get_enum_type(SettleType),
                         help='Indicates how to settle received messages.')

    with self.argument_context('iot device upload-file') as context:
        context.argument('file_path', options_list=['--file-path', '-fp'],
                         help='Path to file for upload.')
        context.argument('content_type', options_list=['--content-type', '-ct'],
                         help='MIME Type of file.')

    with self.argument_context('iot edge') as context:
        context.argument('config_id', options_list=['--config-id', '-c'],
                         help='Target Configuration.')
        context.argument('target_condition', options_list=['--target-condition', '-tc'],
                         help='Target condition in which this Edge configuration applies to.')
        context.argument('priority', options_list=['--priority', '-pri'],
                         help='Weight of configuration in case of competing rules (highest wins).')
        context.argument('labels', options_list=['--labels', '-lab'],
                         help="""Map of labels to be applied to target configuration.
                                Use the following format:'{\"key0\":\"value0\", 
                                \"key1\":\"value1\"}'""")

    with self.argument_context('iot dps') as context:
        context.argument('dps_name', help='Name of the Azure IoT Hub device provisioning service')
        context.argument('initial_twin_properties',
                         options_list=['--initial-twin-properties', '-props'],
                         help='Initial twin properties')
        context.argument('initial_twin_tags', options_list=['--initial-twin-tags', '-tags'],
                         help='Initial twin tags')
        context.argument('iot_hub_host_name', help='Host name of target IoT Hub')
        context.argument('provisioning_status', options_list=['--provisioning-status', '-ps'],
                         arg_type=get_enum_type(EntityStatusType),
                         help='Enable or disable enrollment entry')

    with self.argument_context('iot dps enrollment') as context:
        context.argument('enrollment_id', help='ID of device enrollment record')
        context.argument('device_id', help='IoT Hub Device ID')

    with self.argument_context('iot dps enrollment create') as context:
        context.argument('attestation_type', options_list=['--attestation-type', '-at'],
                         arg_type=get_enum_type(AttestationType), help='Attestation Mechanism')
        context.argument('certificate_path', options_list=['--certificate-path', '-cp'],
                         help='The path to the file containing the certificate. '
                         'When choosing x509 as attestation type, certificate path is required.')
        context.argument('endorsement_key', options_list=['--endorsement-key', '-ek'],
                         help='TPM endorsement key for a TPM device. '
                         ' When choosing tpm as attestation type, endorsement key is required.')

    with self.argument_context('iot dps enrollment update') as context:
        context.argument('certificate_path', options_list=['--certificate-path', '-cp'],
                         help='The path to the file containing the certificate. '
                         'When updating enrollment with x509 attestation mechanism, '
                         'certificate path is required.')
        context.argument('endorsement_key', options_list=['--endorsement-key', '-ek'],
                         help='TPM endorsement key for a TPM device.')

    with self.argument_context('iot dps enrollment-group') as context:
        context.argument('enrollment_id', help='ID of enrollment group')
        context.argument('certificate_path', options_list=['--certificate-path', '-cp'],
                         help='The path to the file containing the certificate.')

    with self.argument_context('iot dps registration') as context:
        context.argument('registration_id', help='ID of device registration')

    with self.argument_context('iot dps registration list') as context:
        context.argument('enrollment_id', help='ID of enrollment group')
