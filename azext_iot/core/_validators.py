# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.cli.core.commands.arm import _get_internal_path, _split_key_value_pair


def validate_dps_unit(value, argument="--unit"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidArgumentValueError(f"{argument} must be an integer greater than or equal to 1.")


def validate_dps_create_unit(namespace):
    validate_dps_unit(namespace.unit)


def capture_dps_capacity_edit(namespace):
    # GenericUpdate consumes ordered_arguments before its getter/custom function.
    # Carry intent separately so even an explicit 0 -> 0 is checked by the setter.
    namespace.dps_capacity_edited = False
    for operation, arguments in getattr(namespace, "ordered_arguments", []):
        paths = arguments if operation == "--set" else arguments[:1]
        for expression in paths:
            key = _split_key_value_pair(expression)[0] if operation == "--set" else expression
            path = [segment.lower() for segment in _get_internal_path(key)]
            if path and path[0] == "sku" and (len(path) == 1 or path[1] == "capacity"):
                namespace.dps_capacity_edited = True


def validate_dps_capacity_update(parameters):
    # Modeless generic update preserves dictionary casing. Check aliases too,
    # rather than allowing a second SKU/capacity spelling to bypass validation.
    skus = [value for key, value in parameters.items() if key.lower() == "sku"]
    for sku in skus or [None]:
        capacities = (
            [value for key, value in sku.items() if key.lower() == "capacity"] if isinstance(sku, dict) else []
        )
        for capacity in capacities or [None]:
            validate_dps_unit(capacity, "sku.capacity")
