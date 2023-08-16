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
    get_three_state_flag,
    get_enum_type,
    tags_type,
)
from azext_iot.digitaltwins.common import (
    ADTEndpointAuthType,
    ADTPrivateConnectionStatusType,
    ADTPublicNetworkAccessType,
    ADTModelCreateFailurePolicy
)

depfor_type = CLIArgumentType(
    options_list=["--dependencies-for"],
    type=str,
    nargs="+",
    help="The set of models which will have their dependencies retrieved. "
    "If omitted, all models are retrieved. Format is a whitespace separated list.",
)


def load_digitaltwins_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("dt") as context:
        context.argument(
            "resource_group_name",
            arg_type=resource_group_name_type,
            help="Digital Twins instance resource group. "
            "You can configure the default group using `az configure --defaults group=<name>`.",
        )
        context.argument(
            "name",
            options_list=["-n", "--dtn", "--dt-name"],
            help="Digital Twins instance name.",
        )
        context.argument(
            "name_or_hostname",
            options_list=["-n", "--dtn", "--dt-name"],
            help="Digital Twins instance name or hostname. If an instance name is provided, the user subscription is "
            "first queried for the target instance to retrieve the hostname. If a hostname is provided, the "
            "subscription query is skipped and the provided value is used for subsequent interaction.",
        )
        context.argument(
            "location",
            options_list=["--location", "-l"],
            help="Digital Twins instance location. If no location is provided the resource group location is used."
            "You can configure the default location using `az configure --defaults location=<name>`.",
        ),
        context.argument(
            "tags",
            options_list=["--tags"],
            arg_type=tags_type,
            help="Digital Twins instance tags. Property bag in key-value pairs with the following format: a=b c=d",
        )
        context.argument(
            "endpoint_name",
            options_list=["--endpoint-name", "--en"],
            help="Endpoint name.",
        )
        context.argument(
            "route_name",
            options_list=["--route-name", "--rn"],
            help="Event route name.",
        )
        context.argument(
            "filter",
            options_list=["--filter"],
            help="Event route filter.",
        )
        context.argument(
            "role_type",
            options_list=["--role"],
            help="Role name or Id.",
        )
        context.argument(
            "assignee",
            options_list=["--assignee"],
            help="Represent a user, group, or service principal. supported format: "
            "object id, user sign-in name, or service principal name.",
        )
        context.argument(
            "model_id",
            options_list=["--model-id", "--dtmi", "-m"],
            help="Digital Twins model Id. Example: dtmi:com:example:Room;2",
        )
        context.argument(
            "twin_id",
            options_list=["--twin-id", "-t"],
            help="The digital twin Id.",
        )
        context.argument(
            "include_inherited",
            options_list=["--include-inherited"],
            help="Include assignments applied on parent scopes.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "top",
            type=int,
            options_list=["--top"],
            help="Maximum number of elements to return.",
        )
        context.argument(
            "public_network_access",
            options_list=["--public-network-access", "--pna"],
            help="Determines if the Digital Twins instance can be accessed from a public network.",
            arg_group="Network",
            arg_type=get_enum_type(ADTPublicNetworkAccessType),
        )

    with self.argument_context("dt create") as context:
        context.argument(
            "assign_identity",
            arg_group="Managed Service Identity",
            help="Assign a system generated identity to the Digital Twins instance.",
            arg_type=get_three_state_flag(),
            deprecate_info=context.deprecate(redirect="--mi-system-assigned")
        )
        context.argument(
            "scopes",
            arg_group="Managed Service Identity",
            nargs="+",
            options_list=["--scopes"],
            help="Space-separated scopes the system assigned identity can access. Cannot be used with --no-wait.",
        )
        context.argument(
            "role_type",
            arg_group="Managed Service Identity",
            options_list=["--role"],
            help="Role name or Id the system assigned identity will have.",
        )
        context.argument(
            "system_identity",
            arg_group="Managed Service Identity",
            options_list=["--mi-system-assigned"],
            arg_type=get_three_state_flag(),
            help="Assign a system generated identity to this Digital Twins instance.",
        )
        context.argument(
            "user_identities",
            arg_group="Managed Service Identity",
            nargs="+",
            options_list=["--mi-user-assigned"],
            help="Space-separated user identity resource ids to add to the Digital Twins instance.",
        )

    with self.argument_context("dt wait") as context:
        context.ignore("updated")

    with self.argument_context("dt endpoint create") as context:
        context.argument(
            "dead_letter_secret",
            options_list=["--deadletter-sas-uri", "--dsu"],
            help="Dead-letter storage container URL with SAS token for Key based authentication.",
            arg_group="Dead-letter Endpoint",
        )
        context.argument(
            "dead_letter_uri",
            options_list=["--deadletter-uri", "--du"],
            help="Dead-letter storage container URL for Identity based authentication.",
            arg_group="Dead-letter Endpoint",
        )
        context.argument(
            "auth_type",
            options_list=["--auth-type"],
            help="Endpoint authentication type.",
            arg_type=get_enum_type(ADTEndpointAuthType),
            deprecate_info=context.deprecate(redirect="identity")
        )
        context.argument(
            'system_identity',
            options_list=['--mi-system-assigned', '--system'],
            arg_type=get_three_state_flag(),
            help="Use the system-assigned managed identity for endpoint authentication."
        )
        context.argument(
            'user_identity',
            options_list=['--mi-user-assigned', '--user'],
            help="Use an user-assigned managed identity for endpoint authentication. "
            "Accepts the identity resource id."
        )

    with self.argument_context("dt endpoint create eventgrid") as context:
        context.argument(
            "eventgrid_topic_name",
            options_list=["--eventgrid-topic", "--egt"],
            help="Name of EventGrid Topic to integrate with.",
            arg_group="Event Grid Topic",
        )
        context.argument(
            "eventgrid_resource_group",
            options_list=["--eventgrid-resource-group", "--egg"],
            help="Name of EventGrid Topic resource group. If not provided, the Digital Twin "
            "instance resource group will be used.",
            arg_group="Event Grid Topic",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--eventgrid-subscription", "--egs"],
            help="Name or id of subscription where the endpoint resource exists. "
            "If no subscription is provided the default subscription is used.",
            arg_group="Event Grid Topic",
        )
        context.argument(
            "auth_type",
            options_list=["--auth-type"],
            help="Endpoint authentication type.",
            arg_type=get_enum_type(ADTEndpointAuthType),
            deprecate_info=context.deprecate(redirect="identity", hide=True)
        )

    with self.argument_context("dt endpoint create eventhub") as context:
        context.argument(
            "eventhub_name",
            options_list=["--eventhub", "--eh"],
            help="Name of EventHub to integrate with.",
            arg_group="Event Hub",
        )
        context.argument(
            "eventhub_policy",
            options_list=["--eventhub-policy", "--ehp"],
            help="EventHub policy to use for endpoint configuration. Required when --auth-type is KeyBased.",
            arg_group="Event Hub",
        )
        context.argument(
            "eventhub_namespace",
            options_list=["--eventhub-namespace", "--ehn"],
            help="EventHub Namespace identifier.",
            arg_group="Event Hub",
        )
        context.argument(
            "eventhub_resource_group",
            options_list=["--eventhub-resource-group", "--ehg"],
            help="Name of EventHub resource group. If not provided, the Digital Twin instance "
            "resource group will be used.",
            arg_group="Event Hub",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--eventhub-subscription", "--ehs"],
            help="Name or id of subscription where the endpoint resource exists. "
            "If no subscription is provided the default subscription is used.",
            arg_group="Event Hub",
        )

    with self.argument_context("dt endpoint create servicebus") as context:
        context.argument(
            "servicebus_topic_name",
            options_list=["--servicebus-topic", "--sbt"],
            help="Name of ServiceBus Topic to integrate with.",
            arg_group="Service Bus Topic",
        )
        context.argument(
            "servicebus_policy",
            options_list=["--servicebus-policy", "--sbp"],
            help="ServiceBus Topic policy to use for endpoint configuration. Required when --auth-type is KeyBased.",
            arg_group="Service Bus Topic",
        )
        context.argument(
            "servicebus_namespace",
            options_list=["--servicebus-namespace", "--sbn"],
            help="ServiceBus Namespace identifier.",
            arg_group="Service Bus Topic",
        )
        context.argument(
            "servicebus_resource_group",
            options_list=["--servicebus-resource-group", "--sbg"],
            help="Name of ServiceBus resource group. If not provided, the Digital Twin instance "
            "resource group will be used.",
            arg_group="Service Bus Topic",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--servicebus-subscription", "--sbs"],
            help="Name or id of subscription where the endpoint resource exists. "
            "If no subscription is provided the default subscription is used.",
            arg_group="Service Bus Topic",
        )

    with self.argument_context("dt endpoint wait") as context:
        context.ignore("updated")

    with self.argument_context("dt identity assign") as context:
        context.argument(
            'system_identity',
            options_list=['--mi-system-assigned', '--system'],
            arg_type=get_three_state_flag(),
            help="Assign a system-assigned managed identity to this Digital Twin instance."
        )
        context.argument(
            'user_identities',
            options_list=['--mi-user-assigned', '--user'],
            nargs='+',
            help="Assign user-assigned managed identities to this Digital Twin instance. "
            "Accepts space-separated list of identity resource ids."
        )
        context.argument(
            'identity_role',
            options_list=['--role'],
            help="Role to assign to the digital twin's system-assigned managed identity."
        )
        context.argument(
            'identity_scopes',
            options_list=['--scopes'],
            nargs='*',
            help="Space separated list of scopes to assign the role (--role) "
                 "for the system-assigned managed identity."
        )

    with self.argument_context("dt identity remove") as context:
        context.argument(
            'system_identity',
            options_list=['--mi-system-assigned', '--system'],
            arg_type=get_three_state_flag(),
            nargs='*',
            help="Remove the system-assigned managed identity to this Digital Twin instance."
        )
        context.argument(
            'user_identities',
            options_list=['--mi-user-assigned', '--user'],
            nargs='*',
            help="Remove user-assigned managed identities to this Digital Twin instance. "
            "Accepts space-separated list of identity resource ids."
        )

    with self.argument_context("dt twin") as context:
        context.argument(
            "query_command",
            options_list=["--query-command", "-q"],
            help="User query to be executed.",
        )
        context.argument(
            "show_cost",
            options_list=["--show-cost", "--cost"],
            help="Calculates and shows the query charge.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "relationship_id",
            options_list=["--relationship-id", "-r"],
            help="Relationship Id.",
        )
        context.argument(
            "relationship",
            options_list=["--relationship", "--kind"],
            help="Relationship name or kind. For example: 'contains'",
        )
        context.argument(
            "json_patch",
            options_list=["--json-patch", "--patch"],
            help="An update specification described by JSON-patch. "
            "Updates to property values and $model elements may happen in the same request. "
            "Operations are limited to add, replace and remove. Provide file path or inline JSON.",
        )
        context.argument(
            "etag", options_list=["--etag", "-e"], help="Entity tag value. The command will succeed if "
            "the etag matches the current etag for the resource."
        )
        context.argument(
            "component_path",
            options_list=["--component"],
            help="The path to the DTDL component.",
        )
        context.argument(
            "if_none_match",
            options_list=["--if-none-match"],
            help="Indicates the create operation should fail if an existing twin with the same id exists."
        )

    with self.argument_context("dt twin create") as context:
        context.argument(
            "properties",
            options_list=["--properties", "-p"],
            help="Initial property values for instantiating a digital twin or related components. "
            "Provide file path or inline JSON. Properties are required for twins that contain components, "
            "at the minimum you must provide an empty $metadata object for each component.",
        )

    with self.argument_context("dt twin telemetry") as context:
        context.argument(
            "telemetry",
            options_list=["--telemetry"],
            help="Inline telemetry JSON or file path to telemetry JSON. Default payload is an empty object: {}",
        )
        context.argument(
            "dt_id",
            options_list=["--dt-id"],
            help="A unique message identifier (in the scope of the digital twin id) that is commonly used "
            "for de-duplicating messages. If no value is provided a GUID is automatically generated.",
        )
        context.argument(
            "component_path",
            options_list=["--component"],
            help="The path to the DTDL component. If set, telemetry will be emitted on behalf of the component.",
        )
        context.argument(
            "telemetry_source_time",
            options_list=["--telemetry-source-time", "--tst"],
            help="An RFC 3339 timestamp that identifies the time the telemetry was measured.",
        )

    with self.argument_context("dt twin relationship") as context:
        context.argument(
            "twin_id",
            options_list=["--twin-id", "-t", "--source"],
            help="The source twin Id for a relationship.",
        )
        context.argument(
            "target_twin_id",
            options_list=["--target-twin-id", "--target"],
            help="The target twin Id for a relationship.",
        )

    with self.argument_context("dt twin relationship create") as context:
        context.argument(
            "properties",
            options_list=["--properties", "-p"],
            help="Initial property values for instantiating a digital twin relationship. Provide file path or inline JSON.",
        )

    with self.argument_context("dt twin relationship list") as context:
        context.argument(
            "incoming_relationships",
            options_list=["--incoming"],
            help="Retrieves all incoming relationships for a digital twin.",
            arg_type=get_three_state_flag(),
        )
        context.argument(
            "relationship",
            options_list=["--relationship", "--kind"],
            help="Filter result by the kind of relationship.",
        )

    with self.argument_context("dt model") as context:
        context.argument(
            "from_directory",
            options_list=["--from-directory", "--fd"],
            help="The directory JSON model files will be parsed from. "
            "Please Note: Models are created atomically when directory contains 250 or lesser models, hence in case of an "
            "error none of the models get created."
            "Input model set is chunked & created in batches when directory has more than 250 models(API limit). "
            "In case of an error processing a batch, the behavior is determined by the --failure-policy parameter. ",
            arg_group="Models Input",
        )
        context.argument(
            "max_models_per_batch",
            options_list=["--max-models-per-batch", "--mmpb"],
            type=int,
            is_experimental=True,
            help="The maximum model size per batch when creating more than 250 models."
            "Reduce this number to prevent a DTDLParser error. ",
            arg_group="Models Input"
        )
        context.argument(
            "models",
            options_list=["--models"],
            help="Inline model JSON or file path to model JSON. "
            "Please Note: Models are created atomically when model JSON contains 250 or lesser models, hence in case of an "
            "error none of the models get created."
            "Input model set is chunked & created in batches when model JSON has more than 250 models(API limit). "
            "In case of an error processing a batch, the behavior is determined by the --failure-policy parameter. ",
            arg_group="Models Input",
        )
        context.argument(
            "failure_policy",
            options_list=["--failure-policy", "--fp"],
            help="Indicates the failure policy when an error occurs while processing a models batch. "
            "In the 'Rollback' mode all models created in previous batches are deleted one at a time. "
            "When selected as 'None' the models created in previous batches are not deleted from DT instance.",
            arg_group="Models Input",
            arg_type=get_enum_type(ADTModelCreateFailurePolicy),
        )
        context.argument(
            "definition",
            options_list=["--definition", "--def"],
            arg_type=get_three_state_flag(),
            help="The operation will retrieve the model definition.",
        )
        context.argument(
            "decommission",
            options_list=["--decommission"],
            arg_type=get_three_state_flag(),
            help="Indicates intent to decommission a target model.",
        )
        context.argument(
            "dependencies_for",
            arg_type=depfor_type,
        )

    with self.argument_context("dt network private-link") as context:
        context.argument(
            "link_name",
            options_list=["--link-name", "--ln"],
            help="Private link name.",
            arg_group="Private Connection",
        )

    with self.argument_context("dt network private-endpoint") as context:
        context.argument(
            "conn_name",
            options_list=["--conn-name", "--cn"],
            help="Private endpoint connection name.",
            arg_group="Private Endpoint",
        )
        context.argument(
            "group_ids",
            options_list=["--group-ids"],
            help="Space separated list of group ids that the private endpoint should connect to.",
            arg_group="Private Endpoint",
            nargs="+",
        )
        context.argument(
            "status",
            options_list=["--status"],
            help="The status of a private endpoint connection.",
            arg_type=get_enum_type(ADTPrivateConnectionStatusType),
            arg_group="Private Endpoint",
        )
        context.argument(
            "description",
            options_list=["--description", "--desc"],
            help="Description for the private endpoint connection.",
            arg_group="Private Endpoint",
        )
        context.argument(
            "actions_required",
            options_list=["--actions-required", "--ar"],
            help="A message indicating if changes on the service provider require any updates on the consumer.",
            arg_group="Private Endpoint",
        )

    with self.argument_context("dt network private-endpoint connection wait") as context:
        context.ignore("created")
        context.ignore("exists")

    with self.argument_context("dt data-history") as context:
        context.argument(
            "conn_name",
            options_list=["--conn-name", "--cn"],
            help="Name of data history connection."
        )

    with self.argument_context("dt data-history connection create adx") as context:
        context.argument(
            "adx_cluster_name",
            options_list=["--adx-cluster-name", "--adxc"],
            help="Name of Azure Data Explorer cluster to integrate with.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_database_name",
            options_list=["--adx-database-name", "--adxd"],
            help="Name of Azure Data Explorer database to integrate with.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_resource_group",
            options_list=["--adx-resource-group", "--adxg"],
            help="Name of Azure Data Explorer resource group. If not provided, will use the Digital Twin's resource group.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_subscription",
            options_list=["--adx-subscription", "--adxs"],
            help="Name or id of subscription where the Azure Data Explorer exists. If not provided, will use the subscription "
                 "that contains the Digital Twin Instance.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_table_name",
            options_list=[
                "--adx-property-events-table",
                "--adxpet",
                context.deprecate(target='--adx-table-name', redirect='--adx-property-events-table'),
                context.deprecate(target='--adxt', redirect='--adxpet'),
            ],
            help="The name of the Azure Data Explorer table used for storing updates to properties of twins and relationships.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_twin_lifecycle_events_table_name",
            options_list=["--adx-twin-events-table", "--adxtet"],
            help="The name of the Azure Data Explorer table used for recording twin lifecycle events. The table will not be "
                 "created if this property is left unspecified.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "adx_relationship_lifecycle_events_table_name",
            options_list=["--adx-relationship-events-table", "--adxret"],
            help="The name of the Azure Data Explorer table used for recording relationship lifecycle events. The table will "
                 "not be created if this property is left unspecified.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "record_property_and_item_removals",
            options_list=["--adx-record-removals", "--adxrr"],
            arg_type=get_three_state_flag(),
            help="Specifies whether or not to record twin / relationship property and item removals, including removals of "
                 "indexed or keyed values (such as map entries, array elements, etc.). Setting this property to 'true' will "
                 "generate an additional column in the property events table in ADX.",
            arg_group="Azure Data Explorer",
        )
        context.argument(
            "eh_namespace",
            options_list=["--eventhub-namespace", "--ehn"],
            help="EventHub Namespace identifier.",
            arg_group="Event Hub",
        )
        context.argument(
            "eh_entity_path",
            options_list=["--eventhub", "--eh"],
            help="Name of EventHub to integrate with.",
            arg_group="Event Hub",
        )
        context.argument(
            "eh_consumer_group",
            options_list=["--eventhub-consumer-group", "--ehc"],
            help="The EventHub consumer group to use when ADX reads from EventHub.",
            arg_group="Event Hub",
        )
        context.argument(
            "eh_resource_group",
            options_list=["--eventhub-resource-group", "--ehg"],
            help="Name of EventHub resource group. If not provided, will use the Digital Twin's resource group.",
            arg_group="Event Hub",
        )
        context.argument(
            "eh_subscription",
            options_list=["--eventhub-subscription", "--ehs"],
            help="Name or id of subscription where the EventHub exists. If not provided, will use the subscription that contains"
                 " the Digital Twin Instance.",
            arg_group="Event Hub",
        )
        context.argument(
            "yes",
            options_list=['--yes', '-y'],
            help='Do not prompt for confirmation when assigning required roles.',
        )
        context.argument(
            'user_identity',
            options_list=['--mi-user-assigned', '--user'],
            help="Use an user-assigned managed identity for data history connection authentication. "
            "Accepts the identity resource id. If not provided, will use system identity instead."
        )

    with self.argument_context("dt data-history connection delete") as context:
        context.argument(
            "cleanup_connection_artifacts",
            options_list=["--clean", "-c"],
            arg_type=get_three_state_flag(),
            help="Specifies whether or not to attempt to clean up artifacts that were created in order to establish a "
                 "connection to the time series database. This is a best-effort attempt that will fail if appropriate "
                 "permissions are not in place. Setting this to 'true' does not delete any recorded data.",
        )

    with self.argument_context("dt job") as context:
        context.argument(
            "job_id",
            options_list=["--job-id", "-j"],
            help="Id of job. A system generated id is assigned when this parameter is ommitted during job creation.",
        )

    with self.argument_context("dt job import") as context:
        context.argument(
            "data_file_name",
            options_list=["--data-file", "--df"],
            help="Name of data file input to the bulk import job. The file must be in 'ndjson' format. Sample input data "
            "file: https://github.com/Azure/azure-iot-cli-extension/tree/dev/docs/samples/adt-bulk-import-data-sample.ndjson",
            arg_group="Bulk Import Job",
        )
        context.argument(
            "input_blob_container_name",
            options_list=["--input-blob-container", "--ibc"],
            help="Name of Azure Storage blob container which contains the bulk import data file.",
            arg_group="Bulk Import Job",
        )
        context.argument(
            "input_storage_account_name",
            options_list=["--input-storage-account", "--isa"],
            help="Name of Azure Storage account containing blob container which stores the bulk import data file.",
            arg_group="Bulk Import Job",
        )
        context.argument(
            "output_file_name",
            options_list=["--output-file", "--of"],
            help="Name of the bulk import job's output file. This file will contain logs as well as error information. "
            "The file gets created automatically once the job finishes. The file gets overwritten if it already exists. "
            "If not provided the output file is created with the name: <job_id>_output.txt",
            arg_group="Bulk Import Job",
        )
        context.argument(
            "output_blob_container_name",
            options_list=["--output-blob-container", "--obc"],
            help="Name of Azure Storage blob container where the bulk import job's output file will be created. "
            "If not provided, will use the input blob container.",
            arg_group="Bulk Import Job",
        )
        context.argument(
            "output_storage_account_name",
            options_list=["--output-storage-account", "--osa"],
            help="Name of Azure Storage account containing blob container where bulk import job's output file will be created. "
            "If not provided, will use the input storage account.",
            arg_group="Bulk Import Job",
        )
