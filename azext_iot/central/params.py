# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Unpublished works.
# --------------------------------------------------------------------------------------------

"""
CLI parameter definitions.
"""


def load_digitaltwins_arguments(self, _):
    """
    Load CLI Args for Knack parser
    """
    with self.argument_context("iot central") as context:
        context.argument(
            "model_id",
            options_list=["--model-id"],
            help="ADT Model Id. Example: urn:contosocom:DigitalTwins:Space:1",
        )
