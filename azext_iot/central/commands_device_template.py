# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.common import utility
from azext_iot.central.providers import CentralDeviceTemplateProvider
from azext_iot.sdk.central.ga_2022_05_31.models import DeviceTemplate


def get_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
) -> DeviceTemplate:
    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    template = provider.get(device_template_id=device_template_id)
    return template.raw_template


def list_device_templates(
    cmd,
    app_id: str,
    compact=False,
):
    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    templates = provider.list(compact=compact)
    return templates


def map_device_templates(
    cmd,
    app_id: str,
):
    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    return provider.map()


def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    template = provider.create(
        device_template_id=device_template_id,
        payload=payload,
    )
    return template.raw_template


def update_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)
    template = provider.update(
        device_template_id=device_template_id,
        payload=payload,
    )
    return template.raw_template


def delete_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
):
    provider = CentralDeviceTemplateProvider(cmd=cmd, app_id=app_id)

    return provider.delete(device_template_id=device_template_id)
