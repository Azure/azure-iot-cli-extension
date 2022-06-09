# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from knack.arguments import CLIArgumentType, CaseInsensitiveList
from azext_iot.central.common import DestinationType, ExportSource
from azure.cli.core.commands.parameters import get_three_state_flag, get_enum_type
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
    help="The role that will be associated with this token or user."
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
            help="The IoT Central DNS suffix associated with your application.",
        )
        context.argument(
            "device_id",
            options_list=["--device-id", "-d"],
            help="The device ID of the target device."
            "You can find the device ID by, clicking on the Connect button on the Device Details page.",
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

    with self.argument_context("iot central device-template list") as context:
        context.argument(
            "compact",
            options_list=["--compact", "-c"],
            help="Show templates in compact mode. For each template will only display id, name and model types.",
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
            options_list=["--organization-id", "--org-id"],
            help="The ID of the organization for the token role assignment."
            " Only available for api-version == 1.1-preview",
        )

    with self.argument_context("iot central device compute-device-key") as context:
        context.argument(
            "primary_key",
            options_list=["--primary-key", "--pk"],
            help="The primary symmetric shared access key stored in base64 format. ",
        )

    with self.argument_context("iot central device list") as context:
        context.argument(
            "edge_only",
            options_list=["--edge-only", "-e"],
            help="Only list IoT Edge devices.",
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
            options_list=["--organizations", "--orgs"],
            help="Assign the device to the specified organizations."
            " Comma separated list of organization ids."
            " Minimum supported version: 1.1-preview.",
        )

    with self.argument_context("iot central device update") as context:
        context.argument(
            "enabled",
            options_list=["--enable"],
            arg_type=get_three_state_flag(),
            help="Add this flag if you would like IoT Central to enable or disable the device.",
        )
        context.argument(
            "organizations",
            options_list=["--organizations", "--orgs"],
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
                [ApiVersion.preview.value, ApiVersion.v1_1_preview.value]
            ),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central device-group show") as context:
        context.argument(
            "device_group_id",
            options_list=["--device-group-id", "-d"],
            help="Unique ID of the device group."
        )

    with self.argument_context("iot central device-group create") as context:
        context.argument(
            "device_group_id",
            options_list=["--device-group-id", "-d"],
            help="Unique ID of the device group."
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The device group definition. Provide path to JSON file or raw stringified JSON."
        )

    with self.argument_context("iot central device-group update") as context:
        context.argument(
            "device_group_id",
            options_list=["--device-group-id", "-d"],
            help="Unique ID of the device group."
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The device group definition. Provide path to JSON file or raw stringified JSON."
        )

    with self.argument_context("iot central device-group delete") as context:
        context.argument(
            "device_group_id",
            options_list=["--device-group-id", "-d"],
            help="Unique ID of the device group."
        )

    with self.argument_context("iot central user") as context:
        context.argument(
            "tenant_id",
            options_list=["--tenant-id", "--tnid"],
            help="Tenant ID for service principal to be added to the app. Object ID must also be specified."
            " If email is specified this gets ignored and the user will not be a service principal user"
            ' but a standard "email" user.',
        )
        context.argument(
            "object_id",
            options_list=["--object-id", "--oid"],
            help="Object ID for service principal to be added to the app. Tenant ID must also be specified."
            " If email is specified this gets ignored and the user will not be a service principal user"
            ' but a standard "email" user.',
        )
        context.argument(
            "email",
            options_list=["--email"],
            help="Email address of user to be added to the app."
            " If this is specified, service principal parameters (tenant_id and object_id) will be ignored.",
        )
        context.argument(
            "assignee",
            options_list=["--user-id", "--assignee"],
            help="ID associated with the user. ",
        )
        context.argument("role", arg_type=role_type)
        context.argument(
            "org_id",
            options_list=["--organization-id", "--org-id"],
            help="The ID of the organization for the user role assignment."
            " Only available for api-version == 1.1-preview",
        )

    with self.argument_context("iot central user update") as context:
        context.ignore("role")
        context.ignore("org_id")
        context.argument(
            "roles",
            options_list=["--roles"],
            help="Comma-separated list of roles that will be associated with this user."
            " You can specify one of the built-in roles, or specify the role ID of a custom role."
            " See more at https://aka.ms/iotcentral-customrolesdocs."
            " Organizations can be specified alongside roles when running with API version == 1.1-preview."
            ' E.g. "organization_id\\role".',
        )

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

    with self.argument_context("iot central file-upload-config") as context:
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList([ApiVersion.v1_1_preview.value]),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central file-upload-config create") as context:
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
            " ISO 8601 duration standard. Default: 1h.",
        )

    with self.argument_context("iot central file-upload-config update") as context:
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
            " ISO 8601 duration standard. Default: 1h.",
        )

    with self.argument_context("iot central organization") as context:
        context.argument(
            "org_id",
            options_list=["--org-id"],
            help="Unique identifier for the organization.",
        )
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList([ApiVersion.v1_1_preview.value]),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central organization create") as context:
        context.argument(
            "parent_org",
            options_list=["--parent-id"],
            help="The ID of the parent of the organization.",
        )
        context.argument(
            "org_name",
            options_list=["--org-name"],
            help="Display name of the organization.",
        )

    with self.argument_context("iot central organization update") as context:
        context.argument(
            "parent_org",
            options_list=["--parent-id"],
            help="The ID of the parent of the organization.",
        )
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
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList(
                [ApiVersion.v1_1_preview.value, ApiVersion.preview.value]
            ),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
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
            "batch_type",
            options_list=["--batch-type", "--bt"],
            default=False,
            help="Specify if batching is done on a number of devices or a percentage of the total.",
        )
        context.argument(
            "batch",
            type=int,
            options_list=["--batch", "-b"],
            help="The number or percentage of devices on which batching is done.",
        )
        context.argument(
            "threshold",
            type=int,
            options_list=["--cancellation-threshold", "--cth"],
            help="The number or percentage of devices on which the cancellation threshold is applied.",
        )
        context.argument(
            "threshold_type",
            options_list=["--cancellation-threshold-type", "--ctt"],
            choices=CaseInsensitiveList(["number", "percentage"]),
            default="number",
            help="Specify if cancellation threshold applies for a number of devices or a percentage of the total.",
        )
        context.argument(
            "threshold_batch",
            options_list=["--cancellation-threshold-batch", "--ctb"],
            default="number",
            help="Whether the cancellation threshold applies per-batch or to the overall job.",
        )
        context.argument(
            "description",
            type=str,
            options_list=["--description", "--desc"],
            help="Detailed description of the job.",
        )

    with self.argument_context("iot central query") as context:
        context.argument(
            "query_string",
            options_list=["--query-string", "--qs"],
            help="Query clause to retrieve telemetry or property data.",
        )
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList([ApiVersion.v1_1_preview.value]),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central export") as context:
        context.argument(
            "export_id",
            options_list=["--export-id", "--id"],
            help="Unique identifier for the export.",
        )
        context.argument(
            "api_version",
            options_list=["--api-version", "--av"],
            choices=CaseInsensitiveList([ApiVersion.v1_1_preview.value]),
            default=ApiVersion.v1_1_preview.value,
            help="The API version for the requested operation.",
        )

    with self.argument_context("iot central export create") as context:
        context.argument(
            "display_name",
            options_list=["--display-name", "--name"],
            help="The data export display name",
        )
        context.argument(
            "enabled",
            options_list=["--enabled", "-e"],
            arg_type=get_three_state_flag(),
            help="The enabled status for data export, True or False.",
        )
        context.argument(
            "filter",
            options_list=["--filter", "-f"],
            default=None,
            help="IoT Central Query Language based filter, more details from: aka.ms/iotcquery",
        )
        context.argument(
            "source",
            options_list=["--source", "-s"],
            help="The data export source.",
            arg_type=get_enum_type(ExportSource),
        )
        context.argument(
            "enrichments",
            options_list=["--enrichments", "--en"],
            help="The data export enrichment",
            default=None,
        )
        context.argument(
            "destinations",
            options_list=["--destinations", "--dests"],
            help="The list of destinations with transform.",
        )

    with self.argument_context("iot central export update") as context:
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The partial export definition. Provide path to JSON file or raw stringified JSON."
            " [File Path Example:./path/to/file.json]"
            " [Example of stringified JSON:{<Export Data JSON>}]. The request body must contain partial content of Export.",
        )

    with self.argument_context("iot central export destination") as context:
        context.argument(
            "destination_id",
            options_list=["--dest-id"],
            help="Unique identifier for the export destination.",
        )

    with self.argument_context("iot central export destination create") as context:
        context.argument(
            "display_name",
            options_list=["--display-name", "--name"],
            help="The destination display name.",
        )
        context.argument(
            "type",
            options_list=["--type", "-t"],
            help="The destination type.",
            arg_type=get_enum_type(DestinationType),
        )
        context.argument(
            "url",
            options_list=["--url"],
            help="The webhook url.",
        )
        context.argument(
            "cluster_url",
            options_list=["--cluster-url", "--cu"],
            help="The azure data explorer cluster url.",
        )
        context.argument(
            "database",
            options_list=["--database"],
            help="The azure data explorer database.",
        )
        context.argument(
            "table",
            options_list=["--table"],
            help="The azure data explorer table.",
        )
        context.argument(
            "header_customizations",
            options_list=["--header"],
            help="The webhook destination custimized header collection in json.",
        )
        context.argument(
            "authorization",
            options_list=["--authorization", "--au"],
            help="The authorization config in json.",
        )

    with self.argument_context("iot central export destination update") as context:
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="The partial destination definition. Provide path to JSON file or raw stringified JSON."
            " [File Path Example:./path/to/file.json]"
            " [Example of stringified JSON:{<Destination Data JSON>}]."
            " The request body must contain partial content of Destination.",
        )

    with self.argument_context("iot central device edge module") as context:
        context.argument(
            "module_id",
            options_list=["--module-id", "-m"],
            help="The module ID of the target module.",
        )

    with self.argument_context("iot central device edge children") as context:
        context.argument(
            "children_ids",
            nargs="+",
            options_list=["--children-ids"],
            help="Space-separated list of children device ids.",
        )
