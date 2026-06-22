# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the IoT Hub command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table.
"""

from unittest.mock import MagicMock

from azext_iot.iothub._help import load_iothub_help
from azext_iot.iothub.command_map import load_iothub_commands
from azext_iot.iothub.params import load_iothub_arguments


def test_load_iothub_help():
    load_iothub_help()


def test_load_iothub_commands():
    load_iothub_commands(MagicMock(), None)


def test_load_iothub_arguments():
    load_iothub_arguments(MagicMock(), None)


def test_endpoint_update_result_transform(mocker):
    from azext_iot.iothub.command_map import EndpointUpdateResultTransform

    transform = EndpointUpdateResultTransform(MagicMock())
    result = {"properties": {"routing": {"endpoints": ["e"]}}}
    mocker.patch(
        "azext_iot.iothub.command_map.LongRunningOperation.__call__",
        return_value=result,
    )
    assert transform("poller") == ["e"]


def test_route_update_result_transform(mocker):
    from azext_iot.iothub.command_map import RouteUpdateResultTransform

    transform = RouteUpdateResultTransform(MagicMock())
    result = {"properties": {"routing": {"routes": ["r"]}}}
    mocker.patch(
        "azext_iot.iothub.command_map.LongRunningOperation.__call__",
        return_value=result,
    )
    assert transform("poller") == ["r"]
