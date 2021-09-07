# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Nothing in this file should be used outside of service/central

from knack.util import CLIError, to_snake_case
from requests import Response
from knack.log import logging

from azext_iot import constants
from azext_iot.common import auth

import uuid
from importlib import import_module
from azext_iot.central.models.enum import ApiVersion


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


def get_object(data: dict, model: str, api_version):
    try:
        if api_version == ApiVersion.v1.value:
            module = getattr(
                import_module(
                    "azext_iot.central.models.v1.{}".format(to_snake_case(model))
                ),
                model,
            )
            return module(data)

        elif api_version == ApiVersion.v2.value:
            module = getattr(
                import_module(
                    "azext_iot.central.models.v2.{}".format(to_snake_case(model))
                ),
                model,
            )
            return module(data)
        else:
            module = getattr(
                import_module(
                    "azext_iot.central.models.preview.{}".format(to_snake_case(model))
                ),
                model,
            )
            return module(data)
    except Exception as e:
        print(e)
        raise CLIError(
            "{} is not available for api version == {}".format(model, api_version)
        )
