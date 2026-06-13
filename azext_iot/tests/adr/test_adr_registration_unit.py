# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the ADR command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table.
"""

from unittest.mock import MagicMock

import azext_iot.adr._help  # noqa: F401  (covered on import)
from azext_iot.adr.command_map import load_adr_commands
from azext_iot.adr.params_adr_management import load_adr_management_arguments


def test_load_adr_commands():
    load_adr_commands(MagicMock(), None)


def test_load_adr_management_arguments():
    load_adr_management_arguments(MagicMock(), None)
