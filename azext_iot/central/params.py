# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from knack.arguments import CLIArgumentType, CaseInsensitiveList
from azure.cli.core.commands.parameters import get_three_state_flag
from azext_iot.monitor.models.enum import Severity
from azext_iot.central.models.enum import ApiVersion
from azext_iot._params import event_msg_prop_type, event_timeout_type

severity_type = CLIArgumentType(
    options_list=["--minimum-severity"],
    choices=CaseInsensitiveList([sev.name for sev in Severity]),
    help="Minimum severity of issue required for reporting.",
)

role_type = CLIArgumentType(
    options_list=["--role", "-r"],
    help="The role that will be associated with this token."
    " You can specify one of the built-in roles, or specify the role ID of a custom role."
    " See more at https://aka.ms/iotcentral-customrolesdocs",
)

style_type = CLIArgumentType(
    options_list=["--style"],
    choices=CaseInsensitiveList(["scroll", "json", "csv"]),
    help="Indicate output style"
    "scroll = deliver errors as they arrive, json = summarize results as json, csv = summarize results as csv",
)

api_version = CLIArgumentType(
    options_list=["--api-version", "--av"],
    choices=CaseInsensitiveList([version.value for version in ApiVersion]),
    default=ApiVersion.v1.value,
    help="The API version for the requested operation.",
)


