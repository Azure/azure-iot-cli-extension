# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from azext_iot.common.utility import ISO8601Validator
from azext_iot.monitor.central_validator import enum, obj, utils
from azext_iot.monitor.central_validator.predefinied_complex_validator import (
    validate_vector,
    validate_geopoint,
)

iso_validator = ISO8601Validator()

validation_function_factory = {
    # primitive
    "boolean": lambda schema, value: isinstance(value, bool),
    "double": lambda schema, value: isinstance(value, (float, int)),
    "float": lambda schema, value: isinstance(value, (float, int)),
    "integer": lambda schema, value: isinstance(value, int),
    "long": lambda schema, value: isinstance(value, (float, int)),
    "string": lambda schema, value: isinstance(value, str),
    # primitive - time
    "time": lambda schema, value: iso_validator.is_iso8601_time(value),
    "date": lambda schema, value: iso_validator.is_iso8601_date(value),
    "dateTime": lambda schema, value: iso_validator.is_iso8601_datetime(value),
    "duration": lambda schema, value: iso_validator.is_iso8601_duration(value),
    # pre-defined complex
    "vector": lambda schema, value: validate_vector(value),
    "geopoint": lambda schema, value: validate_geopoint(value),
    # complex
    "Enum": enum.validate,
    "Object": obj.validate,
    # TODO: yet to be enabled in prod "Map": lambda val: False,
    # TODO: yet to be implemented in prod "Array": lambda val: False,
}


def validate(schema, value):
    # if theres nothing to validate, then its valid
    if value is None:
        return True

    schema_type = utils.extract_schema_type(schema)
    if not schema_type:
        return False

    validate_function = validation_function_factory.get(schema_type)

    # invalid schema type detected
    if not validate_function:
        return False

    return validate_function(schema, value)
