# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Unpublished works.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azure.cli.core.commands.parameters import get_three_state_flag


def load_central_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot central app") as context:
        context.argument(
            "instance_of",
            options_list=["--instance-of"],
            help="Central model id. Example: urn:ojpkindbz:modelDefinition:iild3tm_uo",
        )
        context.argument(
            "device_name",
            options_list=["--device-name"],
            help="Human readable device name. Example: Fridge",
        )
        context.argument(
            "simulated",
            options_list=["--simulated"],
            arg_type=get_three_state_flag(),
            help="Add this flag if you would like IoT Central to set this up as a simulated device. "
            "--instance-of is required if this is true",
        )
        context.argument(
            "device_template_id",
            options_list=["--device-template-id"],
            help="Device template id. Example: somedevicetemplate",
        )
        context.argument(
            "content",
            options_list=["--content", "-k"],
            help="Configuration for request. "
            "Provide path to JSON file or raw stringified JSON. "
            "[File Path Example: ./path/to/file.json] "
            "[Stringified JSON Example: {'a': 'b'}] ",
        )
        context.argument(
            "token",
            options_list=["--token"],
            help="Authorization token for request. "
            "More info available here: https://docs.microsoft.com/en-us/learn/modules/manage-iot-central-apps-with-rest-api/ "
            "MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...'). "
            "Example: 'Bearer someBearerTokenHere'",
        )
        context.argument(
            "central_dns_suffix",
            options_list=["--central-dns-suffix"],
            help="Central dns suffix. "
            "This enables running cli commands against non public/prod environments",
        )
