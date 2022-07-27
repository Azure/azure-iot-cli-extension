# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def load_iothub_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot hub digital-twin") as context:
        context.argument(
            "command_name",
            options_list=["--command-name", "--cn"],
            help="Digital twin command name.",
        )
        context.argument(
            "component_path",
            options_list=["--component-path"],
            help="Digital twin component path. For example: thermostat1.",
        )
        context.argument(
            "json_patch",
            options_list=["--json-patch", "--patch"],
            help="An update specification described by JSON-patch. "
            "Operations are limited to add, replace and remove. Provide file path or inline JSON.",
        )
        context.argument(
            "payload",
            options_list=["--payload"],
            help="JSON payload input for command. Provide file path or inline JSON.",
        )
        context.argument(
            "connect_timeout",
            type=int,
            options_list=["--connect-timeout", "--cto"],
            help="Maximum interval of time, in seconds, that IoT Hub will attempt to connect to the device.",
            arg_group="Timeout"
        )
        context.argument(
            "response_timeout",
            type=int,
            options_list=["--response-timeout", "--rto"],
            help="Maximum interval of time, in seconds, that the digital twin command will wait for the result.",
            arg_group="Timeout"
        )
