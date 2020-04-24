# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Load CLI commands
"""

from azext_iot import (
    iothub_ops,
    iotdps_ops,
    iotdigitaltwin_ops,
    iotpnp_ops,
    iotcentral_ops,
)


def load_command_table(self, _):
    """
    Load CLI commands
    """
    with self.command_group("iot hub", command_type=iothub_ops) as cmd_group:
        cmd_group.command("query", "iot_query")
        cmd_group.command("invoke-device-method", "iot_device_method")
        cmd_group.command("invoke-module-method", "iot_device_module_method")
        cmd_group.command("generate-sas-token", "iot_get_sas_token")
        cmd_group.command("monitor-events", "iot_hub_monitor_events")
        cmd_group.command("monitor-feedback", "iot_hub_monitor_feedback")

    with self.command_group(
        "iot hub device-identity", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("create", "iot_device_create")
        cmd_group.command("show", "iot_device_show")
        cmd_group.command("list", "iot_device_list")
        cmd_group.command("delete", "iot_device_delete")
        cmd_group.generic_update_command(
            "update", getter_name="iot_device_show", setter_name="iot_device_update"
        )

        cmd_group.command("show-connection-string", "iot_get_device_connection_string")
        cmd_group.command("import", "iot_device_import")
        cmd_group.command("export", "iot_device_export")
        cmd_group.command("add-children", "iot_device_children_add")
        cmd_group.command("remove-children", "iot_device_children_remove")
        cmd_group.command("list-children", "iot_device_children_list")
        cmd_group.command("get-parent", "iot_device_get_parent")
        cmd_group.command("set-parent", "iot_device_set_parent")

    with self.command_group(
        "iot hub module-identity", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("create", "iot_device_module_create")
        cmd_group.command("show", "iot_device_module_show")
        cmd_group.command("list", "iot_device_module_list")
        cmd_group.command("delete", "iot_device_module_delete")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_device_module_show",
            setter_name="iot_device_module_update",
        )

        cmd_group.command("show-connection-string", "iot_get_module_connection_string")

    with self.command_group(
        "iot hub module-twin", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("show", "iot_device_module_twin_show")
        cmd_group.command("replace", "iot_device_module_twin_replace")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_device_module_twin_show",
            setter_name="iot_device_module_twin_update",
            custom_func_name="iot_twin_update_custom",
            custom_func_type=iothub_ops,
        )

    with self.command_group(
        "iot hub device-twin", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("show", "iot_device_twin_show")
        cmd_group.command("replace", "iot_device_twin_replace")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_device_twin_show",
            setter_name="iot_device_twin_update",
            custom_func_name="iot_twin_update_custom",
            custom_func_type=iothub_ops,
        )

    with self.command_group(
        "iot hub configuration", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("show-metric", "iot_hub_configuration_metric_show")
        cmd_group.command("create", "iot_hub_configuration_create")
        cmd_group.command("show", "iot_hub_configuration_show")
        cmd_group.command("list", "iot_hub_configuration_list")
        cmd_group.command("delete", "iot_hub_configuration_delete")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_hub_configuration_show",
            setter_name="iot_hub_configuration_update",
        )

    with self.command_group(
        "iot hub distributed-tracing", command_type=iothub_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("show", "iot_hub_distributed_tracing_show")
        cmd_group.command("update", "iot_hub_distributed_tracing_update")

    with self.command_group("iot edge", command_type=iothub_ops) as cmd_group:
        cmd_group.command("set-modules", "iot_edge_set_modules")

    with self.command_group(
        "iot edge deployment", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("show-metric", "iot_edge_deployment_metric_show")
        cmd_group.command("create", "iot_edge_deployment_create")
        cmd_group.command("show", "iot_hub_configuration_show")
        cmd_group.command("list", "iot_edge_deployment_list")
        cmd_group.command("delete", "iot_hub_configuration_delete")
        cmd_group.generic_update_command(
            "update",
            getter_name="iot_hub_configuration_show",
            setter_name="iot_hub_configuration_update",
        )

    with self.command_group("iot device", command_type=iothub_ops) as cmd_group:
        cmd_group.command("send-d2c-message", "iot_device_send_message")
        cmd_group.command("simulate", "iot_simulate_device")
        cmd_group.command("upload-file", "iot_device_upload_file")

    with self.command_group(
        "iot device c2d-message", command_type=iothub_ops
    ) as cmd_group:
        cmd_group.command("complete", "iot_c2d_message_complete")
        cmd_group.command("abandon", "iot_c2d_message_abandon")
        cmd_group.command("reject", "iot_c2d_message_reject")
        cmd_group.command("receive", "iot_c2d_message_receive")
        cmd_group.command("send", "iot_c2d_message_send")

    with self.command_group("iot dps enrollment", command_type=iotdps_ops) as cmd_group:
        cmd_group.command("create", "iot_dps_device_enrollment_create")
        cmd_group.command("list", "iot_dps_device_enrollment_list")
        cmd_group.command("show", "iot_dps_device_enrollment_get")
        cmd_group.command("update", "iot_dps_device_enrollment_update")
        cmd_group.command("delete", "iot_dps_device_enrollment_delete")

    with self.command_group(
        "iot dps enrollment-group", command_type=iotdps_ops
    ) as cmd_group:
        cmd_group.command("create", "iot_dps_device_enrollment_group_create")
        cmd_group.command("list", "iot_dps_device_enrollment_group_list")
        cmd_group.command("show", "iot_dps_device_enrollment_group_get")
        cmd_group.command("update", "iot_dps_device_enrollment_group_update")
        cmd_group.command("delete", "iot_dps_device_enrollment_group_delete")

    with self.command_group(
        "iot dps registration", command_type=iotdps_ops
    ) as cmd_group:
        cmd_group.command("list", "iot_dps_registration_list")
        cmd_group.command("show", "iot_dps_registration_get")
        cmd_group.command("delete", "iot_dps_registration_delete")

    with self.command_group(
        'iotcentral', command_type=iotcentral_ops,
        deprecate_info=self.deprecate(redirect='iot central', hide=True)
    ) as cmd_group:
        pass

    with self.command_group("iotcentral app", command_type=iotcentral_ops) as cmd_group:
        cmd_group.command(
            "monitor-events",
            "iot_central_monitor_events",
        )

    with self.command_group(
        "iotcentral device-twin", command_type=iotcentral_ops
    ) as cmd_group:
        cmd_group.command(
            "show",
            "iot_central_device_show",
        )

    with self.command_group(
        "iot central app", command_type=iotcentral_ops
    ) as cmd_group:
        cmd_group.command("monitor-events", "iot_central_monitor_events")
        cmd_group.command(
            "validate-messages", "iot_central_validate_messages", is_preview=True
        )

    with self.command_group(
        "iot central device-twin", command_type=iotcentral_ops
    ) as cmd_group:
        cmd_group.command("show", "iot_central_device_show")

    with self.command_group(
        "iot dt", command_type=iotdigitaltwin_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("list-interfaces", "iot_digitaltwin_interface_list")
        cmd_group.command("list-properties", "iot_digitaltwin_properties_list")
        cmd_group.command("update-property", "iot_digitaltwin_property_update")
        cmd_group.command("invoke-command", "iot_digitaltwin_invoke_command")
        cmd_group.command("monitor-events", "iot_digitaltwin_monitor_events")
        cmd_group.command("list-commands", "iot_digitaltwin_command_list")

    with self.command_group(
        "iot pnp interface", command_type=iotpnp_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("show", "iot_pnp_interface_show")
        cmd_group.command("list", "iot_pnp_interface_list")
        cmd_group.command("create", "iot_pnp_interface_create")
        cmd_group.command("publish", "iot_pnp_interface_publish")
        cmd_group.command("delete", "iot_pnp_interface_delete")
        cmd_group.command("update", "iot_pnp_interface_update")

    with self.command_group(
        "iot pnp capability-model", command_type=iotpnp_ops, is_preview=True
    ) as cmd_group:
        cmd_group.command("show", "iot_pnp_model_show")
        cmd_group.command("list", "iot_pnp_model_list")
        cmd_group.command("create", "iot_pnp_model_create")
        cmd_group.command("publish", "iot_pnp_model_publish")
        cmd_group.command("delete", "iot_pnp_model_delete")
        cmd_group.command("update", "iot_pnp_model_update")
