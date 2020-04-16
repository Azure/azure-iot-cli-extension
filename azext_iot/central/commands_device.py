# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from .providers import CentralDeviceProvider


def list_devices(cmd, app_id):
    provider = CentralDeviceProvider(cmd, app_id)
    return provider.list_devices()


def show_device(cmd, app_id, device_id):
    provider = CentralDeviceProvider(cmd, app_id)
    return provider.show_device(device_id)
