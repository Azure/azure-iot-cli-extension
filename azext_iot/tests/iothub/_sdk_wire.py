# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Adapt existing Hub request spies to the real Azure Core transport boundary."""

import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import requests
from azure.core.rest._requests_basic import RestRequestsTransportResponse
from msrest.service_client import ServiceClient


def legacy_spy_response(request):
    """Keep historical body assertions while observing the regenerated wire request."""
    assert parse_qs(urlsplit(request.url).query)["api-version"] == ["2026-11-01-preview"]
    data = request.body
    if isinstance(data, (str, bytes)) and data:
        data = json.loads(data)
    result = ServiceClient.send(request, dict(request.headers), data)
    headers = result.headers
    if isinstance(headers, Mock):
        token = headers.get("x-ms-continuation")
        headers = {"x-ms-continuation": token} if token else {}
    response = requests.Response()
    response.status_code = result.status_code
    response.headers.update(headers)
    response._content = result.text.encode("utf-8")  # pylint: disable=protected-access
    response._content_consumed = True  # pylint: disable=protected-access
    response.reason = "OK" if result.status_code < 400 else "Error"
    response.url = request.url
    response.encoding = "utf-8"
    wrapped = RestRequestsTransportResponse(request=request, internal_response=response, block_size=4096)
    wrapped.read()
    return wrapped