def load_central_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot central") as context:
        context.argument(
            "app_id",
            options_list=["--app-id", "-n"],
            help="The App ID of the IoT Central app you want to manage."
            ' You can find the App ID in the "About" page for your application under the help menu.',
        )
        context.argument("api_version", arg_type=api_version)
        context.argument(
            "token",
            options_list=["--token"],
            help="If you'd prefer to submit your request without authenticating against the Azure CLI, you can specify a valid"
            " user token to authenticate your request. You must specify the type of key as part of the request."
            " Learn more at https://aka.ms/iotcentraldocsapi",
        )
        context.argument(
            "central_dns_suffix",
            options_list=["--central-dns-suffix", "--central-api-uri"],
            help="The IoT Central DNS suffix associated with your application. Default value is: azureiotcentral.com",
        )
        context.argument(
            "device_id",
            options_list=["--device-id", "-d"],
            help="The ID of the target device, "
            "You can find the Device Id by clicking on the Connect button on the Device Details page.",
        )

    with self.argument_context("iot central device-template") as context:
        context.argument(
            "device_template_id",
            options_list=["--device-template-id", "--dtid"],
            help="The ID of the target device template. Example: somedevicetemplate",
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The device template definition. Provide path to JSON file or raw stringified JSON."
            " [File Path Example: ./path/to/file.json] [Example of stringified JSON: {<Device Template JSON>}]."
            " The request body must contain CapabilityModel.",
        )

    with self.argument_context("iot central device-template create") as context:
        context.argument(
            "device_template_id",
            options_list=["--device-template-id", "--dtid"],
            help="Digital Twin Model Identifier of the device template."
            " Learn more at https://aka.ms/iotcentraldtmi.",
        )

    with self.argument_context("iot central api-token") as context:
        context.argument(
            "token_id",
            options_list=["--token-id", "--tkid"],
            help="The IoT Central ID associated with this token, [0-9a-zA-Z\\-] allowed, max length limit to 40."
            " Specify an ID that you'll then use when modifying or deleting this token later via the CLI or API.",
        )
        context.argument("role", arg_type=role_type)
        context.argument(
            "org_id",
            options_list=["--organization-id", "--orgid"],
            help="The ID of the organization for the token role assignment."
            " Only available for api-version == 1.1-preview",
        )

    with self.argument_context("iot central device compute-device-key") as context:
        context.argument(
            "primary_key",
            options_list=["--primary-key", "--pk"],
            help="The primary symmetric shared access key stored in base64 format. ",
        )

    with self.argument_context("iot central device") as context:
        context.argument(
            "template",
            options_list=["--template"],
            help="Central template id. Example: dtmi:ojpkindbz:modelDefinition:iild3tm_uo.",
        )
        context.argument(
            "simulated",
            options_list=["--simulated"],
            arg_type=get_three_state_flag(),
            help="Add this flag if you would like IoT Central to set this up as a simulated device. "
            "--template is required if this is true",
        )
        context.argument(
            "device_name",
            options_list=["--device-name"],
            help="Human readable device name. Example: Fridge",
        )
        context.argument(
            "interface_id",
            options_list=["--interface-id", "-i"],
            help="The name of the interface/component as specified in the device template.You can find it by navigating"
            " to Device Template and view the interface/component identity under the corresponding device capability.",
        )
        context.argument(
            "command_name",
            options_list=["--command-name", "--cn"],
            help="The command name as specified in the device template. Command name could be different from the Display"
            " Name of the command.",
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="Configuration for request. "
            "Provide path to JSON file or raw stringified JSON. "
            "[File Path Example: ./path/to/file.json] "
            "[Stringified JSON Example: {'a': 'b'}] ",
        )

    with self.argument_context("iot central device create") as context:
        context.argument(
            "device_id",
            options_list=["--device-id", "-d"],
            help="Unique identifier for the device."
            " A case-sensitive string (up to 128 characters long) of ASCII 7-bit alphanumeric characters plus"
            " certain special characters: - . + % _ # * ? ! ( ) , : = @ $ '",
        )
        context.argument(
            "organizations",
            options_list=["--organizations", "--org"],
            help="Assign the device to the specified organizations."
            " Comma separated list of organization ids."
            " Minimum supported version: 1.1-preview.",
        )
    with self.argument_context("iot central device manual-failover") as context:
        context.argument(
            "ttl_minutes",
            type=int,
            options_list=["--ttl-minutes", "--ttl"],
            help="A positive integer. TTL in minutes to move device back to the original hub."
            "Has default value in backend. See documentation on what the latest backend default time to live value"
            "by visiting https://github.com/iot-for-all/iot-central-high-availability-clients#readme",
        )

    with self.argument_context("iot central device-group") as context:
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList(
                [ApiVersion.preview.value, ApiVersion.v2.value]
            ),
            default=ApiVersion.v2.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central user") as context:
        context.argument(
            "tenant_id",
            options_list=["--tenant-id", "--tnid"],
            help="Tenant ID for service principal to be added to the app. Object ID must also be specified. ",
        )
        context.argument(
            "object_id",
            options_list=["--object-id", "--oid"],
            help="Object ID for service principal to be added to the app. Tenant ID must also be specified. ",
        )
        context.argument(
            "email",
            options_list=["--email"],
            help="Email address of user to be added to the app. ",
        )
        context.argument(
            "assignee",
            options_list=["--user-id", "--assignee"],
            help="ID associated with the user. ",
        )
        context.argument("role", arg_type=role_type)

    with self.argument_context("iot central diagnostics") as context:
        context.argument("timeout", arg_type=event_timeout_type)
        context.argument("properties", arg_type=event_msg_prop_type)
        context.argument("minimum_severity", arg_type=severity_type)
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
        context.argument(
            "module_id",
            options_list=["--module-id", "-m"],
            help="The IoT Edge Module ID if the device type is IoT Edge.",
        )

    with self.argument_context("iot central role") as context:
        context.argument(
            "role_id",
            options_list=["--role-id", "-r"],
            help="Unique identifier for the role",
        )

    with self.argument_context("iot central file-upload-configuration") as context:
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList([ApiVersion.v2.value]),
            default=ApiVersion.v2.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context(
        "iot central file-upload-configuration create"
    ) as context:
        context.argument(
            "connection_string",
            options_list=["--connection-string", "-s"],
            help="The connection string used to configure the storage account",
        )
        context.argument(
            "container",
            options_list=["--container", "-c"],
            help="The name of the container inside the storage account",
        )
        context.argument(
            "account",
            options_list=["--account", "-a"],
            help="The storage account name where to upload the file to",
        )
        context.argument(
            "sasTtl",
            options_list=["--sas-ttl"],
            help="The amount of time the device’s request to upload a file is valid before it expires."
            " ISO 8601 duration standard. Default 1h.",
        )

    with self.argument_context("iot central organization") as context:
        context.argument(
            "org_id",
            options_list=["--org-id"],
            help="Unique identifier for the organization.",
        )

    with self.argument_context("iot central organization create") as context:
        context.argument(
            "parent_org",
            options_list=["--parent-id"],
            help="The ID of the parent of the organization.",
        )
    with self.argument_context("iot central organization create") as context:
        context.argument(
            "org_name",
            options_list=["--org-name"],
            help="Display name of the organization.",
        )

    with self.argument_context("iot central job") as context:
        context.argument(
            "job_id",
            options_list=["--job-id", "-j"],
            help="Unique identifier for the job.",
        )

    with self.argument_context("iot central job rerun") as context:
        context.argument(
            "rerun_id",
            options_list=["--rerun-id"],
            help="Unique identifier for the rerun.",
        )

    with self.argument_context("iot central job create") as context:
        context.argument(
            "job_name",
            options_list=["--job-name"],
            help="Display name of the job.",
        )
        context.argument(
            "group_id",
            options_list=["--group-id", "-g"],
            help="The ID of the device group on which to execute the job",
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The job data definition. Provide path to JSON file or raw stringified JSON."
            " [File Path Example:./path/to/file.json]"
            " [Example of stringified JSON:[{<Job Data JSON>}]. The request body must contain array of JobData.",
        )
        context.argument(
            "batch_percentage",
            options_list=["--batch-percentage"],
            default=False,
            help="Specify if batching is done on a number of devices or a percentage of the total. Default: False",
        )
        context.argument(
            "batch",
            type=int,
            options_list=["--batch"],
            help="The number or percentage of devices on which batching is done.",
        )
        context.argument(
            "threshold",
            type=int,
            options_list=["--threshold"],
            help="The number or percentage of devices on which the cancellation threshold is applied.",
        )
        context.argument(
            "threshold_percentage",
            options_list=["--threshold-percentage"],
            default=False,
            help="Specify if cancellation threshold applies for a number of devices or a percentage of the total.",
        )
        context.argument(
            "threshold_batch",
            options_list=["--threshold-batch"],
            default=False,
            help="Whether the cancellation threshold applies per-batch or to the overall job.",
        )
        context.argument(
            "description",
            type=str,
            options_list=["--description", "--desc"],
            help="Detailed description of the job.",
        )
