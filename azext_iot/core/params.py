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

    # Load default CLI core args
    load_arguments(self, _)

    # DPS create / update identity params. Namespace links are managed only by
    # ``iot adr ns link`` and are intentionally absent here.
    for command in ("iot dps create", "iot dps update"):
        with self.argument_context(command) as c:
            c.argument(
                "mi_system_assigned",
                arg_type=get_three_state_flag(),
                options_list=[
                    "--system-assigned-mi",
                    c.deprecate(
                        target="--mi-system-assigned",
                        redirect="--system-assigned-mi",
                        hide=True,
                    ),
                ],
                help="Enable system-assigned managed identity for this provisioning service.",
            )
            c.argument(
                "mi_user_assigned",
                nargs="*",
                options_list=[
                    "--user-assigned-mi",
                    c.deprecate(
                        target="--mi-user-assigned",
                        redirect="--user-assigned-mi",
                        hide=True,
                    ),
                ],
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
