# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.monitor.central_validator import validate_schema


def validate(schema: dict, value: dict):
    if not isinstance(schema, dict):
        return False

    if not isinstance(value, dict):
        return False

    fields = schema.get("schema", {}).get("fields", [])
    schema_fields = {field["name"]: field for field in fields}

    for key, val in value.items():
        if key not in schema_fields:
            return False

        if not validate_schema.validate(schema_fields[key], val):
            return False

    return True
