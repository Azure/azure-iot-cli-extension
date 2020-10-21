# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.profiles import ResourceType

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType

digitaltwins_resource_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_resource#{}"
)

digitaltwins_route_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_routes#{}"
)

digitaltwins_model_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_models#{}"
)

digitaltwins_twin_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_twins#{}"
)

digitaltwins_rbac_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_rbac#{}"
)


def load_digitaltwins_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group(
        "dt",
        command_type=digitaltwins_resource_ops,
        resource_type=ResourceType.MGMT_RESOURCE_RESOURCES,
    ) as cmd_group:
        cmd_group.command("create", "create_instance")
        cmd_group.show_command("show", "show_instance")
        cmd_group.command("list", "list_instances")
        cmd_group.command("delete", "delete_instance")

    with self.command_group(
        "dt endpoint", command_type=digitaltwins_resource_ops
    ) as cmd_group:
        cmd_group.show_command(
            "show",
            "show_endpoint",
            table_transformer=(
                "{EndpointName:name, EndpointType:properties.endpointType,"
                "ProvisioningState:properties.provisioningState,CreatedTime:properties.createdTime}"
            ),
        )
        cmd_group.command(
            "list",
            "list_endpoints",
            table_transformer=(
                "[*].{EndpointName:name, EndpointType:properties.endpointType,"
                "ProvisioningState:properties.provisioningState,CreatedTime:properties.createdTime}"
            ),
        )
        cmd_group.command("delete", "delete_endpoint")

    with self.command_group(
        "dt endpoint create", command_type=digitaltwins_resource_ops
    ) as cmd_group:
        cmd_group.command("eventgrid", "add_endpoint_eventgrid")
        cmd_group.command("servicebus", "add_endpoint_servicebus")
        cmd_group.command("eventhub", "add_endpoint_eventhub")

    with self.command_group(
        "dt route", command_type=digitaltwins_route_ops
    ) as cmd_group:
        cmd_group.show_command(
            "show",
            "show_route",
            table_transformer="{RouteName:id,EndpointName:endpointName,Filter:filter}",
        )
        cmd_group.command(
            "list",
            "list_routes",
            table_transformer="[*].{RouteName:id,EndpointName:endpointName,Filter:filter}",
        )
        cmd_group.command("delete", "delete_route")
        cmd_group.command("create", "create_route")

    with self.command_group(
        "dt role-assignment", command_type=digitaltwins_rbac_ops
    ) as cmd_group:
        cmd_group.command("create", "assign_role")
        cmd_group.command("delete", "remove_role")
        cmd_group.command("list", "list_assignments")

    with self.command_group("dt twin", command_type=digitaltwins_twin_ops) as cmd_group:
        cmd_group.command("query", "query_twins")
        cmd_group.command("create", "create_twin")
        cmd_group.show_command("show", "show_twin")
        cmd_group.command("update", "update_twin")
        cmd_group.command("delete", "delete_twin")

    with self.command_group(
        "dt twin component", command_type=digitaltwins_twin_ops
    ) as cmd_group:
        cmd_group.show_command("show", "show_component")
        cmd_group.command("update", "update_component")

    with self.command_group(
        "dt twin relationship", command_type=digitaltwins_twin_ops
    ) as cmd_group:
        cmd_group.command("create", "create_relationship")
        cmd_group.show_command("show", "show_relationship")
        cmd_group.command("list", "list_relationships")
        cmd_group.command("update", "update_relationship")
        cmd_group.command("delete", "delete_relationship")

    with self.command_group(
        "dt twin telemetry", command_type=digitaltwins_twin_ops
    ) as cmd_group:
        cmd_group.command("send", "send_telemetry")

    with self.command_group(
        "dt model", command_type=digitaltwins_model_ops
    ) as cmd_group:
        cmd_group.command("create", "add_models")
        cmd_group.show_command(
            "show",
            "show_model",
            table_transformer="{ModelId:id,UploadTime:uploadTime,Decommissioned:decommissioned}",
        )
        cmd_group.command(
            "list",
            "list_models",
            table_transformer="[*].{ModelId:id,UploadTime:uploadTime,Decommissioned:decommissioned}",
        )
        cmd_group.command("update", "update_model")
        cmd_group.command("delete", "delete_model")
