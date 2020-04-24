# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.central.providers.device_provider import CentralDeviceProvider
from azext_iot.central.providers.device_template_provider import (
    CentralDeviceTemplateProvider,
)

__all__ = ["CentralDeviceProvider", "CentralDeviceTemplateProvider"]
