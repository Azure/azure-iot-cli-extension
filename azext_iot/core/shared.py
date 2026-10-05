# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums).

"""

from enum import Enum


class IotDpsSku(Enum):
    """DPS SKU name."""

    S1 = "S1"
