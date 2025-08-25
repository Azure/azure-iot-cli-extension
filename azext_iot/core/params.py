# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Parameter definitions for IoT Hub and DPS management commands.
"""

from azure.cli.core.commands.parameters import get_three_state_flag


def load_core_arguments(self, _):

    # TODO - CMS Preview - IoT Hub  params
    with self.argument_context("iot hub") as c:
        c.argument(
            "adr_ns_id",
            options_list=["--ns-resource-id"],
            help="Device Registry namespace resource ID to link to this IoT hub.",
        )
        c.argument(
            "adr_ns_identity_id",
            options_list=["--ns-identity-id"],
            help="Managed identity resource ID for Device Registry namespace.",
        )
        c.argument(
            "system_identity",
            arg_type=get_three_state_flag(),
            options_list=["--mi-system-assigned"],
            help="Enable system-assigned managed identity for this IoT hub.",
        )
        c.argument(
            "user_identities",
            nargs="*",
            options_list=["--mi-user-assigned"],
            help="Enable user-assigned managed identities for this IoT hub. "
            "Accepts space-separated list of identity resource IDs.",
        )

    # TODO - CMS Preview - DPS params
    with self.argument_context("iot dps") as c:
        c.argument(
            "adr_ns_id",
            options_list=["--ns-resource-id", "--ns-id"],
            help="Device Registry namespace resource ID to link to this provisioning service.",
        )
        c.argument(
            "adr_ns_identity_id",
            options_list=["--ns-identity-id"],
            help="Managed identity resource ID for Device Registry namespace."
        )
        c.argument(
            "mi_system_assigned",
            arg_type=get_three_state_flag(),
            options_list=["--mi-system-assigned"],
            help="Enable system-assigned managed identity for this provisioning service.",
        )
        c.argument(
            "mi_user_assigned",
            nargs="*",
            options_list=["--mi-user-assigned"],
            help="Enable user-assigned managed identities for this provisioning service. "
            "Accepts space-separated list of identity resource IDs.",
        )

    with self.argument_context("iot dps identity assign") as c:
        c.argument(
            "system_assigned",
            arg_type=get_three_state_flag(),
            options_list=["--system", "--system-assigned"],
            help="Assign a system-assigned managed identity to this provisioning service.",
        )
        c.argument(
            "user_assigned",
            nargs="*",
            options_list=["--user", "--user-assigned"],
            help="Assign user-assigned managed identities to this provisioning service. "
            "Accepts space-separated list of identity resource IDs.",
        )

    with self.argument_context("iot dps identity remove") as c:
        c.argument(
            "system_assigned",
            arg_type=get_three_state_flag(),
            options_list=["--system", "--system-assigned"],
            help="Remove a system-assigned managed identity from this provisioning service.",
        )
        c.argument(
            "user_assigned",
            nargs="*",
            options_list=["--user", "--user-assigned"],
            help="Remove user-assigned managed identities from this provisioning service. "
            "Accepts space-separated list of identity resource IDs.",
        )
    # TODO - CMS Preview - sort out -n / --hub-name / --dps-name
    with self.argument_context("iot dps linked-hub") as context:
        context.argument(
            "hub_name",
            options_list=["--hub-name"],
            help="IoT Hub name to link to DPS.",
            arg_group="IoT Hub Identifier"
        )