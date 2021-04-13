# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.common import utility
from azext_iot.central.providers.preview import CentralDeviceTemplateProviderPreview
from azext_iot.central.providers.v1 import CentralDeviceTemplateProviderV1
from azext_iot.central.utils import process_version
from azext_iot.central.utils import throw_unsupported_version
from azext_iot.constants import IOTC_VERSION_PREVIEW
from azext_iot.constants import IOTC_VERSION_V1

def get_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]  
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralDeviceTemplateProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralDeviceTemplateProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.get_device_template(
        device_template_id=device_template_id, central_dns_suffix=central_dns_suffix
    )

def create_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    content: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]  
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralDeviceTemplateProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralDeviceTemplateProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.create_device_template(
        device_template_id=device_template_id,
        payload=payload,
        central_dns_suffix=central_dns_suffix,
    )


def delete_device_template(
    cmd,
    app_id: str,
    device_template_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]  
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralDeviceTemplateProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralDeviceTemplateProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.delete_device_template(
        device_template_id=device_template_id, central_dns_suffix=central_dns_suffix
    )
