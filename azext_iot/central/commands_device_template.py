# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError

from azext_iot.common import utility
from .providers import CentralDeviceTemplateProvider


def show_device_template(
    cmd, app_id: str, device_template_id: str, central_dns_suffix="azureiotcentral.com"
):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.show_device_template(
        device_template_id=device_template_id, central_dns_suffix=central_dns_suffix
    )


def list_device_templates(cmd, app_id: str, central_dns_suffix="azureiotcentral.com"):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.list_device_templates(central_dns_suffix=central_dns_suffix)


def map_device_templates(cmd, app_id: str, central_dns_suffix="azureiotcentral.com"):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.map_device_templates(central_dns_suffix=central_dns_suffix)


def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
    central_dns_suffix="azureiotcentral.com",
):
    if not type(content) == str:
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.create_device_template(
        device_template_id=device_template_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def delete_device_template(
    cmd, app_id: str, device_template_id: str, central_dns_suffix="azureiotcentral.com"
):
    provider = CentralDeviceTemplateProvider(cmd, app_id)
    return provider.delete_device_template(
        device_template_id=device_template_id, central_dns_suffix=central_dns_suffix
    )
