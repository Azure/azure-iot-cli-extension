# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
#

from typing import Union
import requests

from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.v1_1_preview import QueryReponseV1_1_preview
from azure.cli.core.util import should_disable_connection_verify

logger = get_logger(__name__)

BASE_PATH = "api/query"


def query_run(
    cmd,
    app_id: str,
    query: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[dict, QueryReponseV1_1_preview]:
    """
    Execute query to get the telemetry or property data

    Agrs:
        cmd: command passed into az
        query: query syntax sent to query AP
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch role details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    returns:
        queryReponse: dict
    """

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version
    payload = {"query": query}
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        params=query_parameters,
        verify=not should_disable_connection_verify(),
    )
    return _utility.try_extract_result(response)
