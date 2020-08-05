# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""

from azure.cli.core.commands.parameters import get_enum_type
from azext_iot.product.shared import BadgeType


def load_product_params(self, _):
    with self.argument_context("iot product") as c:
        c.argument(
            "test_id",
            options_list=["--test-id", "-t"],
            help="The generated Id for the device certification test",
            arg_group="IoT Device Certification",
        )
        c.argument(
            "badge_type",
            options_list=["--badge-type", "--bt"],
            help="The type of certification badge",
            arg_group="IoT Device Certification",
            arg_type=get_enum_type(BadgeType),
        )
        c.argument(
            "base_url",
            options_list=["--base-url"],
            help="Override certification service URL to allow testing in non-production environements.",
            arg_group="Development Settings"
        )

    # load az iot product test parameters
    from azext_iot.product.test.params import load_product_test_params
    load_product_test_params(self, _)
