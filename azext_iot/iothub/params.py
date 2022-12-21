# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.common import CertificateAuthorityVersions
from azure.cli.core.commands.parameters import get_enum_type, get_three_state_flag
from azext_iot.common.shared import SettleType, ProtocolType, AckType
from azext_iot.assets.user_messages import info_param_properties_device
from azext_iot._params import hub_auth_type_dataplane_param_type
from azext_iot.iothub.common import EncodingFormat, EndpointType, RouteSourceType
from azext_iot.iothub._validators import validate_device_model_id


def load_iothub_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot hub digital-twin") as context:
        context.argument(
            "command_name",
            options_list=["--command-name", "--cn"],
            help="Digital twin command name.",
        )
        context.argument(
            "component_path",
            options_list=["--component-path"],
            help="Digital twin component path. For example: thermostat1.",
        )
        context.argument(
            "json_patch",
            options_list=["--json-patch", "--patch"],
            help="An update specification described by JSON-patch. "
            "Operations are limited to add, replace and remove. Provide file path or inline JSON.",
        )
        context.argument(
            "payload",
            options_list=["--payload"],
            help="JSON payload input for command. Provide file path or inline JSON.",
        )
        context.argument(
            "connect_timeout",
            type=int,
            options_list=["--connect-timeout", "--cto"],
            help="Maximum interval of time, in seconds, that IoT Hub will attempt to connect to the device.",
            arg_group="Timeout"
        )
        context.argument(
            "response_timeout",
            type=int,
            options_list=["--response-timeout", "--rto"],
            help="Maximum interval of time, in seconds, that the digital twin command will wait for the result.",
            arg_group="Timeout"
        )

    with self.argument_context("iot device") as context:
        context.argument(
            "auth_type_dataplane",
            options_list=["--auth-type"],
            arg_type=hub_auth_type_dataplane_param_type,
        )
        context.argument("data", options_list=["--data", "--da"], help="Message body.")
        context.argument(
            "properties",
            options_list=["--properties", "--props", "-p"],
            help=info_param_properties_device(),
        )
        context.argument(
            "msg_count",
            options_list=["--msg-count", "--mc"],
            type=int,
            help="Number of device messages to send to IoT Hub.",
        )
        context.argument(
            "msg_interval",
            options_list=["--msg-interval", "--mi"],
            type=int,
            help="Delay in seconds between device-to-cloud messages.",
        )
        context.argument(
            "receive_settle",
            options_list=["--receive-settle", "--rs"],
            arg_type=get_enum_type(SettleType),
            help="Indicates how to settle received cloud-to-device messages. "
            "Supported with HTTP only.",
        )
        context.argument(
            "protocol_type",
            options_list=["--protocol", "--proto"],
            arg_type=get_enum_type(ProtocolType),
            help="Indicates device-to-cloud message protocol",
        )
        context.argument(
            "device_symmetric_key",
            options_list=["--symmetric-key", "--key"],
            arg_group="Device Authentication",
            help="Symmetric key to use for the device. If the symmetric key and other device "
            "authentication arguments are provided, symmetric key takes priority.",
        )
        context.argument(
            "certificate_file",
            options_list=["--certificate-file-path", "--cp"],
            arg_group="Device Authentication",
            help="Path to certificate file.",
        )
        context.argument(
            "key_file",
            options_list=["--key-file-path", "--kp"],
            arg_group="Device Authentication",
            help="Path to key file.",
        )
        context.argument(
            "passphrase",
            options_list=["--passphrase", "--pass"],
            arg_group="Device Authentication",
            help="Passphrase for key file.",
        )
        context.argument(
            "model_id",
            options_list=["--model-id", "--dtmi"],
            help="The Digital Twin Model Id the device will report when connecting to the hub. See "
            "https://docs.microsoft.com/en-us/azure/iot-develop/overview-iot-plug-and-play for more details.",
            arg_group="Digital Twin",
            validator=validate_device_model_id,
        )

    with self.argument_context("iot device simulate") as context:
        context.argument(
            "properties",
            options_list=["--properties", "--props", "-p"],
            help=info_param_properties_device(include_http=True),
        )
        context.argument(
            "method_response_code",
            type=int,
            options_list=["--method-response-code", "--mrc"],
            help="Status code to be returned when direct method is executed on device. Optional param, only supported for mqtt.",
        )
        context.argument(
            "method_response_payload",
            options_list=["--method-response-payload", "--mrp"],
            help="Payload to be returned when direct method is executed on device. Provide file path or raw json. "
            "Optional param, only supported for mqtt.",
        )
        context.argument(
            "init_reported_properties",
            options_list=["--init-reported-properties", "--irp"],
            help="Initial state of twin reported properties for the target device when the simulator is run. "
            "Optional param, only supported for mqtt.",
        )

    with self.argument_context("iot device c2d-message") as context:
        context.argument(
            "correlation_id",
            options_list=["--correlation-id", "--cid"],
            help="The correlation Id associated with the C2D message.",
        )
        context.argument(
            "properties",
            options_list=["--properties", "--props", "-p"],
            help=info_param_properties_device(include_mqtt=False),
        )
        context.argument(
            "expiry_time_utc",
            options_list=["--expiry-time-utc", "--expiry"],
            type=int,
            help="Units are milliseconds since unix epoch. "
            "If no time is indicated the default IoT Hub C2D message TTL is used.",
        )
        context.argument(
            "message_id",
            options_list=["--message-id", "--mid"],
            help="The C2D message Id. If no message Id is provided a UUID will be generated.",
        )
        context.argument(
            "user_id",
            options_list=["--user-id", "--uid"],
            help="The C2D message, user Id property.",
        )
        context.argument(
            "lock_timeout",
            options_list=["--lock-timeout", "--lt"],
            type=int,
            help="Specifies the amount of time a message will be invisible to other receive calls.",
        )
        context.argument(
            "content_type",
            options_list=["--content-type", "--ct"],
            help="The content type for the C2D message body.",
        )
        context.argument(
            "content_encoding",
            options_list=["--content-encoding", "--ce"],
            help="The encoding for the C2D message body.",
        )

    with self.argument_context("iot device c2d-message send") as context:
        context.argument(
            "ack",
            options_list=["--ack"],
            arg_type=get_enum_type(AckType),
            help="Request the delivery of per-message feedback regarding the final state of that message. "
            "The description of ack values is as follows. "
            "Positive: If the c2d message reaches the Completed state, IoT Hub generates a feedback message. "
            "Negative: If the c2d message reaches the Dead lettered state, IoT Hub generates a feedback message. "
            "Full: IoT Hub generates a feedback message in either case. "
            "By default, no ack is requested.",
        )
        context.argument(
            "wait_on_feedback",
            options_list=["--wait", "-w"],
            arg_type=get_three_state_flag(),
            help="If set the c2d send operation will block until device feedback has been received.",
        )

    with self.argument_context("iot device c2d-message receive") as context:
        context.argument(
            "abandon",
            arg_group="Message Ack",
            options_list=["--abandon"],
            arg_type=get_three_state_flag(),
            help="Abandon the cloud-to-device message after receipt.",
        )
        context.argument(
            "complete",
            arg_group="Message Ack",
            options_list=["--complete"],
            arg_type=get_three_state_flag(),
            help="Complete the cloud-to-device message after receipt.",
        )
        context.argument(
            "reject",
            arg_group="Message Ack",
            options_list=["--reject"],
            arg_type=get_three_state_flag(),
            help="Reject the cloud-to-device message after receipt.",
        )

    with self.argument_context("iot device upload-file") as context:
        context.argument(
            "file_path",
            options_list=["--file-path", "--fp"],
            help="Path to file for upload.",
        )
        context.argument(
            "content_type",
            options_list=["--content-type", "--ct"],
            help="MIME Type of file.",
        )

    with self.argument_context("iot hub message-endpoint") as context:
        context.argument(
            "hub_name",
            options_list=["--hub-name", "-n"],
            help="IoT Hub name.",
            arg_group=None
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--endpoint", "--en"],
            help="Name of the routing endpoint."
        )
        context.argument(
            "endpoint_type",
            arg_type=get_enum_type(EndpointType),
            options_list=["--endpoint-type", "--type", "-t"],
            help="Type of the Routing Endpoint."
        )

    with self.argument_context("iot hub message-endpoint create") as context:
        context.argument(
            'identity',
            help='Use a system-assigned or user-assigned managed identity for endpoint '
                 'authentication. Use "[system]" to refer to the system-assigned identity or a resource ID '
                 'to refer to a user-assigned identity.',
        )
        context.argument(
            "endpoint_resource_group",
            options_list=["--endpoint-resource-group", "--erg", "-r"],
            help="Resource group of the Endpoint resoure. If not provided, the IoT Hub's resource group will be used."
        )
        context.argument(
            "endpoint_subscription_id",
            options_list=["--endpoint-subscription-id", "-s"],
            help="Subscription Id of the Endpoint resource. If not provided, the IoT Hub's subscription will be used."
        )
        context.argument(
            "connection_string",
            options_list=["--connection-string", "-c"],
            help="Connection string of the Routing Endpoint."
        )
        context.argument(
            "entity_path",
            options_list=["--entity-path"],
            help="The entity path of the endpoint resource."
        )
        context.argument(
            "endpoint_policy_name",
            options_list=["--endpoint-policy-name", "--policy"],
            help="The policy name for connection string retrieval."
        )
        context.argument(
            "endpoint_uri",
            options_list=["--endpoint-uri"],
            help="The uri of the endpoint resource."
        )
        context.argument(
            "policy_name",
            options_list=["--policy-name"],
            help="The policy name for the endpoint resource connection string."
        )
        context.argument(
            "endpoint_account_name",
            options_list=["--endpoint-namespace-name", "--namespace"],
            help="The namespace name for the endpoint resource."
        )

    with self.argument_context("iot hub message-endpoint create storage-container") as context:
        context.argument(
            "container_name",
            options_list=["--container-name", "--container"],
            help="Name of the storage container."
        )
        context.argument(
            "encoding",
            options_list=["--encoding"],
            arg_type=get_enum_type(EncodingFormat),
            help="Encoding format for the container."
        )
        context.argument(
            'batch_frequency',
            options_list=['--batch-frequency', '-b'],
            type=int,
            help='Request batch frequency in seconds. The maximum amount of time that can elapse before data is'
                 ' written to a blob, between 60 and 720 seconds.'
        )
        context.argument(
            'chunk_size_window',
            options_list=['--chunk-size', '-w'],
            type=int,
            help='Request chunk size in megabytes(MB). The maximum size of blobs, between 10 and 500 MB.'
        )
        context.argument(
            'file_name_format',
            options_list=['--file-name-format', '--ff'],
            help='File name format for the blob. The file name format must contain {iothub},'
                 ' {partition}, {YYYY}, {MM}, {DD}, {HH} and {mm} fields. All parameters are'
                 ' mandatory but can be reordered with or without delimiters.'
        )
        context.argument(
            "endpoint_account_name",
            options_list=["--endpoint-account"],
            help="The account name for the endpoint resource."
        )

    with self.argument_context("iot hub message-endpoint create cosmosdb-container") as context:
        context.argument(
            'database_name',
            options_list=['--database-name', '--db'],
            help='The name of the cosmos DB database in the cosmos DB account. Required for Cosmos DB SQL Container Endpoints.',
        )
        context.argument(
            'container_name',
            options_list=['--container-name', '--container'],
            help='The name of the Cosmos DB SQL Container in the cosmos DB Database. Required for Cosmos DB SQL Container '
                 'Endpoints.',
        )
        context.argument(
            'primary_key',
            options_list=['--primary-key', '--pk'],
            help='The primary key of the cosmos DB account.',
            arg_group=None
        )
        context.argument(
            'secondary_key',
            options_list=['--secondary-key', '--sk'],
            help='The secondary key of the cosmos DB account.',
            arg_group=None
        )
        context.argument(
            'partition_key_name',
            options_list=['--partition-key-name', '--pkn'],
            help='The name of the partition key associated with this Cosmos DB SQL Container if one exists.',
        )
        context.argument(
            'partition_key_template',
            options_list=['--partition-key-template', '--pkt'],
            help='The template for generating a synthetic partition key value for use with this Cosmos DB SQL Container. '
                 'The template must include at least one of the following placeholders: {iothub}, {deviceid}, {DD}, {MM}, and '
                 '{YYYY}. Any one placeholder may be specified at most once, but order and non-placeholder components are '
                 'arbitrary. If partition key name is provided, partition key template defaults to {deviceid}-{YYYY}-{MM}',
        )
        context.argument(
            "endpoint_account_name",
            options_list=["--endpoint-account"],
            help="The account name for the endpoint resource."
        )

    with self.argument_context("iot hub message-route") as context:
        context.argument(
            "hub_name",
            options_list=["--hub-name", "-n"],
            help="IoT Hub name.",
            arg_group=None
        )
        context.argument(
            "route_name",
            options_list=["--route-name", "--route", "--rn"],
            help="Name of the route."
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--endpoint", "--en"],
            help="Name of the routing endpoint. For the built-in endpoint, use endpoint name 'events'."
        )
        context.argument(
            "condition",
            options_list=["--condition", "-c"],
            help="Condition that is evaluated to apply the routing rule."
        )
        context.argument(
            "enabled",
            options_list=["--enabled", "-e"],
            arg_type=get_three_state_flag(),
            help="A boolean indicating whether to enable route to the IoT Hub."
        )
        context.argument(
            "source_type",
            arg_type=get_enum_type(RouteSourceType),
            options_list=["--source-type", "--type", "-t"],
            help="Source of the route."
        )

    with self.argument_context("iot hub message-route test") as context:
        context.argument(
            "body",
            options_list=["--body", "-b"],
            help="Body of the route message.",
        )
        context.argument(
            "app_properties",
            options_list=["--app-properties", "--ap"],
            help="App properties of the route message.",
        )
        context.argument(
            "system_properties",
            options_list=["--system-properties", "--sp"],
            help="System properties of the route message.",
        )

    with self.argument_context("iot hub certificate root-authority set") as context:
        context.argument(
            "ca_version",
            options_list=["--certificate-authority", "--cav"],
            help="Certificate Root Authority version. The v1 represents Baltimore CA and v2 represents Digicert CA.",
            arg_type=get_enum_type(CertificateAuthorityVersions),
        )
