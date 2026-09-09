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


def load_adr_workflow_arguments(self, _):
    for command in ("iot adr ns check", "iot adr ns setup"):
        with self.argument_context(command) as context:
            context.argument(
                "namespace_name",
                options_list=["--name", "-n", "--namespace", "--ns"],
                help="Device Registry namespace name.",
            )
            context.argument(
                "resource_group_name",
                arg_type=resource_group_name_type,
            )
            context.argument(
                "no_input",
                options_list=["--no-input"],
                arg_type=get_three_state_flag(),
                help="Disable interactive prompts.",
            )
            context.argument(
                "plain",
                options_list=["--plain"],
                arg_type=get_three_state_flag(),
                help="Use append-only text without color or animation.",
            )

    with self.argument_context("iot adr ns setup") as context:
        context.argument("location", arg_type=get_location_type(self.cli_ctx))
        context.argument("tags", arg_type=tags_type)
        context.argument(
            "namespace_outbound_identity",
            options_list=[
                "--outbound-identity",
                "--namespace-outbound-identity",
            ],
            help=(
                "'system-assigned' or a user-assigned identity ARM resource "
                "ID. Omit to reuse the namespace's current outbound identity."
            ),
        )
        context.argument(
            "dps",
            options_list=["--dps"],
            nargs="+",
            help="DPS endpoint as key=value pairs.",
        )
        context.argument(
            "hubs",
            options_list=["--hub"],
            nargs="+",
            action="append",
            help="IoT Hub endpoint as key=value pairs. Use --hub more than once.",
        )
        context.argument(
            "software_updates",
            options_list=["--software-updates", "--su"],
            nargs="+",
            help="Software Updates endpoint as key=value pairs.",
        )
        context.argument(
            "complete_connectivity",
            options_list=["--complete", "--complete-connectivity"],
            arg_type=get_three_state_flag(),
            help="Require both a DPS and at least one IoT Hub input.",
        )
        context.argument(
            "config",
            options_list=["--config"],
            help="Workflow request as a JSON or YAML file.",
        )
        context.argument(
            "plan_only",
            options_list=["--plan-only"],
            arg_type=get_three_state_flag(),
            help="Build and return the plan without applying changes.",
        )
        context.argument(
            "output_script",
            options_list=["--output-script"],
            help="Write the planned atomic commands to a shell script.",
        )
        context.argument(
            "yes",
            options_list=["--yes", "-y"],
            arg_type=get_three_state_flag(),
            help="Apply without a confirmation prompt.",
        )
