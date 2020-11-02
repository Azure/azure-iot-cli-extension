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
    tags_type
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
            "filter", options_list=["--filter"], help="Event route filter.",
        )
        context.argument(
            "role_type", options_list=["--role"], help="Role name or Id.",
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
            "twin_id", options_list=["--twin-id", "-t"], help="The digital twin Id.",
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

    with self.argument_context("dt endpoint create") as context:
        context.argument(
            "dead_letter_endpoint",
            options_list=["--deadletter-sas-uri", "--dsu"],
            help="Dead-letter storage container URL with SAS token",
            arg_group="Dead-letter Endpoint"
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
            help="Name of EventGrid Topic resource group.",
            arg_group="Event Grid Topic",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--eventgrid-subscription", "--egs"],
            help="Name or ID of subscription where the endpoint resource exists. "
            "If no subscription is provided the default subscription is used.",
            arg_group="Event Grid Topic",
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
            help="EventHub policy to use for endpoint configuration.",
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
            help="Name of EventHub resource group.",
            arg_group="Event Hub",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--eventhub-subscription", "--ehs"],
            help="Name or ID of subscription where the endpoint resource exists. "
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
            help="ServiceBus Topic policy to use for endpoint configuration.",
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
            help="Name of ServiceBus resource group.",
            arg_group="Service Bus Topic",
        )
        context.argument(
            "endpoint_subscription",
            options_list=["--servicebus-subscription", "--sbs"],
            help="Name or ID of subscription where the endpoint resource exists. "
            "If no subscription is provided the default subscription is used.",
            arg_group="Service Bus Topic",
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
            "component_path",
            options_list=["--component"],
            help="The path to the DTDL component.",
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
            help="The directory JSON model files will be parsed from.",
            arg_group="Models Input",
        )
        context.argument(
            "models",
            options_list=["--models"],
            help="Inline model JSON or file path to model JSON.",
            arg_group="Models Input",
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
            "dependencies_for", arg_type=depfor_type,
        )
