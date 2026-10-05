# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Parameter definitions for new DPS management commands.
These will be added to CLI Core
"""

from azure.cli.core.commands.parameters import get_three_state_flag

from azext_iot.core._params import load_arguments


def load_core_arguments(self, _):

    # load default CLI Core args
    load_arguments(self, _)

    # DPS local authentication params
    for scope in ["iot dps create", "iot dps update"]:
        with self.argument_context(scope) as c:
            c.argument(
                "disable_local_auth",
                arg_type=get_three_state_flag(),
                options_list=["--disable-local-auth", "--dla"],
                help="A boolean indicating whether or not to disable SAS key (shared access policy) "
                "authentication for this provisioning service. When disabled, only Azure RBAC is "
                "used to authorize data plane requests.",
            )
