# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot.core._validators import validate_dps_capacity_update


@pytest.mark.parametrize("parameters", [{}, {"sku": None}])
def test_validate_dps_capacity_update_reports_removed_sku(parameters):
    with pytest.raises(InvalidArgumentValueError, match="sku is required and cannot be removed"):
        validate_dps_capacity_update(parameters)


@pytest.mark.parametrize("parameters", [{"sku": {}}, {"sku": {"capacity": None}}, {"sku": {"name": "S1"}}])
def test_validate_dps_capacity_update_reports_missing_capacity(parameters):
    with pytest.raises(InvalidArgumentValueError, match="sku.capacity is required"):
        validate_dps_capacity_update(parameters)


@pytest.mark.parametrize("capacity", [0, -1, 1.5, True, "1"])
def test_validate_dps_capacity_update_reports_invalid_capacity(capacity):
    with pytest.raises(InvalidArgumentValueError, match="sku.capacity must be an integer"):
        validate_dps_capacity_update({"sku": {"capacity": capacity}})


@pytest.mark.parametrize("parameters", [{"sku": {"capacity": 1}}, {"Sku": {"Capacity": 2}}])
def test_validate_dps_capacity_update_accepts_valid_capacity(parameters):
    validate_dps_capacity_update(parameters)
