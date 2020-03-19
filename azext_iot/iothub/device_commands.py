# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider


logger = get_logger(__name__)


def get_device_metrics(cmd, hub_name=None, resource_group_name=None, login=None):
    device_provider = DeviceIdentityProvider(cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login)
    return device_provider.get_device_stats()
