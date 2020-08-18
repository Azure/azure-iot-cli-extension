# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for Product Certification commands.
"""

from knack.help_files import helps


def load_help():
    helps[
        "iot product"
    ] = """
        type: group
        short-summary: Manage device testing for product certification
    """
    # certification requirements
    helps[
        "iot product requirement"
    ] = """
        type: group
        short-summary: Manage product certification requirements
    """
    helps[
        "iot product requirement list"
    ] = """
        type: command
        short-summary: Discover information about provisioning attestation methods that are supported for each badge type
        examples:
        - name: Basic usage
          text: >
            az iot product requirement list
    """
