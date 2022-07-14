# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller


from typing import Optional

from azure.cli.core.azclierror import RequiredArgumentMissingError
from azext_iot.central.providers import CentralFileUploadProvider
from azext_iot.sdk.central.ga_2022_05_31.models import FileUpload


def get_fileupload(
    cmd,
    app_id: str,
) -> FileUpload:
    provider = CentralFileUploadProvider(cmd=cmd, app_id=app_id)
    return provider.get()


def delete_fileupload(
    cmd,
    app_id: str,
) -> FileUpload:
    provider = CentralFileUploadProvider(cmd=cmd, app_id=app_id)
    return provider.delete()


def create_fileupload(
    cmd,
    app_id: str,
    connection_string: str,
    container: str,
    account: Optional[str] = None,
    sasTtl: Optional[str] = None,
) -> FileUpload:
    provider = CentralFileUploadProvider(cmd=cmd, app_id=app_id)
    return provider.create(
        connection_string=connection_string,
        container=container,
        account=account,
        sasTtl=sasTtl,
    )


def update_fileupload(
    cmd,
    app_id: str,
    connection_string: Optional[str] = None,
    container: Optional[str] = None,
    account: Optional[str] = None,
    sasTtl: Optional[str] = None,
) -> FileUpload:
    if not connection_string and not container and not account and not sasTtl:
        raise RequiredArgumentMissingError('You must specify at least one parameter to update.')

    provider = CentralFileUploadProvider(cmd=cmd, app_id=app_id)
    return provider.update(
        connection_string=connection_string,
        container=container,
        account=account,
        sasTtl=sasTtl,
    )
