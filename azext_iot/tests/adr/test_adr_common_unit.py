# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import InvalidArgumentValueError
import pytest

from azext_iot.adr.common import validate_iso8601_datetime


def test_validate_iso8601_datetime_chains_value_errors():
    with pytest.raises(InvalidArgumentValueError) as raised:
        validate_iso8601_datetime("not-a-date")

    assert isinstance(raised.value.__cause__, ValueError)


def test_validate_iso8601_datetime_chains_type_errors(mocker):
    parse = mocker.patch(
        "azext_iot.adr.common.isodate.parse_datetime",
        side_effect=TypeError("bad type"),
    )

    with pytest.raises(InvalidArgumentValueError) as raised:
        validate_iso8601_datetime("2026-11-02T12:00:00Z")

    parse.assert_called_once_with("2026-11-02T12:00:00Z")
    assert isinstance(raised.value.__cause__, TypeError)
