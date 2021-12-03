# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
#

from typing import Union

from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.v1_1_preview import QueryReponseV1_1_preview

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

    # Construct parameters
    payload = {"query": query}
    return _utility.make_api_call(
        cmd,
        method="POST",
        app_id=app_id,
        url=url,
        payload=payload,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
