# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/fileuploads

import requests
from typing import Union
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.common import API_VERSION
from azext_iot.central.models.ga_2022_07_31 import FileUploadGa
from azure.cli.core.util import should_disable_connection_verify


logger = get_logger(__name__)

BASE_PATH = "api/fileUploads"
MODEL = "FileUpload"


def _make_call(
    cmd,
    app_id: str,
    method: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[dict, FileUploadGa]:
    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    response = requests.request(
        url=url,
        method=method.upper(),
        headers=headers,
        params=query_parameters,
        verify=not should_disable_connection_verify(),
    )
    return _utility.try_extract_result(response)


def get_fileupload(
    cmd,
    app_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> FileUploadGa:
    """
    Get fileupload info
    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch fileupload details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        fileupload: dict
    """
    api_version = API_VERSION

    result = _make_call(
        cmd,
        app_id,
        "get",
        token=token,
        api_version=api_version,
        central_dns_suffix=central_dns_suffix,
    )

    return _utility.get_object(result, MODEL, api_version)


def delete_fileupload(
    cmd, app_id: str, token: str, api_version=API_VERSION, central_dns_suffix=CENTRAL_ENDPOINT
) -> FileUploadGa:
    """
    Delete file upload storage configuration

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch fileupload details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        fileupload: dict
    """
    api_version = API_VERSION

    result = _make_call(
        cmd,
        app_id,
        "delete",
        token=token,
        api_version=api_version,
        central_dns_suffix=central_dns_suffix,
    )

    return result


def createorupdate_fileupload(
    cmd,
    app_id: str,
    connection_string: str,
    container: str,
    account: str,
    sasTtl: bool,
    token: str,
    api_version=API_VERSION,
    update=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> FileUploadGa:
    """
    Create the file upload storage account configuration.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        connection_string: The connection string used to configure the storage account
        container: The name of the container inside the storage account
        account: (optional) The storage account name where to upload the file to
        sasTtl: (optional) ISO 8601 duration standard,
                The amount of time the device’s request to upload a file is valid before it expires.
        token: (OPTIONAL) authorization token to fetch file upload details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        fileupload: dict
    """
    api_version = API_VERSION

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    payload = {}
    if connection_string:
        payload["connectionString"] = connection_string
    if container:
        payload["container"] = container
    if account:
        payload["account"] = account
    if sasTtl:
        payload["sasTtl"] = sasTtl

    if update:
        response = requests.patch(
            url, headers=headers, json=payload, params=query_parameters
        )
    else:
        response = requests.put(
            url, headers=headers, json=payload, params=query_parameters
        )
    result = _utility.try_extract_result(response)

    return _utility.get_object(result, MODEL, api_version)
