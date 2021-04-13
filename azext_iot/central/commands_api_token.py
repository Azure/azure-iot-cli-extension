# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.enum import Role
from azext_iot.central.providers.preview import CentralApiTokenProviderPreview
from azext_iot.central.providers.v1 import CentralApiTokenProviderV1
from azext_iot.constants import IOTC_VERSION_PREVIEW
from azext_iot.constants import IOTC_VERSION_V1
from azext_iot.central.utils import process_version
from azext_iot.central.utils import throw_unsupported_version

def add_api_token(
    cmd,
    app_id: str,
    token_id: str,
    role: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralApiTokenProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralApiTokenProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)
    
    return provider.add_api_token(
        token_id=token_id, role=Role[role], central_dns_suffix=central_dns_suffix,
    )


def list_api_tokens(
    cmd, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralApiTokenProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralApiTokenProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.get_api_token_list(central_dns_suffix=central_dns_suffix,)


def get_api_token(
    cmd, app_id: str, token_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralApiTokenProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralApiTokenProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.get_api_token(
        token_id=token_id, central_dns_suffix=central_dns_suffix
    )


def delete_api_token(
    cmd, app_id: str, token_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [IOTC_VERSION_PREVIEW, IOTC_VERSION_V1]
    version = process_version(supported_versions, version)
    if(version == IOTC_VERSION_PREVIEW):
        provider = CentralApiTokenProviderPreview(cmd=cmd, app_id=app_id, token=token)
    elif(version == IOTC_VERSION_V1):
        provider = CentralApiTokenProviderV1(cmd=cmd, app_id=app_id, token=token)
    else:
        throw_unsupported_version(supported_versions)

    return provider.delete_api_token(
        token_id=token_id, central_dns_suffix=central_dns_suffix
    )
