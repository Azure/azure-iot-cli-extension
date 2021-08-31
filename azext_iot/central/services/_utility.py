# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Nothing in this file should be used outside of service/central

from knack.util import CLIError
from requests import Response
from knack.log import logging

from azext_iot import constants
from azext_iot.common import auth
import uuid


def get_headers(token, cmd, has_json_payload=False):
    if not token:
        aad_token = auth.get_aad_token(cmd, resource="https://apps.azureiotcentral.com")
        token = "Bearer {}".format(aad_token["accessToken"])

    headers = {
        "Authorization": token,
        "User-Agent": constants.USER_AGENT,
        "x-ms-client-request-id": str(uuid.uuid1()),
    }

    if has_json_payload:
        headers["Content-Type"] = "application/json"
    
    return headers


def try_extract_result(response: Response):
    # 201 and 204 response codes indicate success
    # with no content, hence attempting to retrieve content will fail
    if response.status_code in [201, 204]:
        return {"result": "success"}

    try:
        body = response.json()
    except:
        raise CLIError("Error parsing response body")

    if "error" in body:
        raise CLIError(body["error"])

    return body


def log_response_debug(response: Response, logger: logging.Logger):
    logger.debug("Response status code: {}".format(response.status_code))
    logger.debug("Response url: {}".format(response.url))
    logger.debug("Response headers: {}".format(response.headers))
