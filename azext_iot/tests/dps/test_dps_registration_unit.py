# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the DPS command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table.
"""

from unittest.mock import MagicMock

from azext_iot.dps._help import load_deviceprovisioningservice_help
from azext_iot.dps.command_map import load_dps_commands
from azext_iot.dps.params import load_dps_arguments


def test_load_dps_help():
    load_deviceprovisioningservice_help()


def test_load_dps_commands():
    load_dps_commands(MagicMock(), None)


def test_load_dps_arguments():
    load_dps_arguments(MagicMock(), None)
