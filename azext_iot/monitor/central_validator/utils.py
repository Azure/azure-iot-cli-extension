# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


def extract_schema_type(schema: dict):
    # some error with parsing schema
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("schema")
    # some error with parsing schema
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
