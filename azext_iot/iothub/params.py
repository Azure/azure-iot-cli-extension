# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.state import HubAspects
from azure.cli.core.commands.parameters import get_enum_type, get_three_state_flag
from azext_iot.common.shared import SettleType, ProtocolType, AckType
from azext_iot.assets.user_messages import info_param_properties_device
from azext_iot._params import hub_auth_type_dataplane_param_type
from azext_iot.iothub._validators import validate_device_model_id
from azext_iot._validators import mode2_iot_login_handler


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

    with self.argument_context("iot hub state") as context:
        context.argument(
            "state_file",
            options_list=["--state-file", "-f"],
            help="The path to the file where the state information will be stored."
        )
        context.argument(
            "replace",
            options_list=["--replace", "-r"],
            help="If this flag is set, then the command will delete the current devices, configurations, and certificates "
                 "of the destination hub."
        )
        context.argument(
            "hub_aspects",
            options_list=["--aspects"],
            nargs="+",
            arg_type=get_enum_type(HubAspects),
            help="Hub Aspects (space separated)."
        )

    with self.argument_context("iot hub state import") as context:
        context.argument(
            "replace",
            options_list=["--replace", "-r"],
            help="If this flag is set, then the command will overwrite the contents of the output file."
        )

    with self.argument_context("iot hub state migrate") as context:
        context.argument(
            "hub_name",
            options_list=["--destination-hub", "--dh"],
            help="Name of IoT Hub to which the origin hub will be copied."
        )
        context.argument(
            "resource_group_name",
            options_list=["--destination-resource-group", "--dg"],
            help="Name of resource group of the IoT Hub to which the origin hub will be copied."
        )
        context.argument(
            "login",
            options_list=["--destination-hub-login", "--dl"],
            validator=mode2_iot_login_handler,
            help="This command supports an entity connection string with rights to perform action on the destination hub. "
            'Use to avoid session login via "az login" for this IoT Hub instance. '
            "If both an entity connection string and name are provided the connection string takes priority. "
            "Required if --destination-hub is not provided.",
            arg_group="IoT Hub Identifier"
        )
        context.argument(
            "orig_hub",
            options_list=["--origin-hub", "--oh"],
            help="Name of IoT Hub which will be copied.",
            arg_group="IoT Hub Identifier"
        )
        context.argument(
            "orig_resource_group_name",
            options_list=["--origin-resource-group", "--og"],
            help="Name of resource group of the IoT Hub which will be copied."
        )
        context.argument(
            "orig_hub_login",
            options_list=["--origin-hub-login", "--ol"],
            validator=mode2_iot_login_handler,
            help="This command supports an entity connection string with rights to perform action on the origin hub. "
            'Use to avoid session login via "az login" for this IoT Hub instance. '
            "If both an entity connection string and name are provided the connection string takes priority. "
            "Required if --origin-hub is not provided.",
            arg_group="IoT Hub Identifier"
        )
