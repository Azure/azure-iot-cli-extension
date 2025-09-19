# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------


def validate(schema, value):
    if not isinstance(schema, dict):
        return False

    # schema.schema.enumValues, but done safely
    enum_values = schema.get("schema", {}).get("enumValues", [])

    allowed_values = [item["enumValue"] for item in enum_values if "enumValue" in item]

    return value in allowed_values
