# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def extract_schema_type(schema: dict):
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("schema")
    # some kind of error with getting the device template
    if not schema_type:
        return

    # Custom defined complex types store schema as dict
    if not isinstance(schema_type, str):
        schema_type = schema_type["@type"]

    # If template is retrieved through API, the type info is in a list
    # Extract the first item
    # TODO: update this work around once IoTC has consistency between API and UX
    if isinstance(schema_type, list):
        schema_type = schema_type[0]

    return schema_type
