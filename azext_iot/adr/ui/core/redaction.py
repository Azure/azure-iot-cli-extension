# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Remove credentials from service payloads before the UI retains or renders them."""

from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_FIELDS = {
    "connectionstring",
    "primaryconnectionstring",
    "primarykey",
    "secondaryconnectionstring",
    "secondarykey",
    "sharedaccesskey",
}


def redact(value: Any) -> Any:
    """Return a recursively copied value with known credential fields replaced."""
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).casefold() in _SENSITIVE_FIELDS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
