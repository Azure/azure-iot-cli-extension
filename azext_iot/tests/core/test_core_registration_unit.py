# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the IoT Hub/DPS core command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table. The
result-transform classes do contain logic and are covered explicitly.
"""

from unittest.mock import MagicMock

import pytest
from azure.cli.core.util import CLIError

from azext_iot.core.command_map import (
    load_core_commands,
    PolicyUpdateResultTransform,
    EndpointUpdateResultTransform,
    RouteUpdateResultTransform,
    HubDeleteResultTransform,
)
from azext_iot.core.params import load_core_arguments
from azext_iot.core.help import patch_core_help

cm_path = "azext_iot.core.command_map"


def test_load_core_commands():
    load_core_commands(MagicMock(), None)


def test_load_core_arguments():
    load_core_arguments(MagicMock(), None)


def test_patch_core_help_with_existing_keys():
    from knack.help_files import helps

    # Pre-populate the help keys so the conditional append branches execute.
    helps["iot hub create"] = "type: command"
    helps["iot dps create"] = "type: command"
    patch_core_help()
    assert "iot dps identity" in helps


def test_policy_update_result_transform(mocker):
    transform = PolicyUpdateResultTransform(MagicMock())
    result = {"properties": {"authorizationPolicies": ["p"]}}
    mocker.patch(f"{cm_path}.LongRunningOperation.__call__", return_value=result)
    assert transform("poller") == ["p"]


def test_endpoint_update_result_transform(mocker):
    transform = EndpointUpdateResultTransform(MagicMock())
    result = {"properties": {"routing": {"endpoints": ["e"]}}}
    mocker.patch(f"{cm_path}.LongRunningOperation.__call__", return_value=result)
    assert transform("poller") == ["e"]


def test_route_update_result_transform(mocker):
    transform = RouteUpdateResultTransform(MagicMock())
    result = {"properties": {"routing": {"routes": ["r"]}}}
    mocker.patch(f"{cm_path}.LongRunningOperation.__call__", return_value=result)
    assert transform("poller") == ["r"]


def test_hub_delete_result_transform_no_poller():
    transform = HubDeleteResultTransform(MagicMock())
    assert transform(None) is None


def test_hub_delete_result_transform_not_found_suppressed(mocker):
    transform = HubDeleteResultTransform(MagicMock())
    mocker.patch(
        f"{cm_path}.LongRunningOperation.__call__",
        side_effect=CLIError("resource not found"),
    )
    # 'not found' errors are suppressed and return None.
    assert transform("poller") is None


def test_hub_delete_result_transform_other_error_raised(mocker):
    transform = HubDeleteResultTransform(MagicMock())
    mocker.patch(
        f"{cm_path}.LongRunningOperation.__call__",
        side_effect=CLIError("something else"),
    )
    with pytest.raises(CLIError):
        transform("poller")
