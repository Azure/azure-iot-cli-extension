# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralFileUploadProvider
from azext_iot.central.models.enum import ApiVersion


def get_fileupload(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralFileUploadProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_fileupload(central_dns_suffix=central_dns_suffix)


def delete_fileupload(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralFileUploadProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.delete_fileupload(central_dns_suffix=central_dns_suffix)


def create_fileupload(
    cmd,
    app_id: str,
    connection_string: str,
    container: str,
    account=None,
    sasTtl=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
):
    provider = CentralFileUploadProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.create_fileupload(
        connection_string=connection_string,
        container=container,
        account=account,
        sasTtl=sasTtl,
        central_dns_suffix=central_dns_suffix,
    )
