# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.monitor.central_validator.validate_schema import validate
from azext_iot.monitor.central_validator.utils import extract_schema_type

__all__ = ["validate", "extract_schema_type"]
