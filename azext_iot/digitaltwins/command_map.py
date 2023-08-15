# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType
from azure.cli.core.commands import LongRunningOperation

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

digitaltwins_job_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_jobs#{}"
)

digitaltwins_identity_ops = CliCommandType(
    operations_tmpl="azext_iot.digitaltwins.commands_identity#{}"
)


class IdentityResultTransform(LongRunningOperation):
    def __call__(self, poller):
        result = super(IdentityResultTransform, self).__call__(poller)
        return result.identity


def load_digitaltwins_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group(
        "dt",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        cmd_group.command("create", "create_instance", supports_no_wait=True)
        cmd_group.show_command("show", "show_instance")
        cmd_group.command("list", "list_instances")
        cmd_group.command("delete", "delete_instance", confirmation=True, supports_no_wait=True)
        cmd_group.wait_command("wait", "wait_instance")
        cmd_group.command(
            "reset",
            "reset_instance",
            confirmation=True,
            deprecate_info=self.deprecate(redirect="az dt job delete-all create", hide=True)
        )

    with self.command_group(
        "dt data-history",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        pass

    with self.command_group(
        "dt data-history connection",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        cmd_group.show_command("show", "show_data_connection")
        cmd_group.wait_command("wait", "wait_data_connection")
        cmd_group.command("list", "list_data_connection")
        cmd_group.command(
            "delete", "delete_data_connection", confirmation=True, supports_no_wait=True
        )

    with self.command_group(
        "dt data-history connection create",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        cmd_group.command("adx", "create_adx_data_connection", supports_no_wait=True)

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
        cmd_group.command("delete", "delete_endpoint", confirmation=True, supports_no_wait=True)
        cmd_group.wait_command(
            "wait", "wait_endpoint"
        )

    with self.command_group(
        "dt endpoint create", command_type=digitaltwins_resource_ops
    ) as cmd_group:
        cmd_group.command("eventgrid", "add_endpoint_eventgrid", supports_no_wait=True)
        cmd_group.command("servicebus", "add_endpoint_servicebus", supports_no_wait=True)
        cmd_group.command("eventhub", "add_endpoint_eventhub", supports_no_wait=True)

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
        "dt identity", command_type=digitaltwins_identity_ops
    ) as cmd_group:
        cmd_group.command("assign", "assign_identity", transform=IdentityResultTransform(self.cli_ctx))
        cmd_group.command("remove", "remove_identity", transform=IdentityResultTransform(self.cli_ctx))
        cmd_group.show_command("show", "show_identity")

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
        cmd_group.command("delete-all", "delete_all_twin", confirmation=True)

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
        cmd_group.command("delete-all", "delete_all_relationship", confirmation=True)

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
        cmd_group.command("delete-all", "delete_all_models", confirmation=True)

    with self.command_group(
        "dt network",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        pass

    with self.command_group(
        "dt network private-link",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        cmd_group.show_command("show", "show_private_link")
        cmd_group.command("list", "list_private_links")

    with self.command_group(
        "dt network private-endpoint",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        pass

    with self.command_group(
        "dt network private-endpoint connection",
        command_type=digitaltwins_resource_ops,
    ) as cmd_group:
        cmd_group.command("set", "set_private_endpoint_conn", supports_no_wait=True)
        cmd_group.show_command("show", "show_private_endpoint_conn")
        cmd_group.command("list", "list_private_endpoint_conns")
        cmd_group.command("delete", "delete_private_endpoint_conn", confirmation=True, supports_no_wait=True)
        cmd_group.wait_command(
            "wait", "wait_private_endpoint_conn"
        )

    with self.command_group(
        "dt job",
        command_type=digitaltwins_job_ops,
    ) as cmd_group:
        pass

    with self.command_group(
        "dt job import",
        command_type=digitaltwins_job_ops
    ) as cmd_group:
        cmd_group.command("create", "create_import_job")
        cmd_group.show_command("show", "show_import_job")
        cmd_group.command("list", "list_import_jobs")
        cmd_group.command("delete", "delete_import_job", confirmation=True)
        cmd_group.command("cancel", "cancel_import_job", confirmation=True)

    with self.command_group(
        "dt job deletion",
        command_type=digitaltwins_job_ops,
        is_preview=True
    ) as cmd_group:
        cmd_group.command("create", "create_delete_job", confirmation=True)
        cmd_group.show_command("show", "show_delete_job")
        cmd_group.command("list", "list_delete_jobs")
