# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from .providers import CentralDeviceTemplateProvider


def show_device_template(cmd, app_id, device_template_id):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.show_device_template(device_template_id)


def list_device_templates(cmd, app_id):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.list_device_templates()
