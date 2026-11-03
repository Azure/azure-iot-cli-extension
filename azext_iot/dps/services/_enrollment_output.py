# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy

from msrest.serialization import Model


def enrollment_group_output(enrollment, show_keys=False):
    """Redact only the output copy, retaining the SDK's response representation."""
    result = deepcopy(enrollment)
    if show_keys:
        return result
    if isinstance(result, dict):
        attestation = result.get("attestation") or {}
        keys = attestation.get("symmetricKey") or {}
        keys.pop("primaryKey", None)
        keys.pop("secondaryKey", None)
    elif isinstance(result, Model):
        attestation = getattr(result, "attestation", None)
        keys = getattr(attestation, "symmetric_key", None)
        if keys is not None:
            keys.primary_key = None
            keys.secondary_key = None
    else:
        raise TypeError("Unsupported enrollment-group response representation.")
    return result
