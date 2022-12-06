# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger

from azext_iot.common.utility import shell_safe_json_parse
from azure.cli.core.azclierror import InvalidArgumentValueError

logger = get_logger(__name__)


invalid_arg_error_str = "Failure processing json string for '{property_name}'. Interpreted value '{inline_json}'. "
use_help_warning = "Please append --help to review examples and json input rules across supported shells."


def parse_manifest_json(inline_json: str, property_name: str) -> dict:
    try:
        result = shell_safe_json_parse(inline_json)
        if not isinstance(result, dict):
            raise InvalidArgumentValueError(f"{property_name} must be an object, parsed type: {type(result)}.")
        return result
    except Exception:
        logger.warning(use_help_warning)
        raise InvalidArgumentValueError(invalid_arg_error_str.format(property_name=property_name, inline_json=inline_json))
