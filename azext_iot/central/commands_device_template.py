# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.central.models.v2022_06_30_preview import TemplatePreview
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.common import utility
from azext_iot.central.providers import CentralDeviceTemplateProvider
from azext_iot.central.common import API_VERSION_PREVIEW


def get_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
) -> TemplatePreview:
    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    template = provider.get_device_template(
        device_template_id=device_template_id,
        central_dns_suffix=central_dns_suffix,
    )
    return template.raw_template


def list_device_templates(
    cmd,
    app_id: str,
    compact=False,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    templates = provider.list_device_templates(
        compact=compact, central_dns_suffix=central_dns_suffix
    )
    return templates


def map_device_templates(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.map_device_templates(central_dns_suffix=central_dns_suffix)


def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    template = provider.create_device_template(
        device_template_id=device_template_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )
    return template.raw_template


def update_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    template = provider.update_device_template(
        device_template_id=device_template_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )
    return template.raw_template


def delete_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION_PREVIEW,
):
    provider = CentralDeviceTemplateProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_device_template(
        device_template_id=device_template_id,
        central_dns_suffix=central_dns_suffix,
    )
