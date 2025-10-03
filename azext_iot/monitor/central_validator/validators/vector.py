# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def validate(schema, value: dict):
    required_keys = set(["x", "y", "z"])
    if not isinstance(value, dict):
        return False

    # check that value has all required keys
    if set(value.keys()) != required_keys:
        return False

    # check that all values are double
    for val in value.values():
        if not isinstance(val, (float, int)):
            return False

    return True
