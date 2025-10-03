# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Parameter definitions for new IoT Hub and DPS management commands.
These will be added to CLI Core
"""

from azure.cli.core.commands.parameters import get_three_state_flag

from azext_iot.core._params import load_arguments


def load_core_arguments(self, _):

    # TODO - CMS Preview - load default CLI Core args
    load_arguments(self, _)

    # IoT Hub ADR params
    with self.argument_context("iot hub") as c:
        c.argument(
            "adr_ns_id",
            options_list=["--ns-resource-id"],
            help="Device Registry namespace resource ID to link to this IoT hub.",
        )
        c.argument(
            "adr_ns_identity_id",
            options_list=["--ns-identity-id"],
            help="User-managed identity resource ID to access Device Registry namespace.",
        )

    # IoT Hub create - namespace role assignment customization
    with self.argument_context("iot hub create") as context:
        context.argument(
            "skip_ns_role_assignments",
            options_list=["--skip-ns-ra"],
            arg_group="ADR Namespace Role Assignment",
            arg_type=get_three_state_flag(),
            help="Used to skip ADR Namespace role assignment after IoT hub creation. "
            "Only applicable to Gen2 IoT Hubs."
        )

        context.argument(
            "custom_ns_role_id",
            options_list=["--custom-ns-role-id"],
            arg_group="ADR Namespace Role Assignment",
            help="Fully qualified role definition Id to apply to ADR Namespace, in the following format: "
            "/subscriptions/{subscriptionId}/providers/Microsoft.Authorization/roleDefinitions/{roleId}. "
            "Only applicable to Gen2 IoT Hubs.",
        )

    # DPS create / update ADR and identity params
    with self.argument_context("iot dps") as c:
        c.argument(
            "adr_ns_id",
            options_list=["--ns-resource-id", "--ns-id"],
            help="Device Registry namespace resource ID to link to this provisioning service.",
        )
        c.argument(
            "adr_ns_identity_id",
            options_list=["--ns-identity-id"],
            help="User-managed identity resource ID to access Device Registry namespace.",
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

    # DPS identity assignment params
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

    # DPS identity removal params
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
