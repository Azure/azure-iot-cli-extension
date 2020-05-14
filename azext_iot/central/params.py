# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Unpublished works.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from knack.arguments import CLIArgumentType, CaseInsensitiveList

from azure.cli.core.commands.parameters import get_three_state_flag, get_enum_type
from azext_iot.central.models.enum import DeviceStatus
from azext_iot.monitor.models.enum import Severity
from azext_iot._params import event_msg_prop_type, event_timeout_type

severity_type = CLIArgumentType(
    options_list=["--minimum-severity"],
    choices=CaseInsensitiveList([sev.name for sev in Severity]),
    help="Minimum severity of issue required for reporting.",
)

style_type = CLIArgumentType(
    options_list=["--style"],
    choices=CaseInsensitiveList(["scroll", "json", "csv"]),
    help="Indicate output style"
    "scroll = deliver errors as they arrive, json = summarize results as json, csv = summarize results as json",
)


def load_central_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot central app") as context:
        context.argument("app_id", options_list=["--app-id"], help="Target App.")
        context.argument("minimum_severity", arg_type=severity_type)
        context.argument(
            "instance_of",
            options_list=["--instance-of"],
            help="Central template id. Example: urn:ojpkindbz:modelDefinition:iild3tm_uo",
        )
        context.argument(
            "device_name",
            options_list=["--device-name"],
            help="Human readable device name. Example: Fridge",
        )
        context.argument(
            "simulated",
            options_list=["--simulated"],
            arg_type=get_three_state_flag(),
            help="Add this flag if you would like IoT Central to set this up as a simulated device. "
            "--instance-of is required if this is true",
        )
        context.argument(
            "device_template_id",
            options_list=["--device-template-id"],
            help="Device template id. Example: somedevicetemplate",
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="Configuration for request. "
            "Provide path to JSON file or raw stringified JSON. "
            "[File Path Example: ./path/to/file.json] "
            "[Stringified JSON Example: {'a': 'b'}] ",
        )
        context.argument(
            "token",
            options_list=["--token"],
            help="Authorization token for request. "
            "More info available here: https://docs.microsoft.com/en-us/learn/modules/manage-iot-central-apps-with-rest-api/ "
            "MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...'). "
            "Example: 'Bearer someBearerTokenHere'",
        )
        context.argument(
            "central_dns_suffix",
            options_list=["--central-dns-suffix", "--central-api-uri"],
            help="Central dns suffix. "
            "This enables running cli commands against non public/prod environments",
        )
        context.argument(
            "device_status",
            options_list=["--device-status", "--ds"],
            arg_type=get_enum_type(DeviceStatus),
            help="Indicates filter option for device status",
        )
        context.argument(
            "summarize_registration",
            options_list=["--registrationsummary", "--rs"],
            arg_type=get_three_state_flag(),
            help="Add this flag to get a summary of registration information",
        )
        context.argument(
            "max_devices",
            options_list=["--maxdevices", "--md"],
            help="This value sets the maximum numner of devices to be displayed in a single instance",
        )

    with self.argument_context("iot central app monitor-events") as context:
        context.argument("timeout", arg_type=event_timeout_type)
        context.argument("properties", arg_type=event_msg_prop_type)

    with self.argument_context("iot central app validate-messages") as context:
        context.argument("timeout", arg_type=event_timeout_type)
        context.argument("properties", arg_type=event_msg_prop_type)
        context.argument("style", arg_type=style_type)
        context.argument(
            "duration",
            options_list=["--duration", "--dr"],
            type=int,
            help="Maximum duration to receive messages from target device before terminating connection."
            "Use 0 for infinity.",
        )
        context.argument(
            "max_messages",
            options_list=["--max-messages", "--mm"],
            type=int,
            help="Maximum number of messages to recieve from target device before terminating connection."
            "Use 0 for infinity.",
        )

    # TODO: Delete this by end of July 2020
    load_deprecated_iotcentral_params(self, _)


# TODO: Delete this by end of July 2020
def load_deprecated_iotcentral_params(self, _):
    with self.argument_context("iotcentral") as context:
        context.argument("app_id", options_list=["--app-id"], help="Target App.")
        context.argument("properties", arg_type=event_msg_prop_type)
        context.argument("timeout", arg_type=event_timeout_type)
        context.argument(
            "device_id", options_list=["--device-id", "-d"], help="Target Device."
        )
        context.argument(
            "timeout",
            options_list=["--timeout", "--to", "-t"],
            type=int,
            help="Maximum seconds to maintain connection. Use 0 for infinity. ",
        )
        context.argument(
            "consumer_group",
            options_list=["--consumer-group", "--cg", "-c"],
            help="Specify the consumer group to use when connecting to event hub endpoint.",
        )
        context.argument(
            "enqueued_time",
            options_list=["--enqueued-time", "--et", "-e"],
            type=int,
            help="Indicates the time that should be used as a starting point to read messages from the partitions. "
            "Units are milliseconds since unix epoch. "
            'If no time is indicated "now" is used.',
        )
        context.argument(
            "content_type",
            options_list=["--content-type", "--ct"],
            help="Specify the Content-Type of the message payload to automatically format the output to that type.",
        )
        context.argument(
            "repair",
            options_list=["--repair", "-r"],
            arg_type=get_three_state_flag(),
            help="Reinstall uamqp dependency compatible with extension version. Default: false",
        )
        context.argument(
            "yes",
            options_list=["--yes", "-y"],
            arg_type=get_three_state_flag(),
            help="Skip user prompts. Indicates acceptance of dependency installation (if required). "
            "Used primarily for automation scenarios. Default: false",
        )
        context.argument(
            "central_dns_suffix",
            options_list=["--central-dns-suffix", "--central-api-uri"],
            help="Central dns suffix. "
            "This enables running cli commands against non public/prod environments",
        )

    with self.argument_context("iot central device-twin") as context:
        context.argument("app_id", options_list=["--app-id"], help="Target App.")
        context.argument(
            "central_dns_suffix",
            options_list=["--central-dns-suffix", "--central-api-uri"],
            help="Central dns suffix. "
            "This enables running cli commands against non public/prod environments",
        )
