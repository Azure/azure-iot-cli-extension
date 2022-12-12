# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
from azext_iot.tests.generators import generate_generic_id


@pytest.mark.parametrize(
    "json_input, expect_error",
    [
        ('{"test_case1": "test_value1"}', False),
        ('{test_case: test_value1}', True),
    ],
)
def test_parse_manifest_json(json_input: str, expect_error: bool, mocker):
    from azext_iot.deviceupdate.providers.utility import parse_manifest_json, invalid_arg_error_str, use_help_warning

    logger_mock = mocker.patch("azext_iot.deviceupdate.providers.utility.logger")

    thrown_error = None
    parsed_prop_name = generate_generic_id()
    try:
        result = parse_manifest_json(json_input, parsed_prop_name)
        assert result == json.loads(json_input)
    except Exception as e:
        thrown_error = e

    if expect_error:
        if not thrown_error:
            pytest.fail(reason="Test is expecting an error but none was thrown!")
        else:
            assert invalid_arg_error_str.format(property_name=parsed_prop_name, inline_json=json_input) == str(thrown_error)
            logger_mock.warning.mock_calls[0].args == (use_help_warning,)
