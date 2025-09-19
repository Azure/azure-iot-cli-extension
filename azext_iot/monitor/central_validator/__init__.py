# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from azext_iot.monitor.central_validator.validate_schema import validate
from azext_iot.monitor.central_validator.utils import extract_schema_type

__all__ = ["validate", "extract_schema_type"]
