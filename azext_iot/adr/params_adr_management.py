# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands.parameters import (
    get_location_type,
    get_three_state_flag,
    resource_group_name_type,
    tags_type,
)
from azure.cli.core.commands.validators import get_default_location_from_resource_group


def load_adr_management_arguments(self, _):
    with self.argument_context("iot adr ns") as context:
        context.argument("resource_group_name", arg_type=resource_group_name_type)
        context.argument(
            "namespace_name", options_list=["--namespace", "--name", "-n"],
            help="Name of the Device Registry namespace.",
        )

    with self.argument_context("iot adr ns create") as context:
        context.argument(
            "location", arg_type=get_location_type(self.cli_ctx),
            validator=get_default_location_from_resource_group,
        )

    for command in ("create", "update"):
        with self.argument_context(f"iot adr ns {command}") as context:
            context.argument("tags", arg_type=tags_type)
            context.argument(
                "system_assigned", options_list=["--system-assigned"],
                arg_type=get_three_state_flag(),
                help="Enable the system-assigned identity (SystemAssigned) or disable it (None). "
                     "Defaults to enabled on create; unchanged on update.",
            )
            context.argument(
                "messaging_endpoints", options_list=["--messaging-endpoints"],
                help="JSON object or file mapping endpoint names to objects with required address and optional "
                     "endpointType/resourceId. Replaces the endpoint map; use '{}' to clear it.",
            )

    with self.argument_context("iot adr ns migrate") as context:
        context.argument(
            "resource_ids", options_list=["--resource-ids"], nargs="+",
            help="Resource IDs of legacy Microsoft.DeviceRegistry/assets resources to migrate into the namespace.",
        )
