# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType, LongRunningOperation
from azure.cli.core.profiles import ResourceType

pnp_runtime_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_pnp_runtime#{}"
)
iothub_job_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_job#{}")
iothub_message_endpoint_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_message_endpoint#{}")
iothub_message_route_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_message_route#{}")
device_messaging_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_device_messaging#{}"
)
iothub_state_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_state#{}")
device_identity_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_device_identity#{}"
)
iothub_resource_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_certificate#{}"
)


class EndpointUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super(EndpointUpdateResultTransform, self).__call__(poller)
        return result.properties.routing.endpoints


class RouteUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super(RouteUpdateResultTransform, self).__call__(poller)
        return result.properties.routing.routes


def load_iothub_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub job", command_type=iothub_job_ops) as cmd_group:
        cmd_group.command("create", "job_create")
        cmd_group.show_command("show", "job_show")
        cmd_group.command("list", "job_list")
        cmd_group.command("cancel", "job_cancel")

    with self.command_group(
        "iot hub digital-twin", command_type=pnp_runtime_ops
    ) as cmd_group:
        cmd_group.command("invoke-command", "invoke_device_command")
        cmd_group.show_command("show", "get_digital_twin")
        cmd_group.command("update", "patch_digital_twin")

    with self.command_group(
        "iot hub message-endpoint", command_type=iothub_message_endpoint_ops, is_preview=True
    ) as cmd_group:
        cmd_group.show_command("show", "message_endpoint_show")
        cmd_group.command("list", "message_endpoint_list")
        cmd_group.command(
            "delete",
            "message_endpoint_delete",
            transform=EndpointUpdateResultTransform(self.cli_ctx),
            confirmation=True
        )

    with self.command_group(
        "iot hub message-endpoint create",
        command_type=iothub_message_endpoint_ops,
    ) as cmd_group:
        cmd_group.command(
            "eventhub",
            "message_endpoint_create_event_hub",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "servicebus-queue",
            "message_endpoint_create_service_bus_queue",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "servicebus-topic",
            "message_endpoint_create_service_bus_topic",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "cosmosdb-container",
            "message_endpoint_create_cosmos_db_container",
            transform=EndpointUpdateResultTransform(self.cli_ctx),
            resource_type=ResourceType.MGMT_IOTHUB,
            min_api="2022-04-30-preview"
        )
        cmd_group.command(
            "storage-container",
            "message_endpoint_create_storage_container",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )

    with self.command_group(
        "iot hub message-endpoint update",
        command_type=iothub_message_endpoint_ops,
    ) as cmd_group:
        cmd_group.command(
            "eventhub",
            "message_endpoint_update_event_hub",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "servicebus-queue",
            "message_endpoint_update_service_bus_queue",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "servicebus-topic",
            "message_endpoint_update_service_bus_topic",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command(
            "cosmosdb-container",
            "message_endpoint_update_cosmos_db_container",
            transform=EndpointUpdateResultTransform(self.cli_ctx),
            resource_type=ResourceType.MGMT_IOTHUB,
            min_api="2022-04-30-preview"
        )
        cmd_group.command(
            "storage-container",
            "message_endpoint_update_storage_container",
            transform=EndpointUpdateResultTransform(self.cli_ctx)
        )

    with self.command_group(
        'iot hub message-route', command_type=iothub_message_route_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command(
            'create', 'message_route_create', transform=RouteUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.show_command('show', 'message_route_show')
        cmd_group.command('list', 'message_route_list')
        cmd_group.command(
            'delete',
            'message_route_delete',
            transform=RouteUpdateResultTransform(self.cli_ctx),
            confirmation=True
        )
        cmd_group.command(
            'update', 'message_route_update', transform=RouteUpdateResultTransform(self.cli_ctx)
        )
        cmd_group.command('test', 'message_route_test')

    with self.command_group("iot hub message-route fallback", command_type=iothub_message_route_ops) as cmd_group:
        cmd_group.show_command("show", "message_fallback_route_show")
        cmd_group.command("set", "message_fallback_route_set")

    with self.command_group("iot device", command_type=device_messaging_ops) as cmd_group:
        cmd_group.command("send-d2c-message", "iot_device_send_message")
        cmd_group.command("simulate", "iot_simulate_device", is_experimental=True)
        cmd_group.command("upload-file", "iot_device_upload_file")

    with self.command_group(
        "iot device c2d-message", command_type=device_messaging_ops
    ) as cmd_group:
        cmd_group.command("complete", "iot_c2d_message_complete")
        cmd_group.command("abandon", "iot_c2d_message_abandon")
        cmd_group.command("reject", "iot_c2d_message_reject")
        cmd_group.command("receive", "iot_c2d_message_receive")
        cmd_group.command("send", "iot_c2d_message_send")
        cmd_group.command("purge", "iot_c2d_message_purge")

    with self.command_group("iot hub state", command_type=iothub_state_ops, is_experimental=True) as cmd_group:
        cmd_group.command("export", "state_export")
        cmd_group.command("import", "state_import")
        cmd_group.command("migrate", "state_migrate")

    with self.command_group(
        "iot edge devices", command_type=device_identity_ops
    ) as cmd_group:
        cmd_group.command("create", "iot_edge_devices_create", is_experimental=True)

    with self.command_group(
        "iot hub certificate root-authority", command_type=iothub_resource_ops, is_experimental=True
    ) as cmd_group:
        cmd_group.show_command("show", "certificate_root_authority_show")
        cmd_group.command("set", "certificate_root_authority_set")
