# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""
from azure.cli.core.commands import CliCommandType, LongRunningOperation

pnp_runtime_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_pnp_runtime#{}"
)
iothub_job_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_job#{}")
iothub_message_endpoint_ops = CliCommandType(operations_tmpl="azext_iot.iothub.commands_message_endpoint#{}")
device_messaging_ops = CliCommandType(
    operations_tmpl="azext_iot.iothub.commands_device_messaging#{}"
)

class EndpointUpdateResultTransform(LongRunningOperation):  # pylint: disable=too-few-public-methods
    def __call__(self, poller):
        result = super(EndpointUpdateResultTransform, self).__call__(poller)
        return result.properties.routing.endpoints

def load_iothub_commands(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub job", command_type=iothub_job_ops) as cmd_group:
        cmd_group.command("create", "job_create")
        cmd_group.show_command("show", "job_show")
        cmd_group.command("list", "job_list")
        cmd_group.command("cancel", "job_cancel")

    with self.command_group("iot hub digital-twin", command_type=pnp_runtime_ops) as cmd_group:
        cmd_group.command("invoke-command", "invoke_device_command")
        cmd_group.show_command("show", "get_digital_twin")
        cmd_group.command("update", "patch_digital_twin")

    with self.command_group("iot hub messaging-endpoint", command_type=iothub_message_endpoint_ops) as cmd_group:
        pass

    with self.command_group("iot hub messaging-endpoint create", command_type=iothub_message_endpoint_ops) as cmd_group:
        cmd_group.command("event-hub", "message_endpoint_create_event_hub",
                         transform=EndpointUpdateResultTransform(self.cli_ctx))
        cmd_group.command("service-bus-queue", "message_endpoint_create_service_bus_queue",
                         transform=EndpointUpdateResultTransform(self.cli_ctx))
        cmd_group.command("service-bus-topic", "message_endpoint_create_service_bus_topic",
                         transform=EndpointUpdateResultTransform(self.cli_ctx))
        cmd_group.command("cosmos-db-collection", "message_endpoint_create_cosmos_db_collection",
                         transform=EndpointUpdateResultTransform(self.cli_ctx))
        cmd_group.command("storage-container", "message_endpoint_create_storage_container",
                         transform=EndpointUpdateResultTransform(self.cli_ctx))

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
