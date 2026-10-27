# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the Device Update command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table.
"""

from unittest.mock import MagicMock

from azext_iot.deviceupdate._help import load_deviceupdate_help
from azext_iot.deviceupdate.command_map import load_deviceupdate_commands
from azext_iot.deviceupdate.params import load_deviceupdate_arguments


def test_load_deviceupdate_help():
    load_deviceupdate_help()


def test_load_deviceupdate_commands():
    load_deviceupdate_commands(MagicMock(), None)


def test_load_deviceupdate_arguments():
    load_deviceupdate_arguments(MagicMock(), None)
